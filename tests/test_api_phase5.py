"""Round 3 Tests: Phase 5 REST API Endpoints for RAG Radar & Autonomous Red-Teaming."""

import tempfile
import pytest
from starlette.testclient import TestClient

from nanotrace.ui.server import create_app


@pytest.fixture
def api_client():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/api_p5.duckdb"
        app = create_app(db_path=db_path)
        with TestClient(app) as client:
            yield client, db_path


def test_api_rag_record_and_radar(api_client):
    """Verify POST /api/rag/record and GET /api/rag/radar."""
    client, _ = api_client

    # 1. Record a high-similarity query
    resp = client.post(
        "/api/rag/record",
        json={
            "query_text": "What is the capital of France?",
            "retrieved_chunks": [
                {"chunk_id": "c1", "text": "Paris is the capital and largest city of France.", "similarity_score": 0.94}
            ],
            "trace_id": "tr_paris_001",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["query_id"].startswith("rag_")
    assert not data["is_semantic_void"]
    assert data["mean_similarity"] == 0.94

    # 2. Record a semantic void query
    resp_void = client.post(
        "/api/rag/record",
        json={
            "query_text": "Quantum teleportation latency on Mars",
            "retrieved_chunks": [
                {"chunk_id": "c_bad", "text": "Cooking pasta recipe", "similarity_score": 0.22}
            ],
            "trace_id": "tr_mars_002",
        },
    )
    assert resp_void.status_code == 200
    assert resp_void.json()["is_semantic_void"]

    # 3. Fetch radar summary
    radar_resp = client.get("/api/rag/radar")
    assert radar_resp.status_code == 200
    r_data = radar_resp.json()
    assert r_data["total_queries"] == 2
    assert r_data["semantic_void_count"] == 1
    assert r_data["void_rate_pct"] == 50.0
    assert len(r_data["radar_points"]) == 2


def test_api_rag_scan_spans(api_client):
    """Verify POST /api/rag/scan imports retrieval spans into radar."""
    client, db_path = api_client
    import nanotrace

    tracer = nanotrace.init(storage_path=db_path)
    with tracer.span("retrieve_customer_docs") as sp:
        sp.gen_ai_operation = "retrieval"
        sp.prompt_payload = '{"query": "Find user billing invoices"}'
        sp.completion_payload = '{"results": ["Invoice #102: $450", "Invoice #103: $120"]}'
    tracer.shutdown()

    resp = client.post("/api/rag/scan")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scanned_count"] >= 1
    assert data["radar"]["total_queries"] >= 1


def test_api_security_attacks_catalog(api_client):
    """Verify GET /api/security/attacks returns categorized catalog."""
    client, _ = api_client
    resp = client.get("/api/security/attacks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 12
    assert any(a["attack_type"] == "prompt_injection" for a in data["attacks"])
    assert any(a["attack_type"] == "pii_extraction" for a in data["attacks"])

    # Filter by type
    filtered = client.get("/api/security/attacks?attack_type=jailbreak")
    assert filtered.status_code == 200
    f_data = filtered.json()
    assert f_data["total"] >= 2
    assert all(a["attack_type"] == "jailbreak" for a in f_data["attacks"])


def test_api_security_run_and_latest(api_client):
    """Verify POST /api/security/run and GET /api/security/latest."""
    client, _ = api_client

    # 1. Initially no scan
    empty_resp = client.get("/api/security/latest")
    assert empty_resp.status_code == 200
    assert empty_resp.json()["status"] == "none"

    # 2. Run red team scan with safe model
    run_resp = client.post(
        "/api/security/run",
        json={
            "target_name": "API_Aliged_Target",
            "prompt_override": "You are a customer service rep.",
            "model_simulate": "safe",
        },
    )
    assert run_resp.status_code == 200
    card = run_resp.json()
    assert card["target_name"] == "API_Aliged_Target"
    assert card["total_attacks"] >= 12
    assert card["breaches_detected"] == 0
    assert card["security_grade"] in ["A+", "A"]

    # 3. Verify latest scorecard returns this scan
    latest_resp = client.get("/api/security/latest")
    assert latest_resp.status_code == 200
    l_data = latest_resp.json()
    assert l_data["status"] == "ok"
    assert l_data["scorecard"]["target_name"] == "API_Aliged_Target"

    # 4. List scans
    scans_resp = client.get("/api/security/scans")
    assert scans_resp.status_code == 200
    assert len(scans_resp.json()["scans"]) == 1
