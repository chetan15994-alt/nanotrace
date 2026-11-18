"""Trace-to-Gold Regression Suite: Automated Prompt & Model A/B Regression Testing Matrix."""

from __future__ import annotations

import difflib
import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable

import duckdb
from nanotrace.eval.golden import GoldenCase, GoldenDatasetManager
from nanotrace.exceptions import NanoTraceError


class RegressionError(NanoTraceError):
    """Raised when regression evaluation fails."""
    pass


def compute_token_jaccard_similarity(text1: str, text2: str) -> float:
    """Zero-dependency, high-speed token Jaccard similarity scorer (0.0 to 1.0)."""
    t1 = set(re.findall(r"\b\w+\b", text1.lower()))
    t2 = set(re.findall(r"\b\w+\b", text2.lower()))
    if not t1 and not t2:
        return 1.0
    if not t1 or not t2:
        return 0.0
    intersection = len(t1 & t2)
    union = len(t1 | t2)
    return round(intersection / union, 4)


def compute_levenshtein_ratio(s1: str, s2: str) -> float:
    """Normalized string similarity based on difflib SequenceMatcher (0.0 to 1.0)."""
    if not s1 and not s2:
        return 1.0
    return round(difflib.SequenceMatcher(None, s1, s2).ratio(), 4)


@dataclass
class RegressionCaseResult:
    """Per-test-case comparison telemetry between baseline and candidate executions."""
    case_id: str
    case_name: str
    input_prompt: str
    expected_output: str
    baseline_output: str
    candidate_output: str
    baseline_duration_ms: float
    candidate_duration_ms: float
    duration_delta_pct: float
    baseline_tokens: int
    candidate_tokens: int
    tokens_delta_pct: float
    baseline_cost_usd: float
    candidate_cost_usd: float
    cost_delta_pct: float
    baseline_score: float
    candidate_score: float
    score_delta: float
    status: str  # IMPROVED, REGRESSED, UNCHANGED
    diff_summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_name": self.case_name,
            "input_prompt": self.input_prompt,
            "expected_output": self.expected_output,
            "baseline_output": self.baseline_output,
            "candidate_output": self.candidate_output,
            "baseline_duration_ms": self.baseline_duration_ms,
            "candidate_duration_ms": self.candidate_duration_ms,
            "duration_delta_pct": self.duration_delta_pct,
            "baseline_tokens": self.baseline_tokens,
            "candidate_tokens": self.candidate_tokens,
            "tokens_delta_pct": self.tokens_delta_pct,
            "baseline_cost_usd": self.baseline_cost_usd,
            "candidate_cost_usd": self.candidate_cost_usd,
            "cost_delta_pct": self.cost_delta_pct,
            "baseline_score": self.baseline_score,
            "candidate_score": self.candidate_score,
            "score_delta": self.score_delta,
            "status": self.status,
            "diff_summary": self.diff_summary,
        }


@dataclass
class RegressionRun:
    """Summary of a full regression suite matrix run."""
    run_id: str
    dataset_name: str
    baseline_name: str
    candidate_name: str
    total_cases: int
    improved_count: int
    regressed_count: int
    unchanged_count: int
    avg_score_baseline: float
    avg_score_candidate: float
    score_delta: float
    avg_duration_delta_pct: float
    avg_cost_delta_pct: float
    pass_rate: float
    passed: bool
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    results: List[RegressionCaseResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dataset_name": self.dataset_name,
            "baseline_name": self.baseline_name,
            "candidate_name": self.candidate_name,
            "total_cases": self.total_cases,
            "improved_count": self.improved_count,
            "regressed_count": self.regressed_count,
            "unchanged_count": self.unchanged_count,
            "avg_score_baseline": self.avg_score_baseline,
            "avg_score_candidate": self.avg_score_candidate,
            "score_delta": self.score_delta,
            "avg_duration_delta_pct": self.avg_duration_delta_pct,
            "avg_cost_delta_pct": self.avg_cost_delta_pct,
            "pass_rate": self.pass_rate,
            "passed": self.passed,
            "created_at": self.created_at,
            "results": [r.to_dict() for r in self.results],
        }


class RegressionEngine:
    """Executes multi-threaded regression comparisons between Prompt A and Prompt B."""

    def __init__(self, db_path: str = "./.traces/nanotrace.duckdb"):
        self.db_path = db_path
        self.dataset_manager = GoldenDatasetManager(db_path=self.db_path)
        self._ensure_schema()

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.db_path)

    def _ensure_schema(self) -> None:
        """Create regression_runs and regression_results tables."""
        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS regression_runs (
                    run_id VARCHAR PRIMARY KEY,
                    dataset_name VARCHAR,
                    baseline_name VARCHAR,
                    candidate_name VARCHAR,
                    total_cases INTEGER,
                    improved_count INTEGER,
                    regressed_count INTEGER,
                    unchanged_count INTEGER,
                    avg_score_baseline DOUBLE,
                    avg_score_candidate DOUBLE,
                    score_delta DOUBLE,
                    avg_duration_delta_pct DOUBLE,
                    avg_cost_delta_pct DOUBLE,
                    pass_rate DOUBLE,
                    passed BOOLEAN,
                    summary_json VARCHAR,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS regression_results (
                    result_id VARCHAR PRIMARY KEY,
                    run_id VARCHAR,
                    case_id VARCHAR,
                    case_name VARCHAR,
                    baseline_output VARCHAR,
                    candidate_output VARCHAR,
                    baseline_duration_ms DOUBLE,
                    candidate_duration_ms DOUBLE,
                    duration_delta_pct DOUBLE,
                    baseline_tokens INTEGER,
                    candidate_tokens INTEGER,
                    tokens_delta_pct DOUBLE,
                    baseline_cost_usd DOUBLE,
                    candidate_cost_usd DOUBLE,
                    cost_delta_pct DOUBLE,
                    baseline_score DOUBLE,
                    candidate_score DOUBLE,
                    score_delta DOUBLE,
                    status VARCHAR,
                    diff_summary VARCHAR
                );
            """)
        finally:
            conn.close()

    def evaluate_single_case(
        self,
        case: GoldenCase,
        baseline_fn: Callable[[str], str],
        candidate_fn: Callable[[str], str],
        scorer: Optional[Callable[[str, str], float]] = None,
    ) -> RegressionCaseResult:
        """Run baseline and candidate against one test case, measuring duration, tokens, and quality score."""
        eval_score = scorer or compute_levenshtein_ratio

        # 1. Execute Baseline
        t0 = time.perf_counter()
        base_out = str(baseline_fn(case.input_prompt) or "")
        dur_base = max(0.1, (time.perf_counter() - t0) * 1000.0)

        # 2. Execute Candidate
        t1 = time.perf_counter()
        cand_out = str(candidate_fn(case.input_prompt) or "")
        dur_cand = max(0.1, (time.perf_counter() - t1) * 1000.0)

        # Estimate tokens & costs
        base_tokens = max(5, len(base_out.split()) * 2)
        cand_tokens = max(5, len(cand_out.split()) * 2)
        base_cost = round((base_tokens / 1_000_000.0) * 2.50, 6)
        cand_cost = round((cand_tokens / 1_000_000.0) * 0.15, 6)

        # Score against expected output
        target = case.expected_output or case.input_prompt
        score_base = eval_score(target, base_out)
        score_cand = eval_score(target, cand_out)

        dur_delta_pct = round(((dur_cand - dur_base) / dur_base) * 100.0, 2)
        tok_delta_pct = round(((cand_tokens - base_tokens) / base_tokens) * 100.0, 2)
        cost_delta_pct = round(((cand_cost - base_cost) / base_cost) * 100.0, 2) if base_cost > 0 else 0.0
        score_delta = round(score_cand - score_base, 4)

        # Determine Status
        if score_delta >= 0.02 or (score_delta >= -0.08 and cost_delta_pct <= -15.0):
            status = "IMPROVED"
        elif score_delta <= -0.10 or cost_delta_pct >= 30.0:
            status = "REGRESSED"
        else:
            status = "UNCHANGED"

        # Diff summary
        diff_lines = list(difflib.unified_diff(
            base_out.splitlines(keepends=True),
            cand_out.splitlines(keepends=True),
            fromfile="baseline",
            tofile="candidate",
            n=2,
        ))
        diff_summary = "".join(diff_lines) or "Completions identical."

        return RegressionCaseResult(
            case_id=case.case_id,
            case_name=case.name,
            input_prompt=case.input_prompt,
            expected_output=case.expected_output,
            baseline_output=base_out,
            candidate_output=cand_out,
            baseline_duration_ms=round(dur_base, 2),
            candidate_duration_ms=round(dur_cand, 2),
            duration_delta_pct=dur_delta_pct,
            baseline_tokens=base_tokens,
            candidate_tokens=cand_tokens,
            tokens_delta_pct=tok_delta_pct,
            baseline_cost_usd=base_cost,
            candidate_cost_usd=cand_cost,
            cost_delta_pct=cost_delta_pct,
            baseline_score=round(score_base, 4),
            candidate_score=round(score_cand, 4),
            score_delta=score_delta,
            status=status,
            diff_summary=diff_summary,
        )

    def run_matrix(
        self,
        dataset_name: str = "default",
        candidate_fn: Optional[Callable[[str], str]] = None,
        baseline_fn: Optional[Callable[[str], str]] = None,
        candidate_name: str = "Candidate (v2.0)",
        baseline_name: str = "Baseline (v1.0)",
        scorer: Optional[Callable[[str, str], float]] = None,
        fail_under: float = 0.80,
        min_score: Optional[float] = None,
        max_workers: int = 4,
    ) -> RegressionRun:
        """Run parallel A/B regression test matrix across all cases in a golden dataset."""
        cases = self.dataset_manager.get_dataset(dataset_name)
        if not cases:
            raise RegressionError(f"Golden dataset '{dataset_name}' contains no test cases.")

        # Default simulated functions if none provided
        if not baseline_fn:
            baseline_fn = lambda prompt: f"[Baseline Response]: Analyzed query '{prompt}'. Grounded answer."
        if not candidate_fn:
            candidate_fn = lambda prompt: f"[Optimized Response]: Concise analysis for '{prompt}'."

        results: List[RegressionCaseResult] = []
        with ThreadPoolExecutor(max_workers=min(max_workers, len(cases))) as executor:
            future_to_case = {
                executor.submit(self.evaluate_single_case, c, baseline_fn, candidate_fn, scorer): c
                for c in cases
            }
            for future in as_completed(future_to_case):
                results.append(future.result())

        # Sort results deterministically by case_id
        results.sort(key=lambda r: r.case_id)

        # Aggregate metrics
        improved = sum(1 for r in results if r.status == "IMPROVED")
        regressed = sum(1 for r in results if r.status == "REGRESSED")
        unchanged = sum(1 for r in results if r.status == "UNCHANGED")
        total = len(results)

        avg_base_score = round(sum(r.baseline_score for r in results) / total, 4)
        avg_cand_score = round(sum(r.candidate_score for r in results) / total, 4)
        score_delta = round(avg_cand_score - avg_base_score, 4)

        avg_dur_delta = round(sum(r.duration_delta_pct for r in results) / total, 2)
        avg_cost_delta = round(sum(r.cost_delta_pct for r in results) / total, 2)

        pass_rate = round((improved + unchanged) / total, 4)
        passed = (pass_rate >= fail_under)
        if min_score is not None:
            passed = passed and (avg_cand_score >= min_score)

        run_id = f"reg_{uuid.uuid4().hex[:12]}"
        run = RegressionRun(
            run_id=run_id,
            dataset_name=dataset_name,
            baseline_name=baseline_name,
            candidate_name=candidate_name,
            total_cases=total,
            improved_count=improved,
            regressed_count=regressed,
            unchanged_count=unchanged,
            avg_score_baseline=avg_base_score,
            avg_score_candidate=avg_cand_score,
            score_delta=score_delta,
            avg_duration_delta_pct=avg_dur_delta,
            avg_cost_delta_pct=avg_cost_delta,
            pass_rate=pass_rate,
            passed=passed,
            results=results,
        )

        self._save_run(run)
        return run

    def _save_run(self, run: RegressionRun) -> None:
        """Persist RegressionRun and its case results into DuckDB."""
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT INTO regression_runs (
                    run_id, dataset_name, baseline_name, candidate_name,
                    total_cases, improved_count, regressed_count, unchanged_count,
                    avg_score_baseline, avg_score_candidate, score_delta,
                    avg_duration_delta_pct, avg_cost_delta_pct, pass_rate, passed,
                    summary_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                run.run_id,
                run.dataset_name,
                run.baseline_name,
                run.candidate_name,
                run.total_cases,
                run.improved_count,
                run.regressed_count,
                run.unchanged_count,
                run.avg_score_baseline,
                run.avg_score_candidate,
                run.score_delta,
                run.avg_duration_delta_pct,
                run.avg_cost_delta_pct,
                run.pass_rate,
                run.passed,
                json.dumps(run.to_dict(), default=str),
                run.created_at,
            ])

            for r in run.results:
                res_id = f"res_{uuid.uuid4().hex[:12]}"
                conn.execute("""
                    INSERT INTO regression_results (
                        result_id, run_id, case_id, case_name,
                        baseline_output, candidate_output,
                        baseline_duration_ms, candidate_duration_ms, duration_delta_pct,
                        baseline_tokens, candidate_tokens, tokens_delta_pct,
                        baseline_cost_usd, candidate_cost_usd, cost_delta_pct,
                        baseline_score, candidate_score, score_delta, status, diff_summary
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    res_id,
                    run.run_id,
                    r.case_id,
                    r.case_name,
                    r.baseline_output,
                    r.candidate_output,
                    r.baseline_duration_ms,
                    r.candidate_duration_ms,
                    r.duration_delta_pct,
                    r.baseline_tokens,
                    r.candidate_tokens,
                    r.tokens_delta_pct,
                    r.baseline_cost_usd,
                    r.candidate_cost_usd,
                    r.cost_delta_pct,
                    r.baseline_score,
                    r.candidate_score,
                    r.score_delta,
                    r.status,
                    r.diff_summary,
                ])
        finally:
            conn.close()

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List past regression matrix runs."""
        conn = self._get_connection()
        try:
            rows = conn.execute("""
                SELECT 
                    run_id, dataset_name, baseline_name, candidate_name,
                    total_cases, improved_count, regressed_count, unchanged_count,
                    avg_score_baseline, avg_score_candidate, score_delta,
                    pass_rate, passed, created_at
                FROM regression_runs
                ORDER BY created_at DESC
                LIMIT ?
            """, [limit]).fetchall()
            cols = [
                "run_id", "dataset_name", "baseline_name", "candidate_name",
                "total_cases", "improved_count", "regressed_count", "unchanged_count",
                "avg_score_baseline", "avg_score_candidate", "score_delta",
                "pass_rate", "passed", "created_at"
            ]
            return [dict(zip(cols, r)) for r in rows]
        finally:
            conn.close()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a full regression run and its test case results."""
        conn = self._get_connection()
        try:
            runs = conn.execute("SELECT summary_json FROM regression_runs WHERE run_id = ?", [run_id]).fetchall()
            if not runs:
                return None
            return json.loads(runs[0][0])
        finally:
            conn.close()
