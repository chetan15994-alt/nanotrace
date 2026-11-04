"""Unified Trace-to-Eval bridge for NanoTrace."""

from __future__ import annotations

from typing import List, Dict, Any, Optional

from nanotrace.eval.deepeval import trace_records_to_deepeval, LLMTestCase
from nanotrace.eval.ragas import trace_records_to_ragas, EvaluationDataset
from nanotrace.eval.heuristics import LocalHeuristicEvaluator, HeuristicResult
from nanotrace.storage.duckdb_sink import DuckDBSink


class TraceDataset:
    """A collection of agent trace records ready for evaluation and analysis."""

    def __init__(self, records: List[Dict[str, Any]]):
        self.records = records

    def __len__(self) -> int:
        return len(self.records)

    def to_deepeval(self) -> List[LLMTestCase]:
        """Convert traces directly to DeepEval LLMTestCase objects."""
        return trace_records_to_deepeval(self.records)

    def to_ragas(self) -> EvaluationDataset:
        """Convert traces directly to Ragas EvaluationDataset."""
        return trace_records_to_ragas(self.records)

    def run_heuristics(self) -> List[HeuristicResult]:
        """Run zero-cost local evaluation heuristics across all spans."""
        return LocalHeuristicEvaluator.evaluate_all(self.records)

    def to_dicts(self) -> List[Dict[str, Any]]:
        """Return raw span records as dictionaries."""
        return self.records


def load_traces(
    db_path: str = "./.traces/nanotrace.duckdb",
    sql_filter: Optional[str] = None,
    limit: int = 100,
) -> TraceDataset:
    """Load traces from a DuckDB database into an evaluable TraceDataset."""
    sink = DuckDBSink(db_path=db_path)
    try:
        sql = "SELECT * FROM spans"
        if sql_filter:
            sql += f" WHERE {sql_filter}"
        sql += f" ORDER BY start_time_ns DESC LIMIT {limit};"
        records = sink.query(sql)
        return TraceDataset(records)
    finally:
        sink.close()
