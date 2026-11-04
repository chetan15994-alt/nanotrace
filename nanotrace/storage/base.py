"""StorageSink abstract base class for NanoTrace."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from nanotrace.core.span import Span


class StorageSink(ABC):
    """Abstract interface for storing and querying NanoTrace spans."""

    @abstractmethod
    def write_spans(self, spans: List[Span]) -> int:
        """Persist a batch of spans. Returns the count of successfully persisted spans."""
        pass

    @abstractmethod
    def query(self, sql_or_filter: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Query stored traces."""
        pass

    @abstractmethod
    def get_trace_tree(self, trace_id: str) -> List[Dict[str, Any]]:
        """Retrieve all spans belonging to a trace_id ordered by start_time."""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate metrics (span count, token usage, latency percentiles)."""
        pass

    @abstractmethod
    def flush(self) -> None:
        """Force flush pending transactions."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Cleanly close database connections."""
        pass
