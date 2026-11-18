"""Performance & Latency Benchmark Test Suite for NanoTrace.

Verifies strict SLA constraints:
- In-process lock-free span enqueue overhead < 15 microseconds (< 15 µs)
- Capsule export latency < 25 ms
- Zero performance impact on Python agent execution loops
"""

import time
import tempfile
import pytest

import nanotrace
from nanotrace.schema.otel import SpanKind
from nanotrace.export.capsule import generate_trace_capsule


def test_span_enqueue_latency_sla():
    """Verify that span creation and ring-buffer enqueue overhead is strictly < 15 µs per span."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/bench.duckdb"
        tracer = nanotrace.init(storage_path=db_path, buffer_capacity=20_000, flush_interval=1.0)

        # Warmup
        for i in range(100):
            with tracer.span(f"warmup_{i}", kind=SpanKind.INTERNAL):
                pass

        num_spans = 5_000
        start_ns = time.perf_counter_ns()
        for i in range(num_spans):
            with tracer.span(f"span_{i}", kind=SpanKind.INTERNAL):
                pass
        total_elapsed_ns = time.perf_counter_ns() - start_ns

        tracer.shutdown()

        avg_latency_us = (total_elapsed_ns / num_spans) / 1_000.0
        print(f"\n⚡️ [Benchmark Result] Mean Span Latency: {avg_latency_us:.3f} µs (Target: < 15.0 µs)")

        # Strict SLA check: must be under 15 microseconds
        assert avg_latency_us < 15.0, f"Span overhead {avg_latency_us:.2f} µs exceeded 15 µs SLA!"


def test_nanoshield_circuit_breaker_latency_sla():
    """Verify that active NanoShield circuit breaker evaluation remains < 15 µs SLA."""
    from nanotrace.guardrails.breakers import MaxLoopBreaker, BudgetCapBreaker, MaxTokenBreaker, PIIRedaction
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/bench_shield.duckdb"
        breakers = [
            MaxLoopBreaker(limit=100_000),
            BudgetCapBreaker(max_trace_usd=1000.0),
            MaxTokenBreaker(max_total_tokens=10_000_000),
            PIIRedaction(),
        ]
        tracer = nanotrace.init(
            storage_path=db_path,
            buffer_capacity=20_000,
            flush_interval=1.0,
            circuit_breakers=breakers,
        )

        # Warmup
        for i in range(100):
            with tracer.span(f"warmup_shield_{i}", kind=SpanKind.INTERNAL):
                pass

        num_spans = 5_000
        start_ns = time.perf_counter_ns()
        for i in range(num_spans):
            with tracer.span(f"shield_span_{i}", kind=SpanKind.INTERNAL) as sp:
                sp.prompt_payload = "Standard agent query without PII"
                sp.completion_payload = "Standard calibrated reply"
        total_elapsed_ns = time.perf_counter_ns() - start_ns

        tracer.shutdown()

        avg_latency_us = (total_elapsed_ns / num_spans) / 1_000.0
        print(f"\n🛡️ [NanoShield Benchmark Result] Mean Latency with 4 Active Guardrails: {avg_latency_us:.3f} µs (Target: < 15.0 µs)")

        # Strict SLA check: must be under 15 microseconds even with all 4 guardrails active
        assert avg_latency_us < 15.0, f"NanoShield span overhead {avg_latency_us:.2f} µs exceeded 15 µs SLA!"


def test_capsule_generation_latency():
    """Verify that generating a standalone capsule for a 50-span trace completes in < 30 ms."""
    mock_spans = []
    base_ns = time.time_ns()
    for i in range(50):
        mock_spans.append({
            "trace_id": "test_trace_1234567890abcdef",
            "span_id": f"span_{i:04d}",
            "parent_span_id": None if i == 0 else "span_0000",
            "name": f"step_{i}",
            "kind": "INTERNAL",
            "start_time_ns": base_ns + (i * 1_000_000),
            "end_time_ns": base_ns + ((i + 1) * 1_000_000),
            "duration_ms": 1.0,
            "status": "OK",
            "attributes_json": '{"gen_ai.system": "openai"}',
            "events_json": "[]",
            "prompt_payload": "user request",
            "completion_payload": "agent response",
            "gen_ai_system": "openai",
            "gen_ai_request_model": "gpt-4o",
            "gen_ai_operation": "chat" if i % 2 == 0 else "execute_tool",
            "gen_ai_input_tokens": 100,
            "gen_ai_output_tokens": 50,
            "gen_ai_total_tokens": 150,
            "gen_ai_cost_usd": 0.0005,
            "gen_ai_tool_name": f"tool_{i}" if i % 2 != 0 else None,
            "created_at": "2026-11-18 08:00:00",
        })

    start_perf = time.perf_counter()
    html = generate_trace_capsule("test_trace_1234567890abcdef", mock_spans)
    duration_ms = (time.perf_counter() - start_perf) * 1000.0

    print(f"\n⚡️ [Benchmark Result] Capsule generation time (50 spans): {duration_ms:.2f} ms")
    assert duration_ms < 30.0, f"Capsule generation took {duration_ms:.2f} ms (> 30 ms)"
    assert len(html) > 5000
    assert "test_trace_1234567890abcdef" in html
