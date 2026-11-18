"""Feedback data models for NanoTrace end-user sentiment tracking."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class FeedbackEntry:
    """Represents an end-user rating, thumbs-up/down, or qualitative feedback attached to a trace."""
    trace_id: str
    score: float  # e.g. 1.0 = positive, -1.0 = negative, 0.0 = neutral
    comment: Optional[str] = None
    span_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    feedback_id: str = field(default_factory=lambda: f"fb_{uuid.uuid4().hex[:12]}")
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "score": self.score,
            "comment": self.comment,
            "user_id": self.user_id,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FeedbackEntry:
        return cls(
            trace_id=data["trace_id"],
            score=float(data["score"]),
            comment=data.get("comment"),
            span_id=data.get("span_id"),
            user_id=data.get("user_id"),
            metadata=data.get("metadata") or {},
            feedback_id=data.get("feedback_id") or f"fb_{uuid.uuid4().hex[:12]}",
            created_at=data.get("created_at") or datetime.now(timezone.utc).isoformat(),
        )
