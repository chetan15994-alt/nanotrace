"""In-memory storage sink for testing and ephemeral workflows."""

from __future__ import annotations

import threading
from typing import List, Dict, Any, Optional

from nanotrace.core.span import Span
from nanotrace.storage.base import StorageSink


class MemorySink(StorageSink):
    """In-memory trace store."""

    def __init__(self):
        self._lock = threading.Lock()
        self._spans: List[Span] = []

    def write_spans(self, spans: List[Span]) -> int:
        with self._lock:
            self._spans.extend(spans)
            return len(spans)

    def query(self, sql_or_filter: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        with self._lock:
            return [s.to_flat_dict() for s in self._spans]

    def get_trace_tree(self, trace_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            filtered = [s.to_flat_dict() for s in self._spans if s.trace_id == trace_id]
            filtered.sort(key=lambda x: x["start_time_ns"])
            return filtered

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            traces = set(s.trace_id for s in self._spans)
            total_tokens = sum(s.attributes.get("gen_ai.usage.total_tokens", 0) for s in self._spans)
            errors = sum(1 for s in self._spans if s.status.value == "ERROR")
            return {
                "total_traces": len(traces),
                "total_spans": len(self._spans),
                "total_tokens": total_tokens,
                "error_rate_pct": (errors / len(self._spans) * 100) if self._spans else 0.0,
            }

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass
