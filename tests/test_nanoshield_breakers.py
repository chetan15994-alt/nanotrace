"""Comprehensive Unit & Functional Tests for NanoShield In-Process Circuit Breakers."""

import os
import time
import pytest

import nanotrace
from nanotrace.exceptions import CircuitBreakerTrip
from nanotrace.guardrails.breakers import (
    MaxLoopBreaker,
    BudgetCapBreaker,
    MaxTokenBreaker,
    PIIRedaction,
    TimeoutBreaker,
    get_trace_state,
    clear_trace_state,
)
from nanotrace.schema.otel import GenAIAttributes, StatusCode


@pytest.fixture(autouse=True)
def clean_env(tmp_path):
    db_file = str(tmp_path / "shield_test.duckdb")
    tracer = nanotrace.init(storage_path=db_file, buffer_capacity=1000, flush_interval=0.01)
    yield tracer, db_file
    try:
        tracer.shutdown()
    except Exception:
        pass


def test_max_loop_breaker_trace_scope(clean_env):
    tracer, db_file = clean_env
    loop_breaker = MaxLoopBreaker(limit=3)

    with tracer.span("parent_agent"):
        # 3 iterations should succeed
        for i in range(3):
            with tracer.span("iterative_tool", circuit_breakers=[loop_breaker]) as sp:
                sp.set_attribute(GenAIAttributes.TOOL_NAME, "calculator")

        # 4th iteration must trip
        with pytest.raises(CircuitBreakerTrip) as exc_info:
            with tracer.span("iterative_tool", circuit_breakers=[loop_breaker]) as sp:
                sp.set_attribute(GenAIAttributes.TOOL_NAME, "calculator")

    trip = exc_info.value
    assert trip.breaker_name == "MaxLoopBreaker"
    assert "Runaway recursive loop detected" in trip.reason
    assert trip.metric_value == 4
    assert trip.threshold == 3

    tracer.flush()
    records = tracer.query("SELECT * FROM spans WHERE status = 'ERROR'")
    assert len(records) >= 1
    tripped_span = records[-1]
    import json
    attrs = json.loads(tripped_span["attributes_json"])
    assert attrs.get("nanotrace.shield.tripped") is True
    assert attrs.get("nanotrace.shield.breaker") == "MaxLoopBreaker"


def test_max_loop_breaker_global_scope(clean_env):
    tracer, db_file = clean_env
    loop_breaker = MaxLoopBreaker(limit=2, scope="global")

    # Call 1 & 2 across independent spans
    with tracer.span("global_step_1", circuit_breakers=[loop_breaker]):
        pass
    with tracer.span("global_step_1", circuit_breakers=[loop_breaker]):
        pass

    # Call 3 across independent span must trip
    with pytest.raises(CircuitBreakerTrip) as exc_info:
        with tracer.span("global_step_1", circuit_breakers=[loop_breaker]):
            pass

    assert exc_info.value.breaker_name == "MaxLoopBreaker"
    assert exc_info.value.metric_value == 3


def test_budget_cap_breaker_trace_usd(clean_env):
    tracer, db_file = clean_env
    budget_breaker = BudgetCapBreaker(max_trace_usd=0.05)

    with tracer.span("agent_session"):
        # First turn: cost $0.03 (under $0.05 cap)
        with tracer.span("agent_step_1", circuit_breakers=[budget_breaker]) as sp:
            sp.set_attribute(GenAIAttributes.USAGE_COST_USD, 0.03)

        # Second turn: cost $0.03 (cumulative spend reaches $0.06 > $0.05)
        with tracer.span("agent_step_2", circuit_breakers=[budget_breaker]) as sp:
            sp.set_attribute(GenAIAttributes.USAGE_COST_USD, 0.03)

        # Third turn: must trip pre-execution because cumulative spend ($0.06) >= $0.05
        with pytest.raises(CircuitBreakerTrip) as exc_info:
            with tracer.span("agent_step_3", circuit_breakers=[budget_breaker]) as sp:
                pass

    trip = exc_info.value
    assert trip.breaker_name == "BudgetCapBreaker"
    assert "Cumulative budget exceeded" in trip.reason
    assert trip.metric_value >= 0.05


def test_budget_cap_breaker_turn_usd(clean_env):
    tracer, db_file = clean_env
    budget_breaker = BudgetCapBreaker(max_turn_usd=0.02)

    # Single turn exceeding $0.02 limit should trip post-execution
    with pytest.raises(CircuitBreakerTrip) as exc_info:
        with tracer.span("expensive_turn", circuit_breakers=[budget_breaker]) as sp:
            sp.set_attribute(GenAIAttributes.USAGE_COST_USD, 0.05)

    assert exc_info.value.breaker_name == "BudgetCapBreaker"
    assert "Single turn spend" in exc_info.value.reason


def test_max_token_breaker_total_and_turn(clean_env):
    tracer, db_file = clean_env
    token_breaker = MaxTokenBreaker(max_total_tokens=1000, max_turn_tokens=600)

    # Turn 1: 500 tokens (allowed)
    with tracer.span("call_1", circuit_breakers=[token_breaker]) as sp:
        sp.set_attribute(GenAIAttributes.USAGE_TOTAL_TOKENS, 500)

    # Turn 2: single turn with 700 tokens (> max_turn_tokens 600) -> trips post-execution
    with pytest.raises(CircuitBreakerTrip) as exc_info:
        with tracer.span("call_2", circuit_breakers=[token_breaker]) as sp:
            sp.set_attribute(GenAIAttributes.USAGE_TOTAL_TOKENS, 700)

    assert exc_info.value.breaker_name == "MaxTokenBreaker"
    assert "Single turn tokens" in exc_info.value.reason


def test_pii_redaction_sanitizes_prompt_and_completion(clean_env):
    tracer, db_file = clean_env
    pii = PIIRedaction(action="redact")

    prompt_text = (
        "User sk-proj-123456789012345678901234 sent email test.user@company.org "
        "and SSN 000-12-3456."
    )
    completion_text = (
        "Confirmed for card 4111-2222-3333-4444 and phone (555) 019-2834."
    )

    with tracer.span("llm_call", circuit_breakers=[pii]) as sp:
        sp.prompt_payload = prompt_text
        sp.completion_payload = completion_text

    assert "[REDACTED]_API_KEY" in sp.prompt_payload
    assert "[REDACTED]_EMAIL" in sp.prompt_payload
    assert "[REDACTED]_SSN" in sp.prompt_payload
    assert "sk-proj-" not in sp.prompt_payload
    assert "test.user@company.org" not in sp.prompt_payload

    assert "[REDACTED]_CREDIT_CARD" in sp.completion_payload
    assert "[REDACTED]_PHONE" in sp.completion_payload
    assert "4111-2222-3333-4444" not in sp.completion_payload
    assert sp.attributes.get("nanotrace.shield.pii_redacted") is True


def test_pii_redaction_blocks_when_configured(clean_env):
    tracer, db_file = clean_env
    pii = PIIRedaction(action="block")

    with pytest.raises(CircuitBreakerTrip) as exc_info:
        with tracer.span("secure_llm_call", circuit_breakers=[pii]) as sp:
            sp.prompt_payload = "Leaking key sk-123456789012345678901234"

    assert exc_info.value.breaker_name == "PIIRedaction"
    assert "Sensitive PII/Credential detected" in exc_info.value.reason


def test_timeout_breaker(clean_env):
    tracer, db_file = clean_env
    timeout_breaker = TimeoutBreaker(timeout_seconds=0.01)

    with tracer.span("parent_agent"):
        time.sleep(0.02)
        with pytest.raises(CircuitBreakerTrip) as exc_info:
            with tracer.span("child_operation", circuit_breakers=[timeout_breaker]) as sp:
                pass

    assert exc_info.value.breaker_name == "TimeoutBreaker"
    assert "Execution timeout" in exc_info.value.reason


def test_trace_tool_and_agent_decorator_with_shield(clean_env):
    tracer, db_file = clean_env
    loop_breaker = MaxLoopBreaker(limit=2)

    @tracer.trace_tool(circuit_breakers=[loop_breaker])
    def search_docs(query: str):
        return f"Results for {query}"

    with tracer.span("agent_session"):
        # Call 1 & 2 succeed
        r1 = search_docs("first query")
        r2 = search_docs("second query")
        assert "Results for" in r1 and "Results for" in r2

        # Call 3 must trip
        with pytest.raises(CircuitBreakerTrip):
            search_docs("third query")

    tracer.flush()
    spans = tracer.query("SELECT * FROM spans WHERE name = 'tool: search_docs'")
    assert len(spans) == 3
    # Last span should be marked as ERROR
    assert spans[-1]["status"] == "ERROR"
