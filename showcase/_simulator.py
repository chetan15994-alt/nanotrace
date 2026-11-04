"""Shared simulation utilities for NanoTrace showcase agents.

Provides mock_llm_call, mock_tool_call, mock_embedding, and mock_retrieval
that produce structurally identical OpenTelemetry spans to real LLM/tool
invocations — with realistic latency, token counts, and USD cost tracking —
all without requiring API keys or network access.

Token estimation uses the industry-standard ~4 characters per token heuristic.
Latency is proportional to output size with per-model calibration and jitter.
"""

from __future__ import annotations

import time
import random
import hashlib
from typing import Any, Dict, List, Optional

import nanotrace
from nanotrace.schema.otel import (
    GenAIAttributes,
    GenAIOperation,
    SpanKind,
    StatusCode,
)

# ── Token Estimation ────────────────────────────────────────────────────────
CHARS_PER_TOKEN = 4  # Industry-standard approximation


def estimate_tokens(text: Any) -> int:
    """Estimate token count from text using ~4 chars/token heuristic."""
    s = str(text) if text else ""
    return max(1, len(s) // CHARS_PER_TOKEN)


# ── Model Pricing & Latency ────────────────────────────────────────────────
MODEL_CATALOG = {
    "gpt-4o": {
        "input": 2.50, "output": 10.00,
        "provider": "openai",
        "latency_per_100tok_ms": 15,
    },
    "gpt-4o-mini": {
        "input": 0.15, "output": 0.60,
        "provider": "openai",
        "latency_per_100tok_ms": 8,
    },
    "claude-3-5-sonnet": {
        "input": 3.00, "output": 15.00,
        "provider": "anthropic",
        "latency_per_100tok_ms": 18,
    },
    "claude-3-haiku": {
        "input": 0.25, "output": 1.25,
        "provider": "anthropic",
        "latency_per_100tok_ms": 5,
    },
    "gemini-2.0-flash": {
        "input": 0.10, "output": 0.40,
        "provider": "google",
        "latency_per_100tok_ms": 6,
    },
    "text-embedding-3-small": {
        "input": 0.02, "output": 0.0,
        "provider": "openai",
        "latency_per_100tok_ms": 3,
    },
}

_DEFAULT_CATALOG = {"input": 1.0, "output": 2.0, "provider": "custom", "latency_per_100tok_ms": 10}


def _get_model_info(model: str) -> dict:
    return MODEL_CATALOG.get(model, _DEFAULT_CATALOG)


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate USD cost for given token usage."""
    info = _get_model_info(model)
    return round(
        (input_tokens / 1_000_000) * info["input"]
        + (output_tokens / 1_000_000) * info["output"],
        6,
    )


def _simulate_latency(model: str, output_tokens: int) -> None:
    """Sleep for a realistic duration based on model speed and output size."""
    info = _get_model_info(model)
    base_ms = info["latency_per_100tok_ms"]
    total_ms = max(5, (output_tokens / 100) * base_ms + random.uniform(5, 25))
    time.sleep(total_ms / 1000)


# ── Core Simulation Functions ───────────────────────────────────────────────


def mock_llm_call(
    model: str,
    system_prompt: str,
    user_message: str,
    response: str,
    span_name: Optional[str] = None,
    temperature: float = 0.7,
) -> str:
    """Simulate an LLM chat completion within a fully-attributed OTel span.

    Produces spans indistinguishable from real OpenAI/Anthropic/Google calls:
    same attribute keys, same token fields, same cost structure.

    Args:
        model: Model identifier (e.g. "gpt-4o", "claude-3-5-sonnet")
        system_prompt: System/instruction message
        user_message: User query
        response: Pre-scripted LLM response text
        span_name: Override span name (default: "chat {model}")
        temperature: Sampling temperature attribute

    Returns:
        The response string (unchanged).
    """
    info = _get_model_info(model)
    provider = info["provider"]
    name = span_name or f"chat {model}"

    input_text = f"{system_prompt}\n{user_message}"
    input_tokens = estimate_tokens(input_text)
    output_tokens = estimate_tokens(response)
    total_tokens = input_tokens + output_tokens
    cost = compute_cost(model, input_tokens, output_tokens)

    with nanotrace.span(name, kind=SpanKind.CLIENT, attributes={
        GenAIAttributes.SYSTEM: provider,
        GenAIAttributes.PROVIDER_NAME: provider,
        GenAIAttributes.OPERATION_NAME: GenAIOperation.CHAT.value,
        GenAIAttributes.REQUEST_MODEL: model,
        GenAIAttributes.RESPONSE_MODEL: model,
        GenAIAttributes.REQUEST_TEMPERATURE: temperature,
        GenAIAttributes.MESSAGES: [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        GenAIAttributes.PROMPT: user_message,
        GenAIAttributes.COMPLETION: response,
        GenAIAttributes.USAGE_INPUT_TOKENS: input_tokens,
        GenAIAttributes.USAGE_OUTPUT_TOKENS: output_tokens,
        GenAIAttributes.USAGE_TOTAL_TOKENS: total_tokens,
        GenAIAttributes.USAGE_COST_USD: cost,
        GenAIAttributes.RESPONSE_FINISH_REASONS: ["stop"],
    }):
        _simulate_latency(model, output_tokens)

    return response


def mock_tool_call(
    tool_name: str,
    arguments: Any,
    result: Any,
    latency_ms: float = 20.0,
    error: Optional[str] = None,
) -> Any:
    """Simulate a tool execution within a traced span.

    Args:
        tool_name: Name of the tool (e.g. "web_search", "sql_query")
        arguments: Tool input arguments (dict or string)
        result: Expected tool output (returned on success)
        latency_ms: Base execution time in milliseconds
        error: If set, marks the span as ERROR with this message

    Returns:
        The result on success, None on error.
    """
    with nanotrace.span(f"tool: {tool_name}", kind=SpanKind.CLIENT, attributes={
        GenAIAttributes.OPERATION_NAME: GenAIOperation.EXECUTE_TOOL.value,
        GenAIAttributes.TOOL_NAME: tool_name,
        GenAIAttributes.TOOL_ARGUMENTS: arguments,
    }) as sp:
        time.sleep(latency_ms / 1000 + random.uniform(0.002, 0.012))

        if error:
            sp.set_attribute(GenAIAttributes.TOOL_OUTPUT, error)
            sp.set_attribute(GenAIAttributes.ERROR_TYPE, "ToolExecutionError")
            sp.set_attribute(GenAIAttributes.ERROR_MESSAGE, error)
            sp.set_status(StatusCode.ERROR, error)
            return None

        sp.set_attribute(GenAIAttributes.TOOL_OUTPUT, result)
        sp.set_attribute(GenAIAttributes.TOOL_STATUS, "success")
        return result


def mock_embedding(
    model: str,
    text: str,
    dimensions: int = 1536,
    latency_ms: float = 15.0,
) -> List[float]:
    """Simulate an embedding API call with a deterministic pseudo-vector.

    The vector is seeded by the input text hash, so identical inputs
    always produce identical embeddings (useful for testing retrieval).
    """
    tokens = estimate_tokens(text)
    info = _get_model_info(model)
    provider = info["provider"]
    cost = compute_cost(model, tokens, 0)

    with nanotrace.span(f"embedding {model}", kind=SpanKind.CLIENT, attributes={
        GenAIAttributes.SYSTEM: provider,
        GenAIAttributes.OPERATION_NAME: GenAIOperation.EMBEDDING.value,
        GenAIAttributes.REQUEST_MODEL: model,
        GenAIAttributes.USAGE_INPUT_TOKENS: tokens,
        GenAIAttributes.USAGE_TOTAL_TOKENS: tokens,
        GenAIAttributes.USAGE_COST_USD: cost,
        GenAIAttributes.PROMPT: text[:300],
    }):
        time.sleep(latency_ms / 1000)
        seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        return [rng.uniform(-1, 1) for _ in range(min(dimensions, 8))]  # Truncated for storage


def mock_retrieval(
    query: str,
    results: List[Dict[str, Any]],
    top_k: int = 3,
    latency_ms: float = 25.0,
) -> List[Dict[str, Any]]:
    """Simulate a vector search / retrieval operation."""
    with nanotrace.span("retrieval vector_search", kind=SpanKind.CLIENT, attributes={
        GenAIAttributes.OPERATION_NAME: GenAIOperation.RETRIEVAL.value,
        GenAIAttributes.RETRIEVAL_QUERY: query,
        GenAIAttributes.RETRIEVAL_TOP_K: top_k,
        GenAIAttributes.RETRIEVAL_DOCUMENTS: results[:top_k],
    }):
        time.sleep(latency_ms / 1000 + random.uniform(0.002, 0.010))
        return results[:top_k]
