import time
import pytest
from nanotrace.core.span import Span, SpanEvent, generate_trace_id, generate_span_id
from nanotrace.schema.otel import SpanKind, StatusCode, GenAIAttributes


def test_span_id_and_trace_id_generation():
    tid = generate_trace_id()
    sid = generate_span_id()
    assert len(tid) == 32
    assert len(sid) == 16


def test_span_lifecycle_and_timing():
    span = Span(name="test_span", kind=SpanKind.INTERNAL)
    assert not span.is_finished
    assert span.start_time_ns > 0
    time.sleep(0.005)  # 5ms
    span.end()
    assert span.is_finished
    assert span.duration_ms >= 4.0
    assert span.status == StatusCode.OK


def test_w3c_traceparent():
    span = Span(name="parent_span")
    tp = span.w3c_traceparent
    assert tp.startswith("00-")
    assert f"-{span.trace_id}-{span.span_id}-01" in tp

    parsed_tid, parsed_sid = Span.parse_traceparent(tp)
    assert parsed_tid == span.trace_id
    assert parsed_sid == span.span_id


def test_exception_recording():
    span = Span(name="error_step")
    try:
        raise ValueError("Simulated agent failure")
    except ValueError as e:
        span.record_exception(e)
    span.end()

    assert span.status == StatusCode.ERROR
    assert span.status_message == "Simulated agent failure"
    assert span.attributes[GenAIAttributes.ERROR_TYPE] == "ValueError"
    assert "Simulated agent failure" in span.attributes[GenAIAttributes.ERROR_MESSAGE]
    assert len(span.events) == 1
    assert span.events[0].name == "exception"


def test_flattening_for_duckdb():
    span = Span(
        name="chat_step",
        attributes={
            GenAIAttributes.SYSTEM: "openai",
            GenAIAttributes.OPERATION_NAME: "chat",
            GenAIAttributes.REQUEST_MODEL: "gpt-4o",
            GenAIAttributes.USAGE_INPUT_TOKENS: 150,
            GenAIAttributes.USAGE_OUTPUT_TOKENS: 45,
            GenAIAttributes.USAGE_TOTAL_TOKENS: 195,
            GenAIAttributes.USAGE_COST_USD: 0.0012,
        }
    )
    span.end()
    flat = span.to_flat_dict()

    assert flat["name"] == "chat_step"
    assert flat["gen_ai_system"] == "openai"
    assert flat["gen_ai_operation"] == "chat"
    assert flat["gen_ai_request_model"] == "gpt-4o"
    assert flat["gen_ai_input_tokens"] == 150
    assert flat["gen_ai_output_tokens"] == 45
    assert flat["gen_ai_total_tokens"] == 195
    assert flat["gen_ai_cost_usd"] == 0.0012
