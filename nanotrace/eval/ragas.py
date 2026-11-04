"""Trace-to-Ragas conversion bridge for NanoTrace.

Transforms agent traces into Ragas SingleTurnSample and EvaluationDataset objects.
"""

from __future__ import annotations

import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

try:
    from ragas import EvaluationDataset, SingleTurnSample
except ImportError:
    @dataclass
    class SingleTurnSample:  # type: ignore
        user_input: str
        response: str
        retrieved_contexts: Optional[List[str]] = None
        reference: Optional[str] = None

    @dataclass
    class EvaluationDataset:  # type: ignore
        samples: List[SingleTurnSample]


def spans_to_ragas_sample(spans: List[Dict[str, Any]]) -> Optional[SingleTurnSample]:
    """Convert spans of a trace into a Ragas SingleTurnSample."""
    if not spans:
        return None

    root_span = next((s for s in spans if not s.get("parent_span_id")), spans[0])

    user_input = ""
    prompt_raw = root_span.get("prompt_payload")
    if prompt_raw:
        try:
            parsed = json.loads(prompt_raw) if isinstance(prompt_raw, str) else prompt_raw
            if isinstance(parsed, dict) and "args" in parsed and parsed["args"]:
                user_input = str(parsed["args"][0])
            else:
                user_input = str(parsed)
        except Exception:
            user_input = str(prompt_raw)

    response = ""
    comp_raw = root_span.get("completion_payload")
    if comp_raw:
        try:
            parsed = json.loads(comp_raw) if isinstance(comp_raw, str) else comp_raw
            response = str(parsed)
        except Exception:
            response = str(comp_raw)

    retrieved = []
    for s in spans:
        if s.get("gen_ai_operation") == "retrieval":
            doc = s.get("completion_payload")
            if doc:
                retrieved.append(str(doc))

    return SingleTurnSample(
        user_input=user_input or "Agent prompt",
        response=response or "Agent answer",
        retrieved_contexts=retrieved if retrieved else None,
    )


def trace_records_to_ragas(records: List[Dict[str, Any]]) -> EvaluationDataset:
    """Group trace records by trace_id and return a Ragas EvaluationDataset."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        tid = r.get("trace_id", "")
        if tid:
            grouped.setdefault(tid, []).append(r)

    samples = []
    for tid, spans in grouped.items():
        sample = spans_to_ragas_sample(spans)
        if sample:
            samples.append(sample)

    return EvaluationDataset(samples=samples)
