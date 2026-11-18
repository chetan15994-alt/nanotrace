"""Testing Round 2: Concurrency & Scoring Tests for Regression Matrix Engine."""

import os
import pytest

from nanotrace.eval.golden import GoldenCase, GoldenDatasetManager
from nanotrace.eval.regression import (
    RegressionEngine,
    RegressionRun,
    RegressionCaseResult,
    RegressionError,
    compute_token_jaccard_similarity,
    compute_levenshtein_ratio,
)


@pytest.fixture
def regression_setup(tmp_path):
    db_file = str(tmp_path / "reg_test.duckdb")
    mgr = GoldenDatasetManager(db_path=db_file)

    # Seed 5 golden cases
    for i in range(5):
        mgr.save_case(GoldenCase(
            case_id=f"case_{i:02d}",
            dataset_name="qa_eval",
            name=f"Test Case {i}",
            input_prompt=f"Question number {i}: What is the capital of country_{i}?",
            expected_output=f"The capital of country_{i} is City_{i}.",
        ))

    engine = RegressionEngine(db_path=db_file)
    yield engine, db_file


def test_similarity_scorers():
    s1 = "The capital of France is Paris."
    s2 = "The capital of France is Paris."
    assert compute_token_jaccard_similarity(s1, s2) == 1.0
    assert compute_levenshtein_ratio(s1, s2) == 1.0

    s3 = "The capital of France is Paris city."
    assert compute_token_jaccard_similarity(s1, s3) >= 0.7
    assert compute_levenshtein_ratio(s1, s3) > 0.8

    s4 = "Dolphins swim quickly underwater."
    assert compute_token_jaccard_similarity(s1, s4) == 0.0


def test_evaluate_single_case(regression_setup):
    engine, db_file = regression_setup
    case = GoldenCase(
        case_id="c_single",
        dataset_name="demo",
        name="Single Case",
        input_prompt="Translate hello to French",
        expected_output="Bonjour",
    )

    # Baseline gives wrong/verbose answer
    baseline_fn = lambda p: "Hello in French is formally translated as Bonjour or Salut depending on context."
    # Candidate gives exact concise answer
    candidate_fn = lambda p: "Bonjour"

    res = engine.evaluate_single_case(case, baseline_fn, candidate_fn)
    assert isinstance(res, RegressionCaseResult)
    assert res.candidate_output == "Bonjour"
    assert res.candidate_score > res.baseline_score
    assert res.status == "IMPROVED"
    assert res.diff_summary != ""


def test_run_matrix_parallel_execution(regression_setup):
    engine, db_file = regression_setup

    def baseline_model(p: str) -> str:
        # Generic verbose baseline
        return f"Regarding '{p}', the historical context provides multiple facets..."

    def candidate_model(p: str) -> str:
        # Improved direct candidate matching expected format
        q_num = p.split(":")[0].replace("Question number ", "").strip()
        return f"The capital of country_{q_num} is City_{q_num}."

    run = engine.run_matrix(
        dataset_name="qa_eval",
        baseline_fn=baseline_model,
        candidate_fn=candidate_model,
        candidate_name="Candidate (Concise Model)",
        baseline_name="Baseline (Legacy Model)",
        fail_under=0.70,
        max_workers=4,
    )

    assert isinstance(run, RegressionRun)
    assert run.total_cases == 5
    assert run.improved_count >= 4
    assert run.avg_score_candidate > run.avg_score_baseline
    assert run.passed is True
    assert run.pass_rate >= 0.80

    # Verify DuckDB persistence
    saved_run = engine.get_run(run.run_id)
    assert saved_run is not None
    assert saved_run["run_id"] == run.run_id
    assert len(saved_run["results"]) == 5

    past_runs = engine.list_runs()
    assert len(past_runs) >= 1
    assert past_runs[0]["run_id"] == run.run_id


def test_run_matrix_empty_dataset_raises(regression_setup):
    engine, db_file = regression_setup

    with pytest.raises(RegressionError) as exc_info:
        engine.run_matrix(dataset_name="nonexistent_dataset")
    assert "contains no test cases" in str(exc_info.value)
