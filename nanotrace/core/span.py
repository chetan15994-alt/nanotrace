"""Core Span representation adhering to CNCF OpenTelemetry standards.

Supports W3C TraceContext (traceparent) generation & parsing, nanosecond timing,
and seamless JSON / dict serialization for DuckDB and Parquet sinks.
"""

from __future__ import annotations

import os
import time
import json
import uuid
import traceback
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from nanotrace.schema.otel import SpanKind, StatusCode, GenAIAttributes


def generate_trace_id() -> str:
    """Generate a standard 32-character hexadecimal OpenTelemetry TraceID (128-bit)."""
    return uuid.uuid4().hex


def generate_span_id() -> str:
    """Generate a standard 16-character hexadecimal OpenTelemetry SpanID (64-bit)."""
    return os.urandom(8).hex()


@dataclass
class SpanEvent:
    """An in-span event (e.g. streaming token chunk, tool checkpoint)."""
    name: str
    timestamp_ns: int = field(default_factory=time.time_ns)
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "timestamp_ns": self.timestamp_ns,
            "attributes": self.attributes,
        }


@dataclass
class Span:
    """A single OpenTelemetry-compliant unit of execution (Agent step, Tool call, LLM prompt)."""

    name: str
    trace_id: str = field(default_factory=generate_trace_id)
    span_id: str = field(default_factory=generate_span_id)
    parent_span_id: Optional[str] = None
    kind: SpanKind = SpanKind.INTERNAL
    start_time_ns: int = field(default_factory=time.time_ns)
    end_time_ns: Optional[int] = None
    status: StatusCode = StatusCode.UNSET
    status_message: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[SpanEvent] = field(default_factory=list)

    @property
    def duration_ns(self) -> int:
        """Duration in nanoseconds."""
        if self.end_time_ns is None:
            return max(0, time.time_ns() - self.start_time_ns)
        return max(0, self.end_time_ns - self.start_time_ns)

    @property
    def duration_ms(self) -> float:
        """Duration in milliseconds."""
        return self.duration_ns / 1_000_000.0

    @property
    def is_finished(self) -> bool:
        """Returns True if the span has been ended."""
        return self.end_time_ns is not None

    @property
    def w3c_traceparent(self) -> str:
        """Returns standard W3C TraceContext header: 00-{trace_id}-{span_id}-01."""
        return f"00-{self.trace_id}-{self.span_id}-01"

    @classmethod
    def parse_traceparent(cls, header: str) -> tuple[Optional[str], Optional[str]]:
        """Parse W3C traceparent header into (trace_id, parent_span_id)."""
        if not header:
            return None, None
        parts = header.strip().split("-")
        if len(parts) >= 4 and len(parts[1]) == 32 and len(parts[2]) == 16:
            return parts[1], parts[2]
        return None, None

    def set_attribute(self, key: str, value: Any) -> "Span":
        """Set a single attribute."""
        if value is not None:
            self.attributes[key] = value
        return self

    def set_attributes(self, attrs: Dict[str, Any]) -> "Span":
        """Set multiple attributes at once."""
        for k, v in attrs.items():
            if v is not None:
                self.attributes[k] = v
        return self

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> "Span":
        """Record an in-span event with nanosecond timestamp."""
        self.events.append(SpanEvent(name=name, attributes=attributes or {}))
        return self

    def set_status(self, status: StatusCode, message: Optional[str] = None) -> "Span":
        """Set span status code and optional message."""
        self.status = status
        if message:
            self.status_message = message
        return self

    def record_exception(self, exc: BaseException, escaped: bool = True) -> "Span":
        """Record an exception into the span adhering to OpenTelemetry standards."""
        self.set_status(StatusCode.ERROR, str(exc))
        self.set_attribute(GenAIAttributes.ERROR_TYPE, type(exc).__name__)
        self.set_attribute(GenAIAttributes.ERROR_MESSAGE, str(exc))
        self.set_attribute(GenAIAttributes.ERROR_STACKTRACE, traceback.format_exc())
        self.add_event(
            "exception",
            {
                "exception.type": type(exc).__name__,
                "exception.message": str(exc),
                "exception.escaped": escaped,
            },
        )
        return self

    def end(self, end_time_ns: Optional[int] = None) -> "Span":
        """Mark span as finished."""
        if self.end_time_ns is None:
            self.end_time_ns = end_time_ns or time.time_ns()
            if self.status == StatusCode.UNSET:
                self.status = StatusCode.OK
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert span to a dictionary representation suitable for DuckDB / Parquet."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "kind": self.kind.value if isinstance(self.kind, SpanKind) else str(self.kind),
            "start_time_ns": self.start_time_ns,
            "end_time_ns": self.end_time_ns or self.start_time_ns,
            "duration_ms": self.duration_ms,
            "status": self.status.value if isinstance(self.status, StatusCode) else str(self.status),
            "status_message": self.status_message,
            "attributes": self.attributes,
            "events": [e.to_dict() for e in self.events],
        }

    def to_flat_dict(self) -> Dict[str, Any]:
        """Flatten key GenAI attributes for high-performance columnar DuckDB indexing."""
        attrs = self.attributes
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id or "",
            "name": self.name,
            "kind": self.kind.value if isinstance(self.kind, SpanKind) else str(self.kind),
            "start_time_ns": self.start_time_ns,
            "end_time_ns": self.end_time_ns or self.start_time_ns,
            "duration_ms": round(self.duration_ms, 3),
            "status": self.status.value if isinstance(self.status, StatusCode) else str(self.status),
            "status_message": self.status_message or "",
            
            # Key GenAI attributes extracted as first-class columns
            "gen_ai_system": str(attrs.get(GenAIAttributes.SYSTEM) or attrs.get(GenAIAttributes.PROVIDER_NAME) or ""),
            "gen_ai_operation": str(attrs.get(GenAIAttributes.OPERATION_NAME) or ""),
            "gen_ai_request_model": str(attrs.get(GenAIAttributes.REQUEST_MODEL) or ""),
            "gen_ai_response_model": str(attrs.get(GenAIAttributes.RESPONSE_MODEL) or ""),
            "gen_ai_agent_name": str(attrs.get(GenAIAttributes.AGENT_NAME) or ""),
            "gen_ai_tool_name": str(attrs.get(GenAIAttributes.TOOL_NAME) or ""),
            "gen_ai_input_tokens": int(attrs.get(GenAIAttributes.USAGE_INPUT_TOKENS) or 0),
            "gen_ai_output_tokens": int(attrs.get(GenAIAttributes.USAGE_OUTPUT_TOKENS) or 0),
            "gen_ai_total_tokens": int(attrs.get(GenAIAttributes.USAGE_TOTAL_TOKENS) or 0),
            "gen_ai_cost_usd": float(attrs.get(GenAIAttributes.USAGE_COST_USD) or 0.0),
            
            # JSON payloads for nested inspection
            "prompt_payload": json.dumps(attrs.get(GenAIAttributes.PROMPT) or attrs.get(GenAIAttributes.MESSAGES) or ""),
            "completion_payload": json.dumps(attrs.get(GenAIAttributes.COMPLETION) or ""),
            "attributes_json": json.dumps(attrs),
            "events_json": json.dumps([e.to_dict() for e in self.events]),
        }
