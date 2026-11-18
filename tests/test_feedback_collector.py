"""Testing Round 2: Feedback Collector, Sentiment Analytics & Trace Association."""

import pytest
from nanotrace.exceptions import FeedbackError
from nanotrace.feedback.models import FeedbackEntry
from nanotrace.feedback.collector import FeedbackCollector


def test_feedback_entry_serialization():
    """Verify FeedbackEntry model serialization and default values."""
    entry = FeedbackEntry(
        trace_id="trace_abc123",
        score=1.0,
        comment="Accurate calculation and very fast response.",
        user_id="user_fin_99",
        metadata={"client": "web", "latency_perception": "instant"},
    )
    assert entry.feedback_id.startswith("fb_")
    d = entry.to_dict()
    assert d["score"] == 1.0
    assert d["user_id"] == "user_fin_99"

    reconstructed = FeedbackEntry.from_dict(d)
    assert reconstructed.trace_id == "trace_abc123"
    assert reconstructed.metadata["client"] == "web"


def test_feedback_collector_crud_and_trace_association(tmp_path):
    """Verify recording and querying feedback for specific traces in DuckDB."""
    db_file = str(tmp_path / "feedback_test.duckdb")
    collector = FeedbackCollector(db_path=db_file)

    # 1. Record feedback on trace A
    e1 = collector.record(
        trace_id="trace_001",
        score=1.0,
        comment="Great answer!",
        user_id="alice",
    )
    assert e1.score == 1.0

    # 2. Record feedback on trace B
    e2 = collector.record(
        trace_id="trace_002",
        score=-1.0,
        comment="Hallucinated order number",
        user_id="bob",
    )
    assert e2.score == -1.0

    # 3. Query for trace A
    t1_feedback = collector.get_for_trace("trace_001")
    assert len(t1_feedback) == 1
    assert t1_feedback[0].comment == "Great answer!"

    # 4. List all feedback
    all_fb = collector.list_feedback()
    assert len(all_fb) == 2


def test_feedback_stats_and_net_sentiment(tmp_path):
    """Verify aggregate sentiment percentage calculation."""
    db_file = str(tmp_path / "feedback_stats.duckdb")
    collector = FeedbackCollector(db_path=db_file)

    # Record 3 positive, 1 negative, 1 neutral
    collector.record(trace_id="t1", score=1.0)
    collector.record(trace_id="t2", score=1.0)
    collector.record(trace_id="t3", score=1.0)
    collector.record(trace_id="t4", score=-1.0)
    collector.record(trace_id="t5", score=0.0)

    stats = collector.get_stats()
    assert stats["total_feedback"] == 5
    assert stats["positive_count"] == 3
    assert stats["negative_count"] == 1
    assert stats["neutral_count"] == 1
    # Net sentiment: (3 - 1) / 5 = +40.0%
    assert stats["net_sentiment_pct"] == 40.0
    assert stats["average_score"] == 0.4


def test_feedback_recommended_golden_traces(tmp_path):
    """Verify traces with positive sentiment are flagged for golden evaluation suites."""
    db_file = str(tmp_path / "feedback_golden.duckdb")
    collector = FeedbackCollector(db_path=db_file)

    collector.record(trace_id="trace_good_1", score=1.0)
    collector.record(trace_id="trace_good_2", score=0.8)
    collector.record(trace_id="trace_bad_1", score=-1.0)

    recommended = collector.get_recommended_golden_traces(min_score=0.5)
    assert len(recommended) == 2
    assert "trace_good_1" in recommended
    assert "trace_good_2" in recommended
    assert "trace_bad_1" not in recommended


def test_feedback_collector_empty_trace_validation(tmp_path):
    """Verify FeedbackError is raised when trace_id is missing."""
    db_file = str(tmp_path / "feedback_err.duckdb")
    collector = FeedbackCollector(db_path=db_file)

    with pytest.raises(FeedbackError, match="trace_id is required"):
        collector.record(trace_id="", score=1.0)
