import json
import time
import threading
import pytest
from nanotrace.core.healer import TraceHealer
from nanotrace.schema.otel import GenAIAttributes, StatusCode, SpanKind
from nanotrace.storage.duckdb_sink import DuckDBSink


def test_healer_degenerate_inputs():
    healer = TraceHealer()
    assert healer.parse_and_heal(None) == []
    assert healer.parse_and_heal("") == []
    assert healer.parse_and_heal({}) == []
    assert healer.parse_and_heal([]) == []

    # Integer or boolean passed as raw
    spans_int = healer.parse_and_heal(12345)
    assert len(spans_int) == 1
    assert "12345" in str(spans_int[0].attributes)


def test_healer_malformed_json_fallback():
    healer = TraceHealer()
    # Unclosed JSON bracket
    broken_json = '{"agent": "BrokenAgent", "task": "something broken...'
    spans = healer.parse_and_heal(broken_json)
    assert len(spans) == 1
    assert spans[0].status == StatusCode.OK


def test_healer_stdout_react_parsing():
    healer = TraceHealer()
    stdout_log = """
    Thought: I need to check the user account balance before proceeding.
    Action: query_account_balance
    Action Input: {"account_id": "ACC-9982"}
    Observation: {"balance": 4500.50, "currency": "USD"}
    Thought: The balance is sufficient. Generating final transfer approval.
    """
    spans = healer.parse_and_heal(stdout_log)
    assert len(spans) >= 2
    tool_span = next((s for s in spans if "query_account_balance" in s.name), None)
    assert tool_span is not None
    assert tool_span.attributes.get(GenAIAttributes.TOOL_NAME) == "query_account_balance"
    assert "4500.50" in str(tool_span.attributes.get(GenAIAttributes.TOOL_OUTPUT))


def test_healer_deep_tree_flattening():
    healer = TraceHealer()
    # Construct a 15-level deeply nested tree
    current = {"name": "level_15", "run_type": "chain"}
    for i in range(14, 0, -1):
        current = {"name": f"level_{i}", "run_type": "chain", "child_runs": [current]}

    spans = healer.parse_and_heal(current)
    assert len(spans) == 15
    # Verify child-parent chain is fully intact
    for i in range(1, 15):
        assert spans[i].parent_span_id == spans[i - 1].span_id


def test_healer_large_batch_and_concurrency():
    healer = TraceHealer()
    sink = DuckDBSink(db_path=":memory:")

    def worker_ingest(worker_id: int):
        for i in range(50):
            payload = {
                "agent": f"Worker_{worker_id}_Agent",
                "task": f"Task number {i}",
                "output": f"Result {i}",
                "usage": {"prompt_tokens": 100 + i, "completion_tokens": 20 + i},
            }
            spans = healer.parse_and_heal(payload)
            sink.write_spans(spans)

    threads = []
    for wid in range(5):
        t = threading.Thread(target=worker_ingest, args=(wid,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # 5 workers * 50 payloads = 250 spans
    stats = sink.get_stats()
    assert stats["total_spans"] == 250
    assert stats["total_tokens"] > 0
    sink.close()
