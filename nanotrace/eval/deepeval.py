"""Trace-to-DeepEval conversion bridge for NanoTrace.

Transforms hierarchical agent traces into DeepEval LLMTestCase objects
with automatic mapping of input queries, actual outputs, and retrieved context.
"""

from __future__ import annotations

import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

try:
    from deepeval.test_case import LLMTestCase
except ImportError:
    @dataclass
    class LLMTestCase:  # type: ignore
        """Fallback duck-typed LLMTestCase when deepeval is not installed."""
        input: str
        actual_output: str
        expected_output: Optional[str] = None
        retrieval_context: Optional[List[str]] = None
        context: Optional[List[str]] = None
        tools_called: Optional[List[str]] = None


def spans_to_deepeval_test_case(spans: List[Dict[str, Any]]) -> Optional[LLMTestCase]:
    """Parse a single trace's spans and construct an LLMTestCase."""
    if not spans:
        return None

    # Identify root span (parent_span_id is empty or None)
    root_span = next((s for s in spans if not s.get("parent_span_id")), spans[0])

    # Extract user input query
    user_input = ""
    prompt_raw = root_span.get("prompt_payload")
    if prompt_raw:
        try:
            parsed = json.loads(prompt_raw) if isinstance(prompt_raw, str) else prompt_raw
            if isinstance(parsed, dict) and "args" in parsed and parsed["args"]:
                user_input = str(parsed["args"][0])
            elif isinstance(parsed, list) and parsed:
                # If messages array
                user_input = str(parsed[-1].get("content", ""))
            else:
                user_input = str(parsed)
        except Exception:
            user_input = str(prompt_raw)

    # Extract final output
    actual_output = ""
    completion_raw = root_span.get("completion_payload")
    if completion_raw:
        try:
            parsed = json.loads(completion_raw) if isinstance(completion_raw, str) else completion_raw
            actual_output = str(parsed)
        except Exception:
            actual_output = str(completion_raw)

    # If root span did not have output, look at the last child LLM completion
    if not actual_output:
        for s in reversed(spans):
            if s.get("completion_payload"):
                actual_output = str(s["completion_payload"])
                break

    # Extract retrieved contexts
    retrieval_contexts: List[str] = []
    tools_called: List[str] = []

    for s in spans:
        # Check tool execution
        tool_name = s.get("gen_ai_tool_name")
        if tool_name:
            tools_called.append(tool_name)

        # Check retrieval spans
        if s.get("gen_ai_operation") == "retrieval":
            output = s.get("completion_payload") or s.get("attributes_json")
            if output:
                retrieval_contexts.append(str(output))

    return LLMTestCase(
        input=user_input or "Agent execution query",
        actual_output=actual_output or "Agent response",
        retrieval_context=retrieval_contexts if retrieval_contexts else None,
        tools_called=tools_called if tools_called else None,
    )


def trace_records_to_deepeval(records: List[Dict[str, Any]]) -> List[LLMTestCase]:
    """Group trace records by trace_id and return a list of LLMTestCases."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        tid = r.get("trace_id", "")
        if tid:
            grouped.setdefault(tid, []).append(r)

    cases = []
    for tid, spans in grouped.items():
        case = spans_to_deepeval_test_case(spans)
        if case:
            cases.append(case)
    return cases
