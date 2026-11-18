"""Tests for Phase 2 API Endpoints: NanoShield Stats & Time-Travel Forking."""

import os
import pytest
from fastapi.testclient import TestClient

import nanotrace
from nanotrace.ui.server import create_app
from nanotrace.schema.otel import GenAIAttributes


@pytest.fixture
def api_client(tmp_path):
    db_file = str(tmp_path / "api_test.duckdb")
    tracer = nanotrace.init(storage_path=db_file, buffer_capacity=1000, flush_interval=0.01)

    with tracer.span("orchestrator_node") as parent:
        parent.set_attribute(GenAIAttributes.REQUEST_MODEL, "gpt-4o")
        parent.prompt_payload = "Generate market analysis"
        parent.completion_payload = "Market is bullish"

        with tracer.span("sub_action") as child:
            child.set_attribute(GenAIAttributes.REQUEST_MODEL, "gpt-4o-mini")
            child.prompt_payload = "Check tech index"
            child.completion_payload = "NASDAQ +1.5%"

    tracer.flush()
    app = create_app(db_path=db_file)
    client = TestClient(app)
    yield client, parent.trace_id, parent.span_id, child.span_id
    try:
        tracer.shutdown()
    except Exception:
        pass


def test_api_shield_stats(api_client):
    client, trace_id, parent_id, child_id = api_client
    resp = client.get("/api/shield/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active"] is True
    assert "total_tripped" in data
    assert "loops_intercepted" in data
    assert "estimated_spend_saved_usd" in data
    assert len(data["configured_breakers"]) == 4


def test_api_replay_context_success(api_client):
    client, trace_id, parent_id, child_id = api_client
    resp = client.get(f"/api/replay/{child_id}/context")
    assert resp.status_code == 200
    data = resp.json()
    assert data["target_span"]["span_id"] == child_id
    assert len(data["ancestors"]) == 1
    assert data["ancestors"][0]["span_id"] == parent_id


def test_api_replay_context_not_found(api_client):
    client, trace_id, parent_id, child_id = api_client
    resp = client.get("/api/replay/invalid_span_9999/context")
    assert resp.status_code == 404
    assert "Span not found" in resp.json()["detail"]


def test_api_fork_trace_node_success(api_client):
    client, trace_id, parent_id, child_id = api_client
    payload = {
        "span_id": parent_id,
        "prompt": "Generate market analysis with pessimistic outlook",
        "model": "gpt-4o-mini",
        "temperature": 0.3,
    }
    resp = client.post(f"/api/traces/{trace_id}/fork", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["original_span_id"] == parent_id
    assert data["model"] == "gpt-4o-mini"
    assert data["forked_trace_id"] != trace_id
    assert data["status"] == "OK"
    assert data["diff_summary"] != ""


def test_api_fork_trace_node_invalid_span(api_client):
    client, trace_id, parent_id, child_id = api_client
    payload = {
        "span_id": "nonexistent_id",
        "prompt": "Test override",
    }
    resp = client.post(f"/api/traces/{trace_id}/fork", json=payload)
    assert resp.status_code == 400
    assert "Cannot fork span" in resp.json()["detail"]
