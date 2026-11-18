"""NanoShield: In-process active safety circuit breakers and runtime guardrails.

Evaluates safety policies in-memory with sub-microsecond latency (< 1 µs)
before and after agent/tool execution to prevent infinite recursion, runaway cloud spend,
and sensitive data leakage.
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from collections import defaultdict

from nanotrace.core.span import Span
from nanotrace.schema.otel import StatusCode, GenAIAttributes
from nanotrace.exceptions import CircuitBreakerTrip


class TraceContextState:
    """In-memory active execution state tracker for a single trace."""

    def __init__(self, trace_id: str):
        self.trace_id = trace_id
        self.start_time_ns = time.time_ns()
        self.span_counts: Dict[str, int] = defaultdict(int)
        self.total_cost_usd: float = 0.0
        self.total_tokens: int = 0
        self.tripped_breakers: List[Dict[str, Any]] = []

    def record_span_start(self, span_name: str) -> int:
        self.span_counts[span_name] += 1
        return self.span_counts[span_name]

    def record_cost_and_tokens(self, cost_usd: float, tokens: int) -> None:
        self.total_cost_usd += float(cost_usd or 0.0)
        self.total_tokens += int(tokens or 0)


# Global in-memory trace state registry
_ACTIVE_STATES: Dict[str, TraceContextState] = {}


def get_trace_state(trace_id: str, start_time_ns: Optional[int] = None) -> TraceContextState:
    """Retrieve or create in-memory state tracker for a trace."""
    if trace_id not in _ACTIVE_STATES:
        state = TraceContextState(trace_id)
        if start_time_ns is not None:
            state.start_time_ns = start_time_ns
        _ACTIVE_STATES[trace_id] = state
    return _ACTIVE_STATES[trace_id]


def clear_trace_state(trace_id: str) -> None:
    """Clean up memory when a trace finishes."""
    _ACTIVE_STATES.pop(trace_id, None)


class CircuitBreaker(ABC):
    """Abstract base class for all NanoShield runtime circuit breakers."""

    name: str = "CircuitBreaker"

    def check_before(self, span: Span, state: TraceContextState) -> None:
        """Executed immediately before the decorated function or span block runs."""
        pass

    def check_after(self, span: Span, result: Any, state: TraceContextState) -> Any:
        """Executed immediately after the decorated function or span block completes."""
        return result

    def trip(
        self,
        span: Span,
        state: TraceContextState,
        reason: str,
        metric_value: Any = None,
        threshold: Any = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Mark span as tripped, record telemetry attributes, and raise CircuitBreakerTrip."""
        trip_info = {
            "breaker": self.name,
            "reason": reason,
            "metric_value": metric_value,
            "threshold": threshold,
            "timestamp_ns": time.time_ns(),
            "details": details or {},
        }
        state.tripped_breakers.append(trip_info)

        span.set_attribute("nanotrace.shield.tripped", True)
        span.set_attribute("nanotrace.shield.breaker", self.name)
        span.set_attribute("nanotrace.shield.reason", reason)
        if metric_value is not None:
            span.set_attribute("nanotrace.shield.metric_value", str(metric_value))
        if threshold is not None:
            span.set_attribute("nanotrace.shield.threshold", str(threshold))

        span.set_status(
            StatusCode.ERROR,
            f"🛡️ NanoShield Tripped: [{self.name}] {reason}",
        )

        raise CircuitBreakerTrip(
            breaker_name=self.name,
            reason=reason,
            metric_value=metric_value,
            threshold=threshold,
            span_name=span.name,
            trace_id=span.trace_id,
            details=details,
        )


class MaxLoopBreaker(CircuitBreaker):
    """Trips when the same tool or operation repeats excessively in a single trace."""

    name = "MaxLoopBreaker"

    def __init__(self, limit: int = 5, match_tool_name: bool = True, scope: str = "trace"):
        self.limit = limit
        self.match_tool_name = match_tool_name
        self.scope = scope
        self._global_counts: Dict[str, int] = defaultdict(int)

    def check_before(self, span: Span, state: TraceContextState) -> None:
        key = span.name
        if self.match_tool_name:
            tool_name = span.attributes.get(GenAIAttributes.TOOL_NAME)
            if tool_name:
                key = f"tool:{tool_name}"

        if self.scope == "global":
            self._global_counts[key] += 1
            count = self._global_counts[key]
        else:
            count = state.record_span_start(key)

        if count > self.limit:
            self.trip(
                span=span,
                state=state,
                reason=f"Runaway recursive loop detected: '{key}' called {count} times (limit is {self.limit}).",
                metric_value=count,
                threshold=self.limit,
                details={"target_operation": key, "execution_count": count},
            )


class BudgetCapBreaker(CircuitBreaker):
    """Trips if cumulative spend or single-step cost exceeds threshold."""

    name = "BudgetCapBreaker"

    def __init__(self, max_trace_usd: Optional[float] = None, max_turn_usd: Optional[float] = None, scope: str = "trace"):
        self.max_trace_usd = max_trace_usd
        self.max_turn_usd = max_turn_usd
        self.scope = scope
        self._global_total_cost_usd: float = 0.0

    def check_before(self, span: Span, state: TraceContextState) -> None:
        cost = self._global_total_cost_usd if self.scope == "global" else state.total_cost_usd
        if self.max_trace_usd is not None and cost >= self.max_trace_usd:
            self.trip(
                span=span,
                state=state,
                reason=f"Cumulative budget exceeded: spend of ${cost:.5f} reached budget cap of ${self.max_trace_usd:.5f}.",
                metric_value=cost,
                threshold=self.max_trace_usd,
            )

    def check_after(self, span: Span, result: Any, state: TraceContextState) -> Any:
        cost = float(span.attributes.get(GenAIAttributes.USAGE_COST_USD) or 0.0)
        tokens = int(span.attributes.get(GenAIAttributes.USAGE_TOTAL_TOKENS) or 0)
        state.record_cost_and_tokens(cost, tokens)
        if self.scope == "global":
            self._global_total_cost_usd += cost

        if self.max_turn_usd is not None and cost > self.max_turn_usd:
            self.trip(
                span=span,
                state=state,
                reason=f"Single turn spend ${cost:.5f} exceeded max turn limit of ${self.max_turn_usd:.5f}.",
                metric_value=cost,
                threshold=self.max_turn_usd,
            )
        return result


class MaxTokenBreaker(CircuitBreaker):
    """Trips if token consumption exceeds limits."""

    name = "MaxTokenBreaker"

    def __init__(self, max_total_tokens: Optional[int] = None, max_turn_tokens: Optional[int] = None, scope: str = "trace"):
        self.max_total_tokens = max_total_tokens
        self.max_turn_tokens = max_turn_tokens
        self.scope = scope
        self._global_total_tokens: int = 0

    def check_before(self, span: Span, state: TraceContextState) -> None:
        total = self._global_total_tokens if self.scope == "global" else state.total_tokens
        if self.max_total_tokens is not None and total >= self.max_total_tokens:
            self.trip(
                span=span,
                state=state,
                reason=f"Cumulative token cap reached: consumed {total:,} tokens (limit: {self.max_total_tokens:,}).",
                metric_value=total,
                threshold=self.max_total_tokens,
            )

    def check_after(self, span: Span, result: Any, state: TraceContextState) -> Any:
        tokens = int(span.attributes.get(GenAIAttributes.USAGE_TOTAL_TOKENS) or 0)
        if self.scope == "global":
            self._global_total_tokens += tokens
        if self.max_turn_tokens is not None and tokens > self.max_turn_tokens:
            self.trip(
                span=span,
                state=state,
                reason=f"Single turn tokens {tokens:,} exceeded turn limit of {self.max_turn_tokens:,}.",
                metric_value=tokens,
                threshold=self.max_turn_tokens,
            )
        return result


class PIIRedaction(CircuitBreaker):
    """Ultra-fast regex sanitizer that redacts sensitive PII before persistence.

    Supports API keys, Social Security Numbers, Credit Cards, Emails, and Phone Numbers.
    """

    name = "PIIRedaction"

    # Pre-compiled high-performance regex patterns
    PATTERNS = {
        "API_KEY": re.compile(r"(sk-[a-zA-Z0-9-_]{20,}|ghp_[a-zA-Z0-9]{30,}|xoxb-[a-zA-Z0-9-]+|AIza[0-9A-Za-z-_]{35})"),
        "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"),
        "CREDIT_CARD": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
        "PHONE": re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    }

    def __init__(
        self,
        mask: Optional[List[str]] = None,
        replacement: str = "[REDACTED]",
        action: str = "redact",  # "redact" or "block"
    ):
        self.mask_types = mask or ["API_KEY", "SSN", "EMAIL", "CREDIT_CARD", "PHONE"]
        self.replacement = replacement
        self.action = action.lower()

    def _sanitize_text(self, text: str) -> tuple[str, bool]:
        """Sanitize text and return (sanitized_string, was_modified)."""
        if not isinstance(text, str) or not text:
            return text, False

        modified = False
        res = text
        for m_type in self.mask_types:
            pattern = self.PATTERNS.get(m_type)
            if pattern and pattern.search(res):
                modified = True
                res = pattern.sub(f"{self.replacement}_{m_type}", res)
        return res, modified

    def check_before(self, span: Span, state: TraceContextState) -> None:
        if span.prompt_payload:
            clean_text, found = self._sanitize_text(span.prompt_payload)
            if found:
                if self.action == "block":
                    self.trip(
                        span=span,
                        state=state,
                        reason="Sensitive PII/Credential detected in input payload under strict blocking policy.",
                    )
                span.prompt_payload = clean_text
                span.set_attribute("nanotrace.shield.pii_redacted", True)

    def check_after(self, span: Span, result: Any, state: TraceContextState) -> Any:
        if span.prompt_payload:
            clean_prompt, p_found = self._sanitize_text(span.prompt_payload)
            if p_found:
                if self.action == "block":
                    self.trip(
                        span=span,
                        state=state,
                        reason="Sensitive PII/Credential detected in input payload under strict blocking policy.",
                    )
                span.prompt_payload = clean_prompt
                span.set_attribute("nanotrace.shield.pii_redacted", True)

        if span.completion_payload:
            clean_text, found = self._sanitize_text(span.completion_payload)
            if found:
                if self.action == "block":
                    self.trip(
                        span=span,
                        state=state,
                        reason="Sensitive PII/Credential generated in completion payload under strict blocking policy.",
                    )
                span.completion_payload = clean_text
                span.set_attribute("nanotrace.shield.pii_redacted", True)
        return result


class TimeoutBreaker(CircuitBreaker):
    """Enforces maximum overall execution duration for an agent trace."""

    name = "TimeoutBreaker"

    def __init__(self, timeout_seconds: float = 30.0):
        self.timeout_seconds = timeout_seconds

    def check_before(self, span: Span, state: TraceContextState) -> None:
        elapsed_sec = (time.time_ns() - state.start_time_ns) / 1_000_000_000.0
        if elapsed_sec > self.timeout_seconds:
            self.trip(
                span=span,
                state=state,
                reason=f"Execution timeout: elapsed {elapsed_sec:.2f}s exceeded limit of {self.timeout_seconds:.2f}s.",
                metric_value=f"{elapsed_sec:.2f}s",
                threshold=f"{self.timeout_seconds:.2f}s",
            )

    def check_after(self, span: Span, result: Any, state: TraceContextState) -> Any:
        elapsed_sec = (time.time_ns() - state.start_time_ns) / 1_000_000_000.0
        span_dur_sec = span.duration_ms / 1000.0
        if elapsed_sec > self.timeout_seconds or span_dur_sec > self.timeout_seconds:
            dur = max(elapsed_sec, span_dur_sec)
            self.trip(
                span=span,
                state=state,
                reason=f"Execution timeout: duration {dur:.2f}s exceeded limit of {self.timeout_seconds:.2f}s.",
                metric_value=f"{dur:.2f}s",
                threshold=f"{self.timeout_seconds:.2f}s",
            )
        return result
