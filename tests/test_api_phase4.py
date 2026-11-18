"""Testing Round 4: Web UI REST Endpoints for Phase 4 Prompt Studio, Feedback & Multi-Modal."""

import pytest
from fastapi.testclient import TestClient

import nanotrace
from nanotrace.ui.server import create_app
from nanotrace.prompts import PromptRegistry, PromptTemplate
from nanotrace.feedback import FeedbackCollector


@pytest.fixture
def phase4_api_client(tmp_path):
    db_file = str(tmp_path / "api_phase4.duckdb")
    tracer = nanotrace.init(storage_path=db_file, buffer_capacity=1000, flush_interval=0.01)

    # Seed a multi-modal span
    fake_png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    with tracer.span("analyze_chart") as sp:
        sp.prompt_payload = f"Inspect chart: {fake_png}"
        sp.completion_payload = "Detected 28% quarter-over-quarter revenue growth."

    tracer.flush()

    # Seed a prompt
    reg = PromptRegistry(db_path=db_file)
    reg.save(PromptTemplate(
        name="growth_analyzer",
        version="v1.0.0",
        template="Analyze {{metric}} for {{quarter}} given {{data}}.",
        tags=["staging"],
        author="alice",
    ))

    # Seed feedback
    collector = FeedbackCollector(db_path=db_file)
    collector.record(trace_id=sp.trace_id, score=1.0, comment="Spot on chart interpretation!")

    app = create_app(db_path=db_file)
    client = TestClient(app)

    yield client, sp.trace_id, sp.span_id, db_file

    try:
        tracer.shutdown()
    except Exception:
        pass


def test_api_prompts_crud_and_promote(phase4_api_client):
    client, trace_id, span_id, db_file = phase4_api_client

    # 1. List prompts
    resp = client.get("/api/prompts")
    assert resp.status_code == 200
    prompts = resp.json()
    assert len(prompts) >= 1
    assert any(p["name"] == "growth_analyzer" for p in prompts)

    # 2. Get prompt details
    resp2 = client.get("/api/prompts/growth_analyzer")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["prompt"]["name"] == "growth_analyzer"
    assert data["prompt"]["version"] == "v1.0.0"
    assert len(data["versions"]) == 1

    # 3. Create v2.0.0
    create_payload = {
        "name": "growth_analyzer",
        "version": "v2.0.0",
        "template": "Concise analysis of {{metric}} for {{quarter}}.",
        "tags": ["dev"],
        "author": "bob",
    }
    resp3 = client.post("/api/prompts", json=create_payload)
    assert resp3.status_code == 200
    saved = resp3.json()["prompt"]
    assert saved["version"] == "v2.0.0"

    # 4. Promote v2.0.0 to production
    promo_payload = {
        "name": "growth_analyzer",
        "version": "v2.0.0",
        "tag": "production",
    }
    resp4 = client.post("/api/prompts/promote", json=promo_payload)
    assert resp4.status_code == 200
    promoted = resp4.json()["prompt"]
    assert "production" in promoted["tags"]

    # 5. Delete v1.0.0
    del_resp = client.delete("/api/prompts/growth_analyzer?version=v1.0.0")
    assert del_resp.status_code == 200


def test_api_feedback_endpoints(phase4_api_client):
    client, trace_id, span_id, db_file = phase4_api_client

    # 1. Record feedback via API
    fb_payload = {
        "trace_id": trace_id,
        "score": -1.0,
        "comment": "Missed minor tax deduction clause.",
        "user_id": "auditor_1",
    }
    resp = client.post("/api/feedback", json=fb_payload)
    assert resp.status_code == 200
    entry = resp.json()["entry"]
    assert entry["score"] == -1.0

    # 2. Get feedback for trace
    resp2 = client.get(f"/api/feedback?trace_id={trace_id}")
    assert resp2.status_code == 200
    items = resp2.json()
    assert len(items) == 2  # initial + newly posted

    # 3. Get feedback stats
    resp3 = client.get("/api/feedback/stats")
    assert resp3.status_code == 200
    stats = resp3.json()
    assert stats["total_feedback"] == 2
    assert stats["positive_count"] == 1
    assert stats["negative_count"] == 1
    assert "recommended_golden_traces" in stats


def test_api_trace_multimodal_gallery(phase4_api_client):
    client, trace_id, span_id, db_file = phase4_api_client

    resp = client.get(f"/api/traces/{trace_id}/media")
    assert resp.status_code == 200
    media_data = resp.json()
    assert media_data["media_count"] == 1
    gallery = media_data["gallery"]
    assert gallery[0]["type"] == "image"
    assert gallery[0]["mime_type"] == "image/png"
    assert gallery[0]["is_base64"] is True
