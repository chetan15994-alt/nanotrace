"""Zero-code auto-instrumentation for the official Anthropic Python SDK."""

from __future__ import annotations

import functools
import logging
from typing import Dict, Any

from nanotrace.schema.otel import GenAIAttributes, GenAIOperation, SpanKind

logger = logging.getLogger("nanotrace")

ANTHROPIC_PRICING = {
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-opus": {"input": 15.00, "output": 75.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
}


def calculate_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    for key, rates in ANTHROPIC_PRICING.items():
        if key in model.lower():
            in_c = (in_tokens / 1_000_000) * rates["input"]
            out_c = (out_tokens / 1_000_000) * rates["output"]
            return round(in_c + out_c, 6)
    return 0.0


def patch_anthropic(tracer) -> bool:
    """Monkey-patch Anthropic messages.create."""
    try:
        import anthropic
        from anthropic.resources.messages import Messages
    except ImportError:
        logger.debug("[NanoTrace] Anthropic SDK not installed. Skipping patch.")
        return False

    if getattr(Messages, "_nanotrace_patched", False):
        return True

    original_create = Messages.create

    @functools.wraps(original_create)
    def patched_create(self, *args, **kwargs):
        model = kwargs.get("model", "claude-model")
        messages = kwargs.get("messages", [])
        span_name = f"chat {model}"

        with tracer.span(span_name, kind=SpanKind.CLIENT) as span:
            span.set_attribute(GenAIAttributes.SYSTEM, "anthropic")
            span.set_attribute(GenAIAttributes.OPERATION_NAME, GenAIOperation.CHAT.value)
            span.set_attribute(GenAIAttributes.REQUEST_MODEL, model)
            span.set_attribute(GenAIAttributes.MESSAGES, messages)

            try:
                response = original_create(self, *args, **kwargs)
                if hasattr(response, "model"):
                    span.set_attribute(GenAIAttributes.RESPONSE_MODEL, response.model)
                if hasattr(response, "content") and response.content:
                    text_parts = [b.text for b in response.content if hasattr(b, "text")]
                    span.set_attribute(GenAIAttributes.COMPLETION, "".join(text_parts))
                if hasattr(response, "usage") and response.usage:
                    u = response.usage
                    in_t = getattr(u, "input_tokens", 0)
                    out_t = getattr(u, "output_tokens", 0)
                    span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, in_t)
                    span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, out_t)
                    span.set_attribute(GenAIAttributes.USAGE_TOTAL_TOKENS, in_t + out_t)
                    span.set_attribute(GenAIAttributes.USAGE_COST_USD, calculate_cost(model, in_t, out_t))
                return response
            except Exception as e:
                span.record_exception(e)
                raise

    Messages.create = patched_create
    Messages._nanotrace_patched = True
    return True
