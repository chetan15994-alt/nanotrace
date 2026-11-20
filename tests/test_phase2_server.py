"""Unit & Integration tests for NanoTrace Server multi-tenant control plane & ingestion relay."""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from nanotrace.server import (
    KeyType,
    Role,
    ServerMetadataStorage,
    Workspace,
    create_server_app,
    generate_api_key,
    verify_api_key,
)
from nanotrace.server.auth import check_permission, Permission


@pytest.fixture
def temp_server_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "metadata.db")
        lakehouse_dir = os.path.join(tmp_dir, "lakehouse")
        app = create_server_app(db_path=db_path, lakehouse_dir=lakehouse_dir)
        client = TestClient(app)
        yield {
            "app": app,
            "client": client,
            "storage": app.state.storage,
            "relay": app.state.ingestion_relay,
            "db_path": db_path,
            "lakehouse_dir": lakehouse_dir,
        }


def test_workspace_and_project_lifecycle(temp_server_env):
    client = temp_server_env["client"]

    # 1. Create Workspace
    resp = client.post(
        "/api/v1/workspaces",
        json={
            "name": "Acme AI Corp",
            "slug": "acme-ai",
            "owner_email": "founder@acme.ai",
            "plan": "team",
        },
    )
    assert resp.status_code == 200
    ws = resp.json()
    assert ws["name"] == "Acme AI Corp"
    assert ws["slug"] == "acme-ai"
    ws_id = ws["workspace_id"]

    # Duplicate slug check
    resp_dup = client.post(
        "/api/v1/workspaces",
        json={
            "name": "Acme AI Corp 2",
            "slug": "acme-ai",
            "owner_email": "other@acme.ai",
        },
    )
    assert resp_dup.status_code == 400

    # 2. Create Project
    resp_proj = client.post(
        "/api/v1/projects",
        json={
            "workspace_id": ws_id,
            "name": "Customer Support Agent",
            "slug": "support-agent",
            "description": "24/7 autonomous support agent",
        },
    )
    assert resp_proj.status_code == 200
    proj = resp_proj.json()
    assert proj["name"] == "Customer Support Agent"
    assert proj["workspace_id"] == ws_id


def test_api_key_generation_and_rbac(temp_server_env):
    storage = temp_server_env["storage"]

    ws = storage.create_workspace(
        Workspace(name="Test Org", slug="test-org", owner_email="test@org.com", plan="team")
    )

    # Ingestion key
    ingest_key, raw_ingest = generate_api_key(
        workspace_id=ws.workspace_id,
        name="Fleet Key",
        key_type=KeyType.INGEST_ONLY,
    )
    assert raw_ingest.startswith("nt_live_")
    assert ingest_key.key_prefix == raw_ingest[:12]
    assert verify_api_key(raw_ingest, ingest_key.hashed_secret)

    # Admin key
    adm_key, raw_adm = generate_api_key(
        workspace_id=ws.workspace_id,
        name="Admin Key",
        key_type=KeyType.ADMIN,
    )
    assert raw_adm.startswith("nt_adm_")
    assert verify_api_key(raw_adm, adm_key.hashed_secret)

    # RBAC permissions
    assert check_permission(Role.OWNER, Permission.MANAGE_WORKSPACE)
    assert check_permission(Role.ADMIN, Permission.MANAGE_KEYS)
    assert not check_permission(Role.MEMBER, Permission.MANAGE_KEYS)
    assert check_permission(Role.MEMBER, Permission.INGEST_TRACES)
    assert not check_permission(Role.VIEWER, Permission.INGEST_TRACES)
    assert check_permission(Role.VIEWER, Permission.VIEW_TRACES)


def test_high_throughput_ingestion_and_lakehouse_query(temp_server_env):
    client = temp_server_env["client"]
    storage = temp_server_env["storage"]

    # Setup Workspace & API Key
    ws = storage.create_workspace(
        Workspace(name="FinTech Agents", slug="fintech", owner_email="fin@tech.com", plan="team")
    )
    api_key_obj, raw_token = generate_api_key(
        workspace_id=ws.workspace_id,
        name="Prod Cluster Key",
        key_type=KeyType.INGEST_ONLY,
    )
    storage.create_api_key(api_key_obj)

    # Test unauthorized access
    unauth_resp = client.post(
        "/api/v1/ingest",
        json={"spans": []},
    )
    assert unauth_resp.status_code == 401

    # Ingest 10 spans
    spans_payload = [
        {
            "span_id": f"sp_{i:04d}",
            "trace_id": "tr_1001",
            "name": f"agent_step_{i}",
            "span_type": "tool" if i % 2 == 0 else "agent",
            "status": "ok",
            "start_time_ns": 1_000_000_000 + i * 100_000_000,
            "end_time_ns": 1_000_000_000 + (i + 1) * 100_000_000,
            "duration_ms": 100.0,
            "model": "gpt-4o",
            "tokens_in": 150,
            "tokens_out": 50,
            "cost_usd": 0.002,
            "input": f"User query {i}",
            "output": f"Agent response {i}",
            "attributes": {"step_index": i},
            "node_id": "worker_pod_01",
        }
        for i in range(10)
    ]

    resp = client.post(
        "/api/v1/ingest",
        headers={"X-API-Key": raw_token},
        json={
            "workspace_id": ws.workspace_id,
            "project_id": "proj_fintech_bot",
            "node_id": "worker_pod_01",
            "spans": spans_payload,
        },
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["success"] is True
    assert res_data["accepted_spans"] == 10
    assert os.path.exists(res_data["lakehouse_partition"])

    # Query Lakehouse traces directly via REST API
    query_resp = client.post(
        "/api/v1/traces/query",
        json={
            "workspace_id": ws.workspace_id,
            "project_id": "proj_fintech_bot",
            "sql_query": "SELECT COUNT(*) as cnt, SUM(cost_usd) as total_spend FROM {traces}",
        },
    )
    assert query_resp.status_code == 200
    rows = query_resp.json()["traces"]
    assert rows[0]["cnt"] == 10
    assert abs(rows[0]["total_spend"] - 0.02) < 0.001
