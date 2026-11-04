"""Context propagation for NanoTrace across threads, asyncio tasks, and sub-agents.

Uses Python contextvars to maintain trace context and parent-child span hierarchies
with zero global lock contention.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional

from nanotrace.core.span import Span

_CURRENT_SPAN: ContextVar[Optional[Span]] = ContextVar("nanotrace_current_span", default=None)
_CURRENT_TRACE_ID: ContextVar[Optional[str]] = ContextVar("nanotrace_current_trace_id", default=None)
_CURRENT_CONVERSATION_ID: ContextVar[Optional[str]] = ContextVar("nanotrace_current_conv_id", default=None)


def get_current_span() -> Optional[Span]:
    """Get the currently active span in this context (async task or thread)."""
    return _CURRENT_SPAN.get()


def get_current_trace_id() -> Optional[str]:
    """Get the currently active trace ID."""
    span = get_current_span()
    if span:
        return span.trace_id
    return _CURRENT_TRACE_ID.get()


def get_current_conversation_id() -> Optional[str]:
    """Get the currently active conversation/session ID."""
    return _CURRENT_CONVERSATION_ID.get()


def set_current_span(span: Optional[Span]) -> Token:
    """Set the active span and return the context token."""
    return _CURRENT_SPAN.set(span)


def reset_current_span(token: Token) -> None:
    """Reset the active span back to the previous context state."""
    _CURRENT_SPAN.reset(token)


def set_conversation_id(conversation_id: str) -> Token:
    """Set the active conversation ID across sub-agents."""
    return _CURRENT_CONVERSATION_ID.set(conversation_id)
