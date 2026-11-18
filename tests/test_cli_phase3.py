"""Testing Round 3: CLI Regression Suite & Golden Dataset Tests."""

import os
import pytest
from typer.testing import CliRunner

import nanotrace
from nanotrace.cli import app
from nanotrace.eval.golden import GoldenCase, GoldenDatasetManager
from nanotrace.schema.otel import GenAIAttributes

runner = CliRunner()


@pytest.fixture
def cli_test_env(tmp_path):
    db_file = str(tmp_path / "cli_phase3.duckdb")
    tracer = nanotrace.init(storage_path=db_file, buffer_capacity=1000, flush_interval=0.01)

    # Seed an execution trace
    with tracer.span("extract_metrics") as sp:
        sp.set_attribute(GenAIAttributes.REQUEST_MODEL, "gpt-4o")
        sp.prompt_payload = "Query: What is the ARR for Q2?"
        sp.completion_payload = "ARR reached $42M with net retention of 118%."

    tracer.flush()

    # Seed 2 golden test cases
    mgr = GoldenDatasetManager(db_path=db_file)
    mgr.save_case(GoldenCase(
        case_id="tc_01",
        dataset_name="metrics_suite",
        name="ARR Metric Check",
        input_prompt="Query: What is the ARR for Q2?",
        expected_output="ARR reached $42M with net retention of 118%.",
    ))
    mgr.save_case(GoldenCase(
        case_id="tc_02",
        dataset_name="metrics_suite",
        name="Churn Rate Check",
        input_prompt="Query: What is the gross revenue churn?",
        expected_output="Gross churn was 1.2% annualized.",
    ))

    yield db_file, sp.trace_id, sp.span_id
    try:
        tracer.shutdown()
    except Exception:
        pass


def test_cli_golden_list(cli_test_env):
    db_file, trace_id, span_id = cli_test_env
    res = runner.invoke(app, ["golden", "list", "--db", db_file])
    assert res.exit_code == 0
    assert "metrics_suite" in res.stdout
    assert "2" in res.stdout  # Case count


def test_cli_golden_save(cli_test_env):
    db_file, trace_id, span_id = cli_test_env
    res = runner.invoke(app, [
        "golden", "save",
        "--trace-id", trace_id,
        "--span-id", span_id,
        "--name", "Extracted ARR Test Case",
        "--dataset", "extracted_suite",
        "--db", db_file,
    ])
    assert res.exit_code == 0
    assert "Saved golden test case" in res.stdout
    assert "extracted_suite" in res.stdout

    # Verify via manager
    mgr = GoldenDatasetManager(db_path=db_file)
    cases = mgr.get_dataset("extracted_suite")
    assert len(cases) == 1
    assert cases[0].name == "Extracted ARR Test Case"


def test_cli_golden_export(cli_test_env, tmp_path):
    db_file, trace_id, span_id = cli_test_env
    out_file = str(tmp_path / "exported_cases.jsonl")
    res = runner.invoke(app, [
        "golden", "export",
        "--dataset", "metrics_suite",
        "--output", out_file,
        "--db", db_file,
    ])
    assert res.exit_code == 0
    assert "Exported 2 golden test cases" in res.stdout
    assert os.path.exists(out_file)


def test_cli_test_quality_gate_passed(cli_test_env):
    db_file, trace_id, span_id = cli_test_env
    # Low threshold should pass
    res = runner.invoke(app, [
        "test",
        "--dataset", "metrics_suite",
        "--fail-under", "0.10",
        "--db", db_file,
    ])
    assert res.exit_code == 0
    assert "QUALITY GATE PASSED" in res.stdout
    assert "metrics_suite" in res.stdout


def test_cli_test_quality_gate_breached(cli_test_env):
    db_file, trace_id, span_id = cli_test_env
    # An impossible pass rate threshold of 1.05 must breach the quality gate
    res = runner.invoke(app, [
        "test",
        "--dataset", "metrics_suite",
        "--fail-under", "1.05",
        "--db", db_file,
    ])
    assert res.exit_code == 1
    assert "QUALITY GATE BREACHED" in res.stdout
