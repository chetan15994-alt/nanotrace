"""In-process DuckDB-backed feedback collector for NanoTrace."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import duckdb

from nanotrace.exceptions import FeedbackError
from nanotrace.feedback.models import FeedbackEntry


class FeedbackCollector:
    """Records and aggregates end-user ratings and sentiment directly against traces in DuckDB."""

    def __init__(self, db_path: str = "./.traces/nanotrace.duckdb"):
        self.db_path = str(db_path)
        self._ensure_storage_dir()
        self._ensure_schema()

    def _ensure_storage_dir(self) -> None:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.db_path)

    def _ensure_schema(self) -> None:
        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trace_feedback (
                    feedback_id VARCHAR PRIMARY KEY,
                    trace_id VARCHAR,
                    span_id VARCHAR,
                    score DOUBLE,
                    comment TEXT,
                    user_id VARCHAR,
                    metadata_json TEXT,
                    created_at VARCHAR
                );
            """)
        finally:
            conn.close()

    def record(
        self,
        trace_id: str,
        score: float,
        comment: Optional[str] = None,
        span_id: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> FeedbackEntry:
        """Record a feedback rating against a trace."""
        if not trace_id:
            raise FeedbackError("trace_id is required to record feedback.")

        entry = FeedbackEntry(
            trace_id=trace_id,
            score=float(score),
            comment=comment,
            span_id=span_id,
            user_id=user_id,
            metadata=metadata or {},
        )

        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO trace_feedback (
                    feedback_id, trace_id, span_id, score, comment, user_id, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                entry.feedback_id,
                entry.trace_id,
                entry.span_id,
                entry.score,
                entry.comment,
                entry.user_id,
                json.dumps(entry.metadata),
                entry.created_at,
            ])
            return entry
        finally:
            conn.close()

    def get_for_trace(self, trace_id: str) -> List[FeedbackEntry]:
        """Retrieve all feedback entries associated with a specific trace."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM trace_feedback WHERE trace_id = ? ORDER BY created_at DESC",
                [trace_id]
            ).fetchall()
            cols = [d[0] for d in conn.description]
            return [self._row_to_entry(dict(zip(cols, r))) for r in rows]
        finally:
            conn.close()

    def list_feedback(self, limit: int = 50) -> List[FeedbackEntry]:
        """List recent feedback entries across all traces."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM trace_feedback ORDER BY created_at DESC LIMIT ?",
                [limit]
            ).fetchall()
            cols = [d[0] for d in conn.description]
            return [self._row_to_entry(dict(zip(cols, r))) for r in rows]
        finally:
            conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Calculate aggregate sentiment metrics and golden candidate counts."""
        conn = self._get_connection()
        try:
            row = conn.execute("""
                SELECT 
                    COUNT(*) as total_feedback,
                    SUM(CASE WHEN score > 0 THEN 1 ELSE 0 END) as positive_count,
                    SUM(CASE WHEN score < 0 THEN 1 ELSE 0 END) as negative_count,
                    SUM(CASE WHEN score = 0 THEN 1 ELSE 0 END) as neutral_count,
                    AVG(score) as avg_score
                FROM trace_feedback
            """).fetchone()

            total = int(row[0] or 0)
            positive = int(row[1] or 0)
            negative = int(row[2] or 0)
            neutral = int(row[3] or 0)
            avg_score = round(float(row[4] or 0.0), 3)
            net_sentiment = round(((positive - negative) / total) * 100.0, 1) if total > 0 else 0.0

            return {
                "total_feedback": total,
                "positive_count": positive,
                "negative_count": negative,
                "neutral_count": neutral,
                "average_score": avg_score,
                "net_sentiment_pct": net_sentiment,
            }
        finally:
            conn.close()

    def get_recommended_golden_traces(self, min_score: float = 0.5) -> List[str]:
        """Fetch distinct trace IDs with positive sentiment recommended for golden evaluation suites."""
        conn = self._get_connection()
        try:
            rows = conn.execute("""
                SELECT DISTINCT trace_id 
                FROM trace_feedback 
                WHERE score >= ? 
                ORDER BY trace_id ASC
            """, [min_score]).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    def _row_to_entry(self, rd: Dict[str, Any]) -> FeedbackEntry:
        return FeedbackEntry(
            trace_id=rd["trace_id"],
            score=float(rd["score"]),
            comment=rd.get("comment"),
            span_id=rd.get("span_id"),
            user_id=rd.get("user_id"),
            metadata=json.loads(rd.get("metadata_json") or "{}"),
            feedback_id=rd["feedback_id"],
            created_at=str(rd.get("created_at") or ""),
        )
