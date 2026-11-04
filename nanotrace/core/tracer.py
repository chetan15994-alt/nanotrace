"""Core NanoTracer implementation and user-facing decorators.

Provides zero-overhead tracing for sync and async agent functions, tools,
and LLM invocations with automatic parent-child relationship tracking.
"""

from __future__ import annotations

import functools
import inspect
import json
from typing import Dict, Any, Optional, Callable, Generator, AsyncGenerator
from contextlib import contextmanager

from nanotrace.core.span import Span, generate_trace_id, generate_span_id
from nanotrace.core.context import (
    get_current_span,
    set_current_span,
    reset_current_span,
    get_current_conversation_id,
)
from nanotrace.core.buffer import SpanBuffer
from nanotrace.core.worker import FlushWorker
from nanotrace.schema.otel import GenAIAttributes, GenAIOperation, SpanKind, StatusCode
from nanotrace.storage.base import StorageSink
from nanotrace.storage.duckdb_sink import DuckDBSink


class NanoTracer:
    """The central NanoTrace tracing coordinator."""

    def __init__(
        self,
        sink: Optional[StorageSink] = None,
        db_path: str = "./.traces/nanotrace.duckdb",
        buffer_capacity: int = 50_000,
        flush_interval: float = 0.25,
    ):
        self.sink = sink or DuckDBSink(db_path=db_path)
        self.buffer = SpanBuffer(max_capacity=buffer_capacity)
        self.worker = FlushWorker(
            buffer=self.buffer,
            sink=self.sink,
            flush_interval_seconds=flush_interval,
        )
        self.worker.start()

    @contextmanager
    def span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        attributes: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
    ) -> Generator[Span, None, None]:
        """Context manager to trace a synchronous block of code."""
        parent = get_current_span()

        # Determine trace_id and parent_span_id
        effective_trace_id = trace_id or (parent.trace_id if parent else generate_trace_id())
        effective_parent_id = parent_span_id or (parent.span_id if parent else None)

        span = Span(
            name=name,
            trace_id=effective_trace_id,
            parent_span_id=effective_parent_id,
            kind=kind,
            attributes=attributes or {},
        )

        # Inherit conversation context if present
        conv_id = get_current_conversation_id()
        if conv_id and GenAIAttributes.CONVERSATION_ID not in span.attributes:
            span.set_attribute(GenAIAttributes.CONVERSATION_ID, conv_id)

        token = set_current_span(span)
        try:
            yield span
        except BaseException as exc:
            span.record_exception(exc)
            raise
        finally:
            span.end()
            reset_current_span(token)
            self.buffer.push(span)

    def trace_agent(
        self,
        name: Optional[str] = None,
        agent_type: Optional[str] = None,
    ) -> Callable:
        """Decorator to trace an agent function or method (supports both sync & async)."""
        def decorator(func: Callable) -> Callable:
            span_name = name or func.__name__

            if inspect.iscoroutinefunction(func):
                @functools.wraps(func)
                async def async_wrapper(*args, **kwargs):
                    with self.span(span_name, kind=SpanKind.INTERNAL) as sp:
                        sp.set_attribute(GenAIAttributes.OPERATION_NAME, GenAIOperation.AGENT_RUN.value)
                        sp.set_attribute(GenAIAttributes.AGENT_NAME, span_name)
                        if agent_type:
                            sp.set_attribute(GenAIAttributes.AGENT_TYPE, agent_type)
                        _record_inputs(sp, args, kwargs)
                        result = await func(*args, **kwargs)
                        _record_output(sp, result)
                        return result
                return async_wrapper
            else:
                @functools.wraps(func)
                def sync_wrapper(*args, **kwargs):
                    with self.span(span_name, kind=SpanKind.INTERNAL) as sp:
                        sp.set_attribute(GenAIAttributes.OPERATION_NAME, GenAIOperation.AGENT_RUN.value)
                        sp.set_attribute(GenAIAttributes.AGENT_NAME, span_name)
                        if agent_type:
                            sp.set_attribute(GenAIAttributes.AGENT_TYPE, agent_type)
                        _record_inputs(sp, args, kwargs)
                        result = func(*args, **kwargs)
                        _record_output(sp, result)
                        return result
                return sync_wrapper

        return decorator

    def trace_tool(
        self,
        name: Optional[str] = None,
    ) -> Callable:
        """Decorator to trace tool execution (sync or async)."""
        def decorator(func: Callable) -> Callable:
            tool_name = name or func.__name__

            if inspect.iscoroutinefunction(func):
                @functools.wraps(func)
                async def async_wrapper(*args, **kwargs):
                    with self.span(f"tool: {tool_name}", kind=SpanKind.CLIENT) as sp:
                        sp.set_attribute(GenAIAttributes.OPERATION_NAME, GenAIOperation.EXECUTE_TOOL.value)
                        sp.set_attribute(GenAIAttributes.TOOL_NAME, tool_name)
                        _record_inputs(sp, args, kwargs, is_tool=True)
                        result = await func(*args, **kwargs)
                        _record_output(sp, result, is_tool=True)
                        return result
                return async_wrapper
            else:
                @functools.wraps(func)
                def sync_wrapper(*args, **kwargs):
                    with self.span(f"tool: {tool_name}", kind=SpanKind.CLIENT) as sp:
                        sp.set_attribute(GenAIAttributes.OPERATION_NAME, GenAIOperation.EXECUTE_TOOL.value)
                        sp.set_attribute(GenAIAttributes.TOOL_NAME, tool_name)
                        _record_inputs(sp, args, kwargs, is_tool=True)
                        result = func(*args, **kwargs)
                        _record_output(sp, result, is_tool=True)
                        return result
                return sync_wrapper

        return decorator

    def flush(self) -> int:
        """Force flush all buffered spans to the storage sink."""
        return self.worker.flush()

    def shutdown(self) -> None:
        """Cleanly flush remaining spans and stop background worker."""
        self.worker.shutdown()

    def query(self, sql_or_filter: str) -> list[dict[str, Any]]:
        """Query stored traces directly with SQL."""
        self.flush()
        return self.sink.query(sql_or_filter)

    def stats(self) -> dict[str, Any]:
        """Get trace execution metrics."""
        self.flush()
        return self.sink.get_stats()


def _record_inputs(span: Span, args: tuple, kwargs: dict, is_tool: bool = False) -> None:
    """Helper to safely record function arguments without crashing on non-serializable objects."""
    try:
        clean_kwargs = {k: v for k, v in kwargs.items() if not k.startswith("_")}
        payload = {"args": [str(a) for a in args], "kwargs": clean_kwargs}
        if is_tool:
            span.set_attribute(GenAIAttributes.TOOL_ARGUMENTS, payload)
        else:
            span.set_attribute(GenAIAttributes.PROMPT, payload)
    except Exception:
        pass


def _record_output(span: Span, result: Any, is_tool: bool = False) -> None:
    """Helper to safely record function output."""
    try:
        if is_tool:
            span.set_attribute(GenAIAttributes.TOOL_OUTPUT, result)
        else:
            span.set_attribute(GenAIAttributes.COMPLETION, result)
    except Exception:
        pass
