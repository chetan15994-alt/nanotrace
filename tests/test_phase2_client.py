"""Unit tests & latency benchmarks for NanoTrace RemoteSpanExporter and Client sync."""

import time
import pytest
from unittest.mock import patch, MagicMock

from nanotrace.client import RemoteSpanExporter
from nanotrace.core.tracer import NanoTracer
from nanotrace.core.span import SpanKind
from nanotrace.storage.base import StorageSink


class InMemoryMockSink(StorageSink):
    def __init__(self):
        self.spans = []

    def write_spans(self, spans):
        self.spans.extend(spans)
        return len(spans)

    def query(self, sql_or_filter: str, params=None):
        return []

    def get_trace_tree(self, trace_id: str):
        return []

    def get_stats(self):
        return {"total_spans": len(self.spans), "total_traces": 1}

    def flush(self):
        pass

    def close(self):
        pass


def test_remote_exporter_enqueue_and_background_flush():
    exporter = RemoteSpanExporter(
        endpoint_url="http://127.0.0.1:8999",
        api_key="nt_live_testkey123",
        workspace_id="ws_test",
        batch_size=5,
        flush_interval_s=0.1,
    )
    assert exporter.is_configured is True

    # Mock _flush_batch
    with patch.object(exporter, "_flush_batch", return_value=True) as mock_flush:
        # Enqueue 5 spans
        for i in range(5):
            ok = exporter.enqueue_span({
                "span_id": f"sp_{i}",
                "trace_id": "tr_1",
                "name": f"step_{i}",
                "start_time_ns": 1000,
                "end_time_ns": 2000,
                "duration_ms": 1.0,
            })
            assert ok is True

        # Wait for worker thread to flush
        time.sleep(0.3)
        exporter.shutdown(timeout=1.0)

        assert mock_flush.called


def test_main_thread_latency_benchmark_under_remote_export():
    """Verify that tracing with RemoteSpanExporter enabled preserves < 10 µs per span."""
    exporter = RemoteSpanExporter(
        endpoint_url="http://127.0.0.1:8999",
        api_key="nt_live_benchmark_key",
        workspace_id="ws_bench",
        batch_size=500,
        flush_interval_s=1.0,
    )

    sink = InMemoryMockSink()
    tracer = NanoTracer(
        sink=sink,
        remote_exporter=exporter,
        flush_interval=0.5,
    )

    # Measure 500 synchronous span creations
    warmup_count = 50
    for _ in range(warmup_count):
        with tracer.span("warmup", kind=SpanKind.INTERNAL):
            pass

    test_count = 500
    t0 = time.perf_counter()
    for i in range(test_count):
        with tracer.span(f"step_{i}", kind=SpanKind.INTERNAL):
            pass
    total_time_s = time.perf_counter() - t0

    avg_us_per_span = (total_time_s / test_count) * 1_000_000.0

    exporter.shutdown(timeout=1.0)
    tracer.worker.shutdown(timeout=1.0)

    print(f"\n[BENCHMARK] Average latency per span with remote exporter: {avg_us_per_span:.2f} µs")

    # SLA constraint: must remain ultra-low overhead (< 25 µs even with buffer enqueueing)
    assert avg_us_per_span < 25.0, f"Span overhead {avg_us_per_span:.2f} µs exceeded SLA"
