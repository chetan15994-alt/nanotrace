"""Edge Case & Async Tests for Phase 2 NanoShield & Replay Engine."""

import os
import asyncio
import pytest

import nanotrace
from nanotrace.exceptions import CircuitBreakerTrip, ReplayError
from nanotrace.guardrails.breakers import MaxLoopBreaker, PIIRedaction, BudgetCapBreaker
from nanotrace.core.replay import ReplayEngine
from nanotrace.schema.otel import GenAIAttributes


@pytest.fixture
def edge_env(tmp_path):
    db_file = str(tmp_path / "edge_test.duckdb")
    tracer = nanotrace.init(storage_path=db_file, buffer_capacity=1000, flush_interval=0.01)
    yield tracer, db_file
    try:
        tracer.shutdown()
    except Exception:
        pass


@pytest.mark.anyio
async def test_async_trace_agent_and_tool_with_loop_breaker(edge_env):
    tracer, db_file = edge_env
    loop_breaker = MaxLoopBreaker(limit=2)

    @tracer.trace_agent(name="async_researcher")
    async def run_agent():
        @tracer.trace_tool(circuit_breakers=[loop_breaker])
        async def fetch_web(url: str):
            await asyncio.sleep(0.001)
            return f"Page content from {url}"

        # 2 calls succeed
        await fetch_web("https://docs.python.org")
        await fetch_web("https://peps.python.org")

        # 3rd call must trip
        with pytest.raises(CircuitBreakerTrip) as exc_info:
            await fetch_web("https://pypi.org")

        assert exc_info.value.breaker_name == "MaxLoopBreaker"
        assert exc_info.value.metric_value == 3

    await run_agent()

    tracer.flush()
    spans = tracer.query("SELECT * FROM spans WHERE name = 'tool: fetch_web'")
    assert len(spans) == 3
    assert spans[-1]["status"] == "ERROR"


@pytest.mark.anyio
async def test_async_trace_tool_with_pii_blocking(edge_env):
    tracer, db_file = edge_env
    blocker = PIIRedaction(action="block")

    @tracer.trace_tool(name="leak_tool", circuit_breakers=[blocker])
    async def unsafe_tool(secret: str):
        await asyncio.sleep(0.001)
        return f"Echo {secret}"

    with pytest.raises(CircuitBreakerTrip) as exc_info:
        await unsafe_tool("Sensitive token: ghp_123456789012345678901234567890")

    assert exc_info.value.breaker_name == "PIIRedaction"
    assert "Sensitive PII/Credential detected" in exc_info.value.reason


def test_replay_context_on_root_node(edge_env):
    tracer, db_file = edge_env

    with tracer.span("single_root_span") as root:
        root.prompt_payload = "Isolated task"
        root.completion_payload = "Task completed"

    tracer.flush()
    engine = ReplayEngine(db_path=db_file)
    ctx = engine.get_node_context(root.span_id)

    assert ctx["target_span"]["span_id"] == root.span_id
    # Root node has no ancestors
    assert ctx["ancestors"] == []
    assert ctx["total_trace_spans"] == 1


def test_pii_all_pattern_types(edge_env):
    tracer, db_file = edge_env
    pii = PIIRedaction(action="redact")

    test_samples = [
        ("API sk-test12345678901234567890 key", "[REDACTED]_API_KEY"),
        ("Call me at 415-555-2671 please", "[REDACTED]_PHONE"),
        ("Send bill to user.name+tag@sub.domain.co.uk", "[REDACTED]_EMAIL"),
        ("ID is 987-65-4321 for registration", "[REDACTED]_SSN"),
        ("Charge 5555 4444 3333 2222 now", "[REDACTED]_CREDIT_CARD"),
    ]

    for raw, expected_token in test_samples:
        with tracer.span("sample_span", circuit_breakers=[pii]) as sp:
            sp.prompt_payload = raw

        assert expected_token in sp.prompt_payload
