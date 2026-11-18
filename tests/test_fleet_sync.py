"""Round 1 Tests: NanoFleet Multi-Node Swarm Aggregation, Parquet Lakehouse Sync & Deduplication."""

import os
import tempfile
import pytest

from nanotrace.fleet.engine import FleetSyncEngine
from nanotrace.fleet.models import FleetNode, SyncResult
from nanotrace.storage.duckdb_sink import DuckDBSink
from nanotrace.core.span import Span
from nanotrace.schema.otel import SpanKind, StatusCode


def test_fleet_node_registration():
    """Verify worker node registration and retrieval in DuckDB."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_fleet.duckdb")
        engine = FleetSyncEngine(db_path=db_path)

        node = engine.register_node(
            node_id="pod_worker_us_east_1a",
            hostname="worker-pod-4921",
            ip_address="10.244.1.84",
            target_uri="s3://ai-traces-lakehouse/us-east-1/",
            metadata={"cluster": "k8s-prod-cluster", "region": "us-east-1"},
        )

        assert node.node_id == "pod_worker_us_east_1a"
        assert node.hostname == "worker-pod-4921"
        assert node.status == "active"
        assert node.metadata["cluster"] == "k8s-prod-cluster"

        nodes = engine.list_nodes()
        assert len(nodes) == 1
        assert nodes[0].node_id == "pod_worker_us_east_1a"
        assert nodes[0].ip_address == "10.244.1.84"


def test_fleet_snapshot_parquet_export_and_overview():
    """Verify exporting local spans to ZSTD-compressed Parquet micro-batches."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "node_worker.duckdb")
        sink = DuckDBSink(db_path=db_path)

        # Insert sample spans
        spans = []
        for i in range(5):
            sp = Span(name=f"agent_step_{i}", trace_id="trace_fleet_01")
            sp.end_time_ns = sp.start_time_ns + int((15.0 + i) * 1_000_000)
            sp.gen_ai_cost_usd = 0.002
            spans.append(sp)
        sink.write_spans(spans)
        sink.close()

        engine = FleetSyncEngine(db_path=db_path)
        engine.register_node(node_id="node_prod_01")

        export_dir = os.path.join(tmpdir, "cloud_lakehouse_sync")
        res = engine.export_snapshot(target_dir=export_dir, node_id="node_prod_01")

        assert res.status == "success"
        assert res.spans_exported == 5
        assert len(res.files_written) == 1
        assert os.path.exists(res.files_written[0])
        assert res.files_written[0].endswith(".parquet")

        overview = engine.get_fleet_overview()
        assert overview.total_nodes == 1
        assert overview.total_spans_aggregated == 5
        assert len(overview.recent_syncs) == 1
        assert overview.recent_syncs[0].spans_exported == 5


def test_fleet_multi_node_lakehouse_import():
    """Verify aggregating Parquet snapshots from multiple remote pods into central lakehouse."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sync_store = os.path.join(tmpdir, "shared_parquet_store")
        os.makedirs(sync_store, exist_ok=True)

        # ── Pod 1: creates and exports 4 spans ──────────────────────────────────
        db_pod1 = os.path.join(tmpdir, "pod1.duckdb")
        sink1 = DuckDBSink(db_path=db_pod1)
        spans1 = []
        for i in range(4):
            sp = Span(name=f"pod1_tool_{i}", trace_id="trace_multi_01")
            sp.end_time_ns = sp.start_time_ns + 10_000_000
            spans1.append(sp)
        sink1.write_spans(spans1)
        sink1.close()

        engine1 = FleetSyncEngine(db_path=db_pod1)
        res1 = engine1.export_snapshot(target_dir=sync_store, node_id="pod_01")
        assert res1.spans_exported == 4

        # ── Pod 2: creates and exports 6 spans ──────────────────────────────────
        db_pod2 = os.path.join(tmpdir, "pod2.duckdb")
        sink2 = DuckDBSink(db_path=db_pod2)
        spans2 = []
        for i in range(6):
            sp = Span(name=f"pod2_agent_{i}", trace_id="trace_multi_02")
            sp.end_time_ns = sp.start_time_ns + 12_000_000
            spans2.append(sp)
        sink2.write_spans(spans2)
        sink2.close()

        engine2 = FleetSyncEngine(db_path=db_pod2)
        res2 = engine2.export_snapshot(target_dir=sync_store, node_id="pod_02")
        assert res2.spans_exported == 6

        # ── Central Lakehouse: imports all parquet snapshots ────────────────────
        db_central = os.path.join(tmpdir, "central_lakehouse.duckdb")
        central_engine = FleetSyncEngine(db_path=db_central)
        central_engine.register_node(node_id="central_collector")

        imported = central_engine.import_fleet_snapshots(sync_store)
        assert imported == 10  # 4 from pod 1 + 6 from pod 2

        # Re-importing should deduplicate (0 new rows)
        imported_again = central_engine.import_fleet_snapshots(sync_store)
        assert imported_again == 0

        overview = central_engine.get_fleet_overview()
        assert overview.total_spans_aggregated == 10


def test_fleet_empty_spans_export_handling():
    """Verify export handles empty spans table with clean no_op status."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "empty.duckdb")
        engine = FleetSyncEngine(db_path=db_path)
        res = engine.export_snapshot(target_dir=os.path.join(tmpdir, "out"))
        assert res.status == "no_op"
        assert res.spans_exported == 0
