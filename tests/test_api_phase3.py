"""Testing Round 4: Web UI Endpoints for Phase 3 Golden Datasets & Regression Matrix."""

import pytest
from fastapi.testclient import TestClient

import nanotrace
from nanotrace.ui.server import create_app
from nanotrace.eval.golden import GoldenCase, GoldenDatasetManager
from nanotrace.schema.otel import GenAIAttributes


@pytest.fixture
def api_test_client(tmp_path):
    db_file = str(tmp_path / "api_phase3.duckdb")
    tracer = nanotrace.init(storage_path=db_file, buffer_capacity=1000, flush_interval=0.01)

    # Seed a span
    with tracer.span("extract_financials") as sp:
        sp.set_attribute(GenAIAttributes.REQUEST_MODEL, "claude-3-5-sonnet")
        sp.prompt_payload = "Calculate EBITDA margin for FY25."
        sp.completion_payload = "EBITDA margin reached 24.8%."

    tracer.flush()

    # Seed a golden case
    mgr = GoldenDatasetManager(db_path=db_file)
    mgr.save_case(GoldenCase(
        case_id="case_api_1",
        dataset_name="financial_qa",
        name="EBITDA Margin Test",
        input_prompt="Calculate EBITDA margin for FY25.",
        expected_output="EBITDA margin reached 24.8%.",
    ))

    app = create_app(db_path=db_file)
    client = TestClient(app)

    yield client, sp.span_id, db_file

    try:
        tracer.shutdown()
    except Exception:
        pass


def test_api_list_golden_datasets(api_test_client):
    client, span_id, db_file = api_test_client
    resp = client.get("/api/golden/datasets")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    ds = next(d for d in data if d["name"] == "financial_qa")
    assert ds["count"] == 1


def test_api_get_golden_cases(api_test_client):
    client, span_id, db_file = api_test_client
    resp = client.get("/api/golden/cases?dataset=financial_qa")
    assert resp.status_code == 200
    cases = resp.json()
    assert len(cases) == 1
    assert cases[0]["case_id"] == "case_api_1"
    assert cases[0]["name"] == "EBITDA Margin Test"


def test_api_save_golden_case_from_span(api_test_client):
    client, span_id, db_file = api_test_client
    # Save a new golden case using span attributes
    payload = {
        "span_id": span_id,
        "dataset_name": "executive_benchmarks",
        "name": "EBITDA Production Reference",
        "input_prompt": "Calculate EBITDA margin for FY25.",
        "expected_output": "EBITDA margin reached 24.8%.",
        "tags": ["finance", "executive"],
    }
    resp = client.post("/api/golden/save", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "case_id" in data
    new_case_id = data["case_id"]

    # Verify retrieval
    resp2 = client.get("/api/golden/cases?dataset=executive_benchmarks")
    assert resp2.status_code == 200
    retrieved = resp2.json()
    assert any(c["case_id"] == new_case_id for c in retrieved)


def test_api_run_regression_matrix(api_test_client):
    client, span_id, db_file = api_test_client
    req = {
        "dataset_name": "financial_qa",
        "baseline_name": "GPT-4o Baseline",
        "candidate_name": "GPT-4o-Mini Candidate",
        "baseline_system_prompt": "You are a concise financial analyst.",
        "candidate_system_prompt": "You are a precise, cost-optimized financial analyst.",
        "fail_under": 0.50,
    }
    resp = client.post("/api/regression/run", json=req)
    assert resp.status_code == 200
    run_data = resp.json()
    assert "run_id" in run_data
    assert run_data["total_cases"] == 1
    assert "pass_rate" in run_data
    assert "results" in run_data
    assert len(run_data["results"]) == 1

    run_id = run_data["run_id"]

    # Verify history
    history_resp = client.get("/api/regression/runs")
    assert history_resp.status_code == 200
    runs = history_resp.json()
    assert any(r["run_id"] == run_id for r in runs)

    # Verify run detail
    detail_resp = client.get(f"/api/regression/runs/{run_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["run_id"] == run_id
    assert len(detail["results"]) == 1


def test_api_delete_golden_case(api_test_client):
    client, span_id, db_file = api_test_client
    del_resp = client.delete("/api/golden/cases/case_api_1")
    assert del_resp.status_code == 200

    # Ensure list is now empty for financial_qa
    resp = client.get("/api/golden/cases?dataset=financial_qa")
    assert resp.status_code == 200
    assert len(resp.json()) == 0
