"""Zero-code auto-instrumentation for the official OpenAI Python SDK.

Automatically captures prompt messages, streaming chunks, token usage, tool calls,
model latency, and costs according to CNCF OpenTelemetry GenAI semantic conventions.
"""

from __future__ import annotations

import time
import functools
import logging
from typing import Optional, Dict, Any, Generator

from nanotrace.core.context import get_current_span
from nanotrace.schema.otel import GenAIAttributes, GenAIOperation, SpanKind, StatusCode

logger = logging.getLogger("nanotrace")

# Approximate pricing per 1M tokens (USD) for common models
MODEL_PRICING = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "o1-preview": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate approximate USD cost for token usage."""
    for key, rates in MODEL_PRICING.items():
        if key in model.lower():
            in_cost = (input_tokens / 1_000_000) * rates["input"]
            out_cost = (output_tokens / 1_000_000) * rates["output"]
            return round(in_cost + out_cost, 6)
    return 0.0


def patch_openai(tracer) -> bool:
    """Monkey-patch the OpenAI SDK to auto-trace completions without user code changes."""
    try:
        import openai
        from openai.resources.chat.completions import Completions
    except ImportError:
        logger.debug("[NanoTrace] OpenAI SDK not installed. Skipping patch.")
        return False

    if getattr(Completions, "_nanotrace_patched", False):
        return True

    original_create = Completions.create

    @functools.wraps(original_create)
    def patched_create(self, *args, **kwargs):
        model = kwargs.get("model", "unknown-model")
        messages = kwargs.get("messages", [])
        stream = kwargs.get("stream", False)
        span_name = f"chat {model}"

        with tracer.span(span_name, kind=SpanKind.CLIENT) as span:
            span.set_attribute(GenAIAttributes.SYSTEM, "openai")
            span.set_attribute(GenAIAttributes.OPERATION_NAME, GenAIOperation.CHAT.value)
            span.set_attribute(GenAIAttributes.REQUEST_MODEL, model)
            span.set_attribute(GenAIAttributes.MESSAGES, messages)

            if "temperature" in kwargs:
                span.set_attribute(GenAIAttributes.REQUEST_TEMPERATURE, kwargs["temperature"])
            if "max_tokens" in kwargs:
                span.set_attribute(GenAIAttributes.REQUEST_MAX_TOKENS, kwargs["max_tokens"])

            if stream:
                # Handle streaming generator
                response = original_create(self, *args, **kwargs)
                return _wrap_stream(response, span, model)

            try:
                response = original_create(self, *args, **kwargs)
                _record_response_metadata(span, response, model)
                return response
            except Exception as e:
                span.record_exception(e)
                raise

    def _wrap_stream(stream_gen, span, model: str) -> Generator:
        """Stream wrapper to accumulate text and record token counts upon completion."""
        accumulated_text = []
        finish_reason = None
        try:
            for chunk in stream_gen:
                if hasattr(chunk, "choices") and chunk.choices:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        accumulated_text.append(delta.content)
                    if hasattr(chunk.choices[0], "finish_reason") and chunk.choices[0].finish_reason:
                        finish_reason = chunk.choices[0].finish_reason
                yield chunk
        finally:
            full_content = "".join(accumulated_text)
            span.set_attribute(GenAIAttributes.COMPLETION, full_content)
            if finish_reason:
                span.set_attribute(GenAIAttributes.RESPONSE_FINISH_REASONS, [finish_reason])
            # Estimate tokens for streaming if usage was not returned
            est_out_tokens = max(1, len(full_content.split()))
            span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, est_out_tokens)
            span.set_attribute(
                GenAIAttributes.USAGE_COST_USD,
                calculate_cost(model, 0, est_out_tokens),
            )

    def _record_response_metadata(span, response, model: str):
        """Extract tokens, model response, and finish reasons."""
        if hasattr(response, "model"):
            span.set_attribute(GenAIAttributes.RESPONSE_MODEL, response.model)

        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            if hasattr(choice, "message"):
                msg = choice.message
                if hasattr(msg, "content") and msg.content:
                    span.set_attribute(GenAIAttributes.COMPLETION, msg.content)
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    span.set_attribute(
                        GenAIAttributes.TOOL_ARGUMENTS,
                        [tc.model_dump() if hasattr(tc, "model_dump") else str(tc) for tc in msg.tool_calls],
                    )
            if hasattr(choice, "finish_reason"):
                span.set_attribute(GenAIAttributes.RESPONSE_FINISH_REASONS, [choice.finish_reason])

        if hasattr(response, "usage") and response.usage:
            u = response.usage
            in_tokens = getattr(u, "prompt_tokens", 0)
            out_tokens = getattr(u, "completion_tokens", 0)
            total_tokens = getattr(u, "total_tokens", in_tokens + out_tokens)

            span.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, in_tokens)
            span.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, out_tokens)
            span.set_attribute(GenAIAttributes.USAGE_TOTAL_TOKENS, total_tokens)
            span.set_attribute(
                GenAIAttributes.USAGE_COST_USD,
                calculate_cost(model, in_tokens, out_tokens),
            )

    Completions.create = patched_create
    Completions._nanotrace_patched = True
    return True
