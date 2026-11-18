"""Testing Round 1: Unit & Architectural Decoupling Tests for Golden Datasets."""

import os
import json
import pytest

import nanotrace
from nanotrace.eval.golden import GoldenCase, GoldenDatasetManager, GoldenDatasetError
from nanotrace.schema.otel import GenAIAttributes


@pytest.fixture
def isolated_duckdb(tmp_path):
    db_file = str(tmp_path / "golden_test.duckdb")
    tracer = nanotrace.init(storage_path=db_file, buffer_capacity=1000, flush_interval=0.01)

    # Seed a trace with prompt and completion
    with tracer.span("agent_step") as sp:
        sp.set_attribute(GenAIAttributes.REQUEST_MODEL, "gpt-4o")
        sp.prompt_payload = "Summarize Q3 financial results for Apple Inc."
        sp.completion_payload = "Apple reported Q3 revenue of $85.8B, up 5% YoY, with Services hitting all-time high."

    tracer.flush()
    yield db_file, sp.trace_id, sp.span_id
    try:
        tracer.shutdown()
    except Exception:
        pass


def test_gold_case_model_serialization():
    case = GoldenCase(
        case_id="gold_test_01",
        dataset_name="finance",
        name="Q3 Revenue Query",
        input_prompt="What is Apple Q3 revenue?",
        expected_output="$85.8B",
        context_chunks=["Apple 10-Q filing"],
        metadata={"priority": "high"},
    )
    d = case.to_dict()
    assert d["case_id"] == "gold_test_01"
    assert d["dataset_name"] == "finance"
    assert d["expected_output"] == "$85.8B"

    rebuilt = GoldenCase.from_dict(d)
    assert rebuilt.case_id == case.case_id
    assert rebuilt.context_chunks == ["Apple 10-Q filing"]
    assert rebuilt.metadata["priority"] == "high"


def test_golden_dataset_manager_crud(isolated_duckdb):
    db_file, trace_id, span_id = isolated_duckdb
    mgr = GoldenDatasetManager(db_path=db_file)

    # 1. Create and save case manually
    c1 = GoldenCase(
        case_id="case_101",
        dataset_name="support",
        name="Password Reset",
        input_prompt="How do I reset my password?",
        expected_output="Click 'Forgot Password' on the login screen.",
    )
    mgr.save_case(c1)

    # 2. Extract case directly from recorded trace
    c2 = mgr.create_case_from_trace(
        trace_id=trace_id,
        span_id=span_id,
        name="Apple Revenue Extraction",
        dataset_name="finance",
    )
    assert c2.case_id.startswith("gold_")
    assert "Summarize Q3 financial results" in c2.input_prompt
    assert "$85.8B" in c2.expected_output

    # 3. List datasets
    datasets = mgr.list_datasets()
    assert len(datasets) == 2
    names = [d["dataset_name"] for d in datasets]
    assert "support" in names and "finance" in names

    # 4. Fetch cases
    support_cases = mgr.get_dataset("support")
    assert len(support_cases) == 1
    assert support_cases[0].case_id == "case_101"

    # 5. Delete case
    mgr.delete_case("case_101")
    assert len(mgr.get_dataset("support")) == 0


def test_golden_dataset_jsonl_export_and_import(isolated_duckdb, tmp_path):
    db_file, trace_id, span_id = isolated_duckdb
    mgr = GoldenDatasetManager(db_path=db_file)

    mgr.save_case(GoldenCase(
        case_id="c1",
        dataset_name="export_test",
        name="Test 1",
        input_prompt="Input 1",
        expected_output="Output 1",
    ))
    mgr.save_case(GoldenCase(
        case_id="c2",
        dataset_name="export_test",
        name="Test 2",
        input_prompt="Input 2",
        expected_output="Output 2",
    ))

    export_path = str(tmp_path / "exported.jsonl")
    count = mgr.export_jsonl("export_test", export_path)
    assert count == 2
    assert os.path.exists(export_path)

    # Import into a new dataset
    imported_count = mgr.import_jsonl("imported_test", export_path)
    assert imported_count == 2
    imported_cases = mgr.get_dataset("imported_test")
    assert len(imported_cases) == 2
    assert imported_cases[0].input_prompt in ["Input 1", "Input 2"]


def test_architectural_decoupling_zero_tracer_dependency(tmp_path):
    """Verify that GoldenDatasetManager works completely standalone without NanoTracer active."""
    standalone_db = str(tmp_path / "standalone_pure.duckdb")
    mgr = GoldenDatasetManager(db_path=standalone_db)

    # Should initialize its own schema cleanly
    datasets = mgr.list_datasets()
    assert datasets == []

    mgr.save_case(GoldenCase(
        case_id="gold_p1",
        dataset_name="unit_suite",
        name="Isolated Unit Case",
        input_prompt="Pure function test",
        expected_output="Return True",
    ))
    assert len(mgr.get_dataset("unit_suite")) == 1
