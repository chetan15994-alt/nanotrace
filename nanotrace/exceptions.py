"""Custom exceptions for NanoTrace and NanoShield runtime guardrails."""

from __future__ import annotations

from typing import Any, Dict, Optional


class NanoTraceError(Exception):
    """Base exception for all NanoTrace errors."""
    pass


class CircuitBreakerTrip(NanoTraceError):
    """Raised when an in-process NanoShield circuit breaker trips to prevent runaway loops or spend."""

    def __init__(
        self,
        breaker_name: str,
        reason: str,
        metric_value: Any = None,
        threshold: Any = None,
        span_name: str = "",
        trace_id: str = "",
        details: Optional[Dict[str, Any]] = None,
    ):
        self.breaker_name = breaker_name
        self.reason = reason
        self.metric_value = metric_value
        self.threshold = threshold
        self.span_name = span_name
        self.trace_id = trace_id
        self.details = details or {}

        msg = (
            f"🛡️ [NanoShield Alert] Circuit breaker '{breaker_name}' TRIPPED: {reason} "
            f"(value: {metric_value}, threshold: {threshold})"
        )
        super().__init__(msg)


class ReplayError(NanoTraceError):
    """Raised when time-travel replay or span forking encounters an error."""
    pass


class PromptError(NanoTraceError):
    """Raised when prompt compilation, registration, or version retrieval fails."""
    pass


class FeedbackError(NanoTraceError):
    """Raised when recording or retrieving trace feedback fails."""
    pass
