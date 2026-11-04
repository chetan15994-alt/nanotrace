import pytest
import nanotrace
from nanotrace.core.context import get_current_span
from nanotrace.schema.otel import SpanKind


def test_span_context_nesting():
    tracer = nanotrace.init(storage_path=":memory:")

    with tracer.span("outer_agent", kind=SpanKind.INTERNAL) as outer:
        assert get_current_span() is outer
        assert outer.parent_span_id is None

        with tracer.span("inner_tool", kind=SpanKind.CLIENT) as inner:
            assert get_current_span() is inner
            assert inner.trace_id == outer.trace_id
            assert inner.parent_span_id == outer.span_id

        # Context restored
        assert get_current_span() is outer

    assert get_current_span() is None
    tracer.shutdown()
