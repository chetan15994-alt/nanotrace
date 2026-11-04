import time
import pytest
from nanotrace.core.span import Span
from nanotrace.core.buffer import SpanBuffer
from nanotrace.core.worker import FlushWorker
from nanotrace.storage.memory_sink import MemorySink


def test_span_buffer_push_and_drain():
    buf = SpanBuffer(max_capacity=10)
    for i in range(5):
        s = Span(name=f"span_{i}")
        s.end()
        buf.push(s)

    assert len(buf) == 5
    drained = buf.drain()
    assert len(drained) == 5
    assert len(buf) == 0


def test_span_buffer_capacity_overflow():
    buf = SpanBuffer(max_capacity=3)
    for i in range(5):
        s = Span(name=f"span_{i}")
        s.end()
        buf.push(s)

    assert len(buf) == 3
    assert buf.dropped_spans == 2
    assert buf.total_enqueued == 5


def test_flush_worker_background_execution():
    buf = SpanBuffer(max_capacity=100)
    sink = MemorySink()
    worker = FlushWorker(buffer=buf, sink=sink, flush_interval_seconds=0.05)
    worker.start()

    for i in range(10):
        s = Span(name=f"worker_span_{i}")
        s.end()
        buf.push(s)

    # Wait briefly for background daemon to flush
    time.sleep(0.15)
    worker.shutdown()

    assert len(sink._spans) == 10
