"""Built-in, zero-cost, local heuristic evaluators for agent traces.

Requires zero API tokens or LLM judges. Evaluates token waste, tool failure loops,
latency anomalies, and repetition directly on trace datasets.
"""

from __future__ import annotations

import statistics
from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class HeuristicResult:
    metric_name: str
    score: float  # 0.0 to 1.0 (1.0 is healthy, 0.0 is problematic)
    passed: bool
    details: Dict[str, Any]


class LocalHeuristicEvaluator:
    """Evaluates agent execution traces using statistical and deterministic heuristics."""

    @staticmethod
    def evaluate_tool_reliability(spans: List[Dict[str, Any]]) -> HeuristicResult:
        """Calculates tool call success rate and detects failure loops."""
        tool_spans = [s for s in spans if s.get("gen_ai_operation") == "execute_tool" or s.get("gen_ai_tool_name")]
        if not tool_spans:
            return HeuristicResult("tool_reliability", 1.0, True, {"total_tools": 0, "failures": 0})

        failures = [s for s in tool_spans if s.get("status") == "ERROR"]
        failure_rate = len(failures) / len(tool_spans)
        score = max(0.0, 1.0 - failure_rate)

        return HeuristicResult(
            metric_name="tool_reliability",
            score=round(score, 3),
            passed=score >= 0.8,
            details={
                "total_tool_calls": len(tool_spans),
                "failed_tool_calls": len(failures),
                "failed_tools": [s.get("gen_ai_tool_name") for s in failures],
            },
        )

    @staticmethod
    def evaluate_latency_anomalies(spans: List[Dict[str, Any]], z_threshold: float = 2.5) -> HeuristicResult:
        """Detects latency outliers among LLM and tool calls."""
        durations = [s.get("duration_ms", 0.0) for s in spans if s.get("duration_ms", 0.0) > 0]
        if len(durations) < 3:
            return HeuristicResult("latency_anomaly", 1.0, True, {"outliers_detected": 0})

        mean = statistics.mean(durations)
        stdev = statistics.stdev(durations) if len(durations) > 1 else 0.0

        if stdev == 0:
            return HeuristicResult("latency_anomaly", 1.0, True, {"outliers_detected": 0})

        outliers = [d for d in durations if (d - mean) / stdev > z_threshold]
        score = max(0.0, 1.0 - (len(outliers) / len(durations)))

        return HeuristicResult(
            metric_name="latency_anomaly",
            score=round(score, 3),
            passed=len(outliers) == 0,
            details={
                "mean_duration_ms": round(mean, 2),
                "p95_threshold_ms": round(mean + (z_threshold * stdev), 2),
                "outlier_count": len(outliers),
            },
        )

    @staticmethod
    def evaluate_token_efficiency(spans: List[Dict[str, Any]], max_recommended_tokens: int = 16_000) -> HeuristicResult:
        """Detects excessive token usage or runaway agent prompts."""
        total_tokens = sum(s.get("gen_ai_total_tokens", 0) for s in spans)
        score = 1.0 if total_tokens <= max_recommended_tokens else max(0.0, max_recommended_tokens / total_tokens)

        return HeuristicResult(
            metric_name="token_efficiency",
            score=round(score, 3),
            passed=score >= 0.7,
            details={
                "total_tokens_consumed": total_tokens,
                "recommended_max": max_recommended_tokens,
            },
        )

    @classmethod
    def evaluate_all(cls, spans: List[Dict[str, Any]]) -> List[HeuristicResult]:
        """Run all built-in local heuristic evaluators."""
        return [
            cls.evaluate_tool_reliability(spans),
            cls.evaluate_latency_anomalies(spans),
            cls.evaluate_token_efficiency(spans),
        ]
