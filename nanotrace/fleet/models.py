"""Data models for NanoFleet: Multi-Node Swarm Aggregation & Parquet Cloud Sync."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FleetNode:
    """Represents an agent worker pod or node in a distributed swarm."""

    node_id: str = field(default_factory=lambda: f"node_{uuid.uuid4().hex[:8]}")
    hostname: str = "localhost"
    ip_address: str = "127.0.0.1"
    status: str = "active"  # "active", "syncing", "offline", "idle"
    spans_synced: int = 0
    last_sync_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    target_uri: str = "local"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "hostname": self.hostname,
            "ip_address": self.ip_address,
            "status": self.status,
            "spans_synced": self.spans_synced,
            "last_sync_at": self.last_sync_at,
            "target_uri": self.target_uri,
            "metadata": self.metadata,
        }


@dataclass
class SyncResult:
    """Outcome of a fleet synchronization or Parquet export job."""

    node_id: str
    target_uri: str
    spans_exported: int
    files_written: List[str]
    elapsed_ms: float
    status: str = "success"  # "success", "failed", "no_op"
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "target_uri": self.target_uri,
            "spans_exported": self.spans_exported,
            "files_written": self.files_written,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "status": self.status,
            "error": self.error,
            "created_at": self.created_at,
        }


@dataclass
class FleetOverview:
    """Aggregated health and telemetry metrics across all swarm nodes."""

    total_nodes: int = 0
    active_nodes: int = 0
    total_spans_aggregated: int = 0
    last_sync_time: str = ""
    nodes: List[FleetNode] = field(default_factory=list)
    recent_syncs: List[SyncResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_nodes": self.total_nodes,
            "active_nodes": self.active_nodes,
            "total_spans_aggregated": self.total_spans_aggregated,
            "last_sync_time": self.last_sync_time,
            "nodes": [n.to_dict() for n in self.nodes],
            "recent_syncs": [s.to_dict() for s in self.recent_syncs],
        }
