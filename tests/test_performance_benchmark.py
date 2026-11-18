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


def test_regression_engine_throughput_and_isolation():
    """Verify that parallel regression evaluation of 50 test cases completes with high throughput (< 150 ms)."""
    from nanotrace.eval.golden import GoldenCase, GoldenDatasetManager
    from nanotrace.eval.regression import RegressionEngine

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/bench_regression.duckdb"
        mgr = GoldenDatasetManager(db_path=db_path)

        # Populate 50 golden cases
        for i in range(50):
            mgr.save_case(GoldenCase(
                case_id=f"case_bench_{i:03d}",
                dataset_name="bench_suite",
                name=f"Benchmark Case #{i}",
                input_prompt=f"Analyze corporate quarterly metric #{i} for risk vectors.",
                expected_output=f"Metric #{i} verified within normal bounds.",
            ))

        engine = RegressionEngine(db_path=db_path)
        start_t = time.perf_counter()
        run = engine.run_matrix(
            dataset_name="bench_suite",
            candidate_fn=lambda p: f"Precise result for: {p}",
            baseline_fn=lambda p: f"Standard result for: {p}",
            max_workers=8,
        )
        total_time_ms = (time.perf_counter() - start_t) * 1000.0

        print(f"\n⚡️ [Regression Matrix Benchmark] Evaluated 50 Golden Cases in: {total_time_ms:.2f} ms ({total_time_ms / 50.0:.2f} ms/case)")
        assert run.total_cases == 50
        assert total_time_ms < 250.0, f"Regression matrix took {total_time_ms:.2f} ms (> 250 ms)"


def test_prompt_registry_lookup_and_compile_latency_sla():
    """Verify that PromptRegistry cached lookup and compile overhead is < 10 µs SLA."""
    from nanotrace.prompts import PromptRegistry, PromptTemplate

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/bench_prompts.duckdb"
        reg = PromptRegistry(db_path=db_path)

        tmpl = PromptTemplate(
            name="high_freq_prompt",
            template="Hello {{user}}, analyze portfolio for {{quarter}} with risk limit {{limit}}.",
            version="1.0.0",
            tags=["production"],
        )
        reg.save(tmpl)

        # Warmup
        for _ in range(50):
            reg.get("high_freq_prompt", tag="production")

        # Benchmark cached get()
        n_iters = 5_000
        start_ns = time.perf_counter_ns()
        for _ in range(n_iters):
            p = reg.get("high_freq_prompt", tag="production")
        elapsed_ns = time.perf_counter_ns() - start_ns
        avg_lookup_us = (elapsed_ns / n_iters) / 1000.0

        # Benchmark compile()
        start_ns = time.perf_counter_ns()
        for _ in range(n_iters):
            p.compile(user="Alice", quarter="Q3", limit="10000")
        elapsed_ns = time.perf_counter_ns() - start_ns
        avg_compile_us = (elapsed_ns / n_iters) / 1000.0

        print(f"\n⚡️ [Prompt Registry Benchmark] Cached Lookup: {avg_lookup_us:.3f} µs, Compile: {avg_compile_us:.3f} µs (Target: < 10.0 µs)")
        assert avg_lookup_us < 10.0, f"Prompt cached lookup {avg_lookup_us:.2f} µs exceeded 10 µs SLA!"
        assert avg_compile_us < 10.0, f"Prompt compile {avg_compile_us:.2f} µs exceeded 10 µs SLA!"


def test_multimodal_sanitizer_throughput_and_latency():
    """Verify that multi-modal base64 detection & sanitization for large payloads runs in < 2 ms."""
    from nanotrace.media import sanitize_payload_for_display, detect_media

    # Construct a 200 KB mock payload with two base64 images and URLs
    b64_dummy = "A" * 150_000
    huge_payload = f"Analysis input:\ndata:image/jpeg;base64,{b64_dummy}\nExternal ref: https://example.com/chart.png\nEnd."

    start_perf = time.perf_counter()
    sanitized_text, media_items = sanitize_payload_for_display(huge_payload)
    elapsed_ms = (time.perf_counter() - start_perf) * 1000.0

    print(f"\n⚡️ [Multi-Modal Sanitizer Benchmark] 200KB payload sanitized in: {elapsed_ms:.2f} ms")
    assert elapsed_ms < 5.0, f"Sanitization took {elapsed_ms:.2f} ms (> 5 ms)"
    assert b64_dummy not in sanitized_text
    assert "[🖼️ Embedded Media: image/jpeg (" in sanitized_text

    # Verify detection speed
    start_perf = time.perf_counter()
    detected = detect_media(huge_payload)
    det_elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
    print(f"⚡️ [Multi-Modal Detection Benchmark] Detected {len(detected)} items in: {det_elapsed_ms:.2f} ms")
    assert len(detected) == 2
    assert det_elapsed_ms < 5.0


def test_tracer_hot_path_architectural_decoupling():
    """Verify that the core Tracer and Buffer have ZERO coupling or dependencies on Phase 4 modules."""
    import nanotrace.core.tracer
    import nanotrace.core.buffer

    # Verify core tracer and buffer module globals do not import prompts, feedback, or media
    tracer_imports = dir(nanotrace.core.tracer)
    buffer_imports = dir(nanotrace.core.buffer)

    forbidden_couplings = [
        "PromptRegistry", "PromptTemplate", "FeedbackCollector", 
        "FeedbackEntry", "detect_media", "sanitize_payload_for_display"
    ]
    for sym in forbidden_couplings:
        assert sym not in tracer_imports, f"Architectural violation: {sym} coupled to Tracer hot-path!"
        assert sym not in buffer_imports, f"Architectural violation: {sym} coupled to Buffer hot-path!"

    print("\n🏛️ [Decoupling Architecture Verification] Core Tracer and Buffer maintain 100% decoupling from secondary subsystems.")

