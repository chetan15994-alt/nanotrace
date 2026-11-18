"""Data models for NanoDrift vector diagnostics and RAG Hallucination Radar."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class RetrievedChunk:
    """Represents a single document chunk retrieved from a vector database or search index."""

    chunk_id: str
    text: str
    similarity_score: float = 0.0
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "similarity_score": round(self.similarity_score, 4),
            "metadata": self.metadata,
        }


@dataclass
class RAGQueryRecord:
    """Represents a user or agent RAG query and its retrieved context chunks."""

    query_id: str = field(default_factory=lambda: f"rag_{uuid.uuid4().hex[:12]}")
    trace_id: Optional[str] = None
    query_text: str = ""
    query_embedding: Optional[List[float]] = None
    retrieved_chunks: List[RetrievedChunk] = field(default_factory=list)
    top_k: int = 0
    min_similarity: float = 0.0
    mean_similarity: float = 0.0
    is_semantic_void: bool = False
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def __post_init__(self):
        if self.retrieved_chunks:
            self.top_k = len(self.retrieved_chunks)
            scores = [c.similarity_score for c in self.retrieved_chunks]
            self.min_similarity = round(min(scores), 4) if scores else 0.0
            self.mean_similarity = round(sum(scores) / len(scores), 4) if scores else 0.0
        else:
            self.top_k = 0
            self.min_similarity = 0.0
            self.mean_similarity = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_id": self.query_id,
            "trace_id": self.trace_id,
            "query_text": self.query_text,
            "top_k": self.top_k,
            "min_similarity": round(self.min_similarity, 4),
            "mean_similarity": round(self.mean_similarity, 4),
            "is_semantic_void": self.is_semantic_void,
            "retrieved_chunks": [c.to_dict() for c in self.retrieved_chunks],
            "created_at": self.created_at,
        }


@dataclass
class RAGRadarPoint:
    """Projected 2D coordinate for interactive radar scatter plot."""

    id: str
    x: float
    y: float
    label: str
    point_type: str  # "query", "chunk", "void"
    similarity: float
    text_snippet: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "x": round(self.x, 2),
            "y": round(self.y, 2),
            "label": self.label,
            "point_type": self.point_type,
            "similarity": round(self.similarity, 4),
            "text_snippet": self.text_snippet[:120] + ("..." if len(self.text_snippet) > 120 else ""),
            "metadata": self.metadata,
        }


@dataclass
class RAGRadarSummary:
    """Aggregated summary of RAG retrieval health and semantic coverage."""

    total_queries: int = 0
    semantic_void_count: int = 0
    void_rate_pct: float = 0.0
    mean_similarity: float = 0.0
    radar_points: List[RAGRadarPoint] = field(default_factory=list)
    void_queries: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_queries": self.total_queries,
            "semantic_void_count": self.semantic_void_count,
            "void_rate_pct": round(self.void_rate_pct, 1),
            "mean_similarity": round(self.mean_similarity, 4),
            "radar_points": [p.to_dict() for p in self.radar_points],
            "void_queries": self.void_queries,
        }
