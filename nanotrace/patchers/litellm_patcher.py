"""Zero-code auto-instrumentation for LiteLLM.

Automatically captures provider, model, prompt messages, token counts,
model latency, and approximate cost for LiteLLM completion calls.
"""

from __future__ import annotations

import functools
import logging
from typing import Dict, Any

from nanotrace.schema.otel import GenAIAttributes, GenAIOperation, SpanKind

logger = logging.getLogger("nanotrace")


def patch_litellm(tracer) -> bool:
    """Monkey-patch LiteLLM completions to record OpenTelemetry spans."""
    try:
        import litellm
    except ImportError:
        logger.debug("[NanoTrace] LiteLLM not installed. Skipping patch.")
        return False

    if getattr(litellm, "_nanotrace_patched", False):
        return True

    original_completion = litellm.completion

    @functools.wraps(original_completion)
    def patched_completion(*args, **kwargs):
        model = kwargs.get("model", "unknown-model")
        messages = kwargs.get("messages", [])
        span_name = f"chat {model}"

        with tracer.span(span_name, kind=SpanKind.CLIENT) as span:
            span.set_attribute(GenAIAttributes.SYSTEM, "litellm")
            span.set_attribute(GenAIAttributes.OPERATION_NAME, GenAIOperation.CHAT.value)
            span.set_attribute(GenAIAttributes.REQUEST_MODEL, model)
            span.set_attribute(GenAIAttributes.MESSAGES, messages)

            if "temperature" in kwargs:
                span.set_attribute(GenAIAttributes.REQUEST_TEMPERATURE, kwargs["temperature"])

            try:
                response = original_completion(*args, **kwargs)
                if hasattr(response, "model"):
                    span.set_attribute(GenAIAttributes.RESPONSE_MODEL, response.model)

                if hasattr(response, "choices") and response.choices:
                    first_choice = response.choices[0]
                    msg = getattr(first_choice, "message", None)
                    if msg and getattr(msg, "content", None):
                        span.set_attribute(GenAIAttributes.COMPLETION, msg.content)

                if hasattr(response, "usage") and response.usage:
                    u = response.usage
                    in_t = getattr(u, "prompt_tokens", 0)
                    out_t = getattr(u, "completion_tokens", 0)
                    tot_t = getattr(u, "total_tokens", in_t + out_t)
                    span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, in_t)
                    span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, out_t)
                    span.set_attribute(GenAIAttributes.USAGE_TOTAL_TOKENS, tot_t)

                return response
            except Exception as e:
                span.record_exception(e)
                raise

    litellm.completion = patched_completion
    setattr(litellm, "_nanotrace_patched", True)
    logger.debug("[NanoTrace] LiteLLM patched successfully.")
    return True
