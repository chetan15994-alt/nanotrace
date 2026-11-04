"""NanoTrace: Ultra-low latency, zero-infra OpenTelemetry tracing & evaluation engine for AI agents and LLMs.

The DuckDB of AI Observability.
"""

from __future__ import annotations

from typing import Optional, Dict, Any, Callable
from contextlib import contextmanager

from nanotrace._version import __version__
from nanotrace.schema.otel import (
    GenAIAttributes,
    GenAIOperation,
    SpanKind,
    StatusCode,
)
from nanotrace.core.span import Span, SpanEvent
from nanotrace.core.tracer import NanoTracer
from nanotrace.eval.bridge import load_traces, TraceDataset
from nanotrace.patchers import autoinstrument

_DEFAULT_TRACER: Optional[NanoTracer] = None


def init(
    storage_path: str = "./.traces/nanotrace.duckdb",
    buffer_capacity: int = 50_000,
    flush_interval: float = 0.25,
    auto_patch: bool = False,
) -> NanoTracer:
    """Initialize the global NanoTrace engine.

    Args:
        storage_path: Path to the local DuckDB database file (e.g. "./.traces/nanotrace.duckdb" or ":memory:")
        buffer_capacity: Max in-memory queue capacity before dropping spans
        flush_interval: Background worker flush interval in seconds
        auto_patch: If True, automatically instruments OpenAI and Anthropic SDKs if installed
    """
    global _DEFAULT_TRACER
    if _DEFAULT_TRACER is not None:
        _DEFAULT_TRACER.shutdown()

    _DEFAULT_TRACER = NanoTracer(
        db_path=storage_path,
        buffer_capacity=buffer_capacity,
        flush_interval=flush_interval,
    )

    if auto_patch:
        autoinstrument(_DEFAULT_TRACER)

    return _DEFAULT_TRACER


def get_tracer() -> NanoTracer:
    """Get the active global NanoTracer instance (initializes default if not yet initialized)."""
    global _DEFAULT_TRACER
    if _DEFAULT_TRACER is None:
        _DEFAULT_TRACER = init()
    return _DEFAULT_TRACER


@contextmanager
def span(
    name: str,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    parent_span_id: Optional[str] = None,
):
    """Context manager to trace a block of code within the active trace tree."""
    tracer = get_tracer()
    with tracer.span(
        name=name,
        kind=kind,
        attributes=attributes,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
    ) as sp:
        yield sp


def trace_agent(name: Optional[str] = None, agent_type: Optional[str] = None) -> Callable:
    """Decorator to trace an agent function or method (sync or async)."""
    return get_tracer().trace_agent(name=name, agent_type=agent_type)


def trace_tool(name: Optional[str] = None) -> Callable:
    """Decorator to trace tool execution (sync or async)."""
    return get_tracer().trace_tool(name=name)


def flush() -> int:
    """Force flush all buffered spans to storage."""
    if _DEFAULT_TRACER is not None:
        return _DEFAULT_TRACER.flush()
    return 0


def shutdown() -> None:
    """Shutdown the tracer worker and cleanly close the database connection."""
    global _DEFAULT_TRACER
    if _DEFAULT_TRACER is not None:
        _DEFAULT_TRACER.shutdown()
        _DEFAULT_TRACER = None


__all__ = [
    "__version__",
    "init",
    "get_tracer",
    "span",
    "trace_agent",
    "trace_tool",
    "flush",
    "shutdown",
    "load_traces",
    "TraceDataset",
    "autoinstrument",
    "GenAIAttributes",
    "GenAIOperation",
    "SpanKind",
    "StatusCode",
    "Span",
    "SpanEvent",
]
