"""Round 3 Tests: Phase 6 REST API Endpoints for Fleet Sync and Topology Optimizer."""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from nanotrace.core.span import Span
from nanotrace.storage.duckdb_sink import DuckDBSink
from nanotrace.ui.server import create_app


@pytest.fixture
def api_client():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_api_p6.duckdb")
        sink = DuckDBSink(db_path=db_path)

        # Seed sample multi-agent trace
        t_id = "trace_api_topo_01"
        s1 = Span(name="SupervisorAgent", trace_id=t_id)
        s1.start_time_ns = 1_000_000_000
        s1.end_time_ns = 1_500_000_000
        s1.gen_ai_agent_name = "SupervisorAgent"

        s2 = Span(name="WorkerAgent", trace_id=t_id, parent_span_id=s1.span_id)
        s2.start_time_ns = 1_100_000_000
        s2.end_time_ns = 1_400_000_000
        s2.gen_ai_agent_name = "WorkerAgent"

        sink.write_spans([s1, s2])
        sink.close()

        app = create_app(db_path=db_path)
        client = TestClient(app)
        yield client, db_path, tmpdir


def test_api_fleet_overview_and_nodes(api_client):
    client, db_path, tmpdir = api_client

    # Test fleet overview initially
    res_ov = client.get("/api/fleet/overview")
    assert res_ov.status_code == 200
    ov_data = res_ov.json()
    assert "total_nodes" in ov_data
    assert "total_spans_aggregated" in ov_data
    assert ov_data["total_spans_aggregated"] == 2

    # Test fleet nodes list
    res_nodes = client.get("/api/fleet/nodes")
    assert res_nodes.status_code == 200
    assert isinstance(res_nodes.json(), list)


def test_api_fleet_sync_export_and_import(api_client):
    client, db_path, tmpdir = api_client
    sync_dir = os.path.join(tmpdir, "api_sync_target")

    # 1. Trigger export
    res_export = client.post("/api/fleet/sync", json={
        "target_dir": sync_dir,
        "node_id": "pod_api_test",
        "mode": "export",
    })
    assert res_export.status_code == 200
    data_exp = res_export.json()
    assert data_exp["status"] == "ok"
    assert data_exp["mode"] == "export"
    assert data_exp["result"]["spans_exported"] == 2

    # 2. Trigger import (deduplicates against same db)
    res_import = client.post("/api/fleet/sync", json={
        "target_dir": sync_dir,
        "mode": "import",
    })
    assert res_import.status_code == 200
    data_imp = res_import.json()
    assert data_imp["status"] == "ok"
    assert data_imp["mode"] == "import"
    assert data_imp["spans_imported"] == 0  # Deduplicated


def test_api_topology_endpoints(api_client):
    client, db_path, tmpdir = api_client

    # 1. Analyze specific trace
    res_trace = client.get("/api/topology/trace/trace_api_topo_01")
    assert res_trace.status_code == 200
    data_t = res_trace.json()
    assert data_t["trace_id"] == "trace_api_topo_01"
    assert data_t["total_steps"] == 2
    assert len(data_t["nodes"]) >= 2
    assert len(data_t["edges"]) >= 1

    # 2. Analyze latest trace
    res_latest = client.get("/api/topology/latest")
    assert res_latest.status_code == 200
    data_l = res_latest.json()
    assert data_l["trace_id"] == "trace_api_topo_01"
    assert data_l["critical_path_ms"] > 0.0
