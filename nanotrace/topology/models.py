"""Data models for Autonomous Swarm Topology & Communication DAG Optimization."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TopologyNode:
    """Represents an agent, tool, or reasoning step in the execution topology."""

    id: str
    name: str
    node_type: str = "agent"  # "agent", "tool", "llm", "router", "step"
    total_calls: int = 1
    total_duration_ms: float = 0.0
    total_cost_usd: float = 0.0
    error_count: int = 0
    avg_latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "node_type": self.node_type,
            "total_calls": self.total_calls,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "total_cost_usd": round(self.total_cost_usd, 5),
            "error_count": self.error_count,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
        }


@dataclass
class TopologyEdge:
    """Represents communication or delegation between two execution nodes."""

    source: str
    target: str
    call_count: int = 1
    avg_latency_ms: float = 0.0
    is_critical_path: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "call_count": self.call_count,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "is_critical_path": self.is_critical_path,
        }


@dataclass
class OptimizationRecommendation:
    """Actionable recommendation to prune redundant hops, reduce chatter, or parallelize."""

    rec_id: str = field(default_factory=lambda: f"rec_{uuid.uuid4().hex[:8]}")
    title: str = "Topology Optimization"
    category: str = "pruning"  # "pruning", "caching", "parallelize", "chatter_reduction"
    severity: str = "medium"  # "critical", "high", "medium", "info"
    description: str = ""
    estimated_savings_pct: float = 0.0
    estimated_cost_reduction_usd: float = 0.0
    suggested_patch: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rec_id": self.rec_id,
            "title": self.title,
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "estimated_savings_pct": round(self.estimated_savings_pct, 1),
            "estimated_cost_reduction_usd": round(self.estimated_cost_reduction_usd, 5),
            "suggested_patch": self.suggested_patch,
        }


@dataclass
class TopologyAnalysis:
    """Complete topological evaluation of an agent trace or multi-agent swarm."""

    trace_id: str
    total_agents: int = 0
    total_steps: int = 0
    critical_path_ms: float = 0.0
    communication_overhead_pct: float = 0.0
    nodes: List[TopologyNode] = field(default_factory=list)
    edges: List[TopologyEdge] = field(default_factory=list)
    recommendations: List[OptimizationRecommendation] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "total_agents": self.total_agents,
            "total_steps": self.total_steps,
            "critical_path_ms": round(self.critical_path_ms, 2),
            "communication_overhead_pct": round(self.communication_overhead_pct, 1),
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "recommendations": [r.to_dict() for r in self.recommendations],
            "created_at": self.created_at,
        }
