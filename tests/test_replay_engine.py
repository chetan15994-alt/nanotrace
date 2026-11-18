"""Comprehensive Unit & Functional Tests for Time-Travel Debugger & ReplayEngine."""

import os
import pytest

import nanotrace
from nanotrace.core.replay import ReplayEngine, ForkResult
from nanotrace.exceptions import ReplayError
from nanotrace.schema.otel import GenAIAttributes, GenAIOperation


@pytest.fixture
def replay_setup(tmp_path):
    db_file = str(tmp_path / "replay_test.duckdb")
    tracer = nanotrace.init(storage_path=db_file, buffer_capacity=1000, flush_interval=0.01)

    # Seed an execution lineage: root_agent -> planner -> tool_call
    with tracer.span("root_agent") as root:
        root.set_attribute(GenAIAttributes.REQUEST_MODEL, "gpt-4o")
        root.prompt_payload = "Analyze Q3 revenue report"
        root.completion_payload = "Initiating financial plan"

        with tracer.span("planner_node") as planner:
            planner.set_attribute(GenAIAttributes.REQUEST_MODEL, "gpt-4o")
            planner.prompt_payload = "Break down queries"
            planner.completion_payload = "Plan: 1. Fetch ledger, 2. Compute margin"

            with tracer.span("tool: fetch_ledger") as tool:
                tool.set_attribute(GenAIAttributes.TOOL_NAME, "fetch_ledger")
                tool.prompt_payload = "{'account': 'revenue'}"
                tool.completion_payload = "{'status': 'OK', 'total': 450000}"

    tracer.flush()
    engine = ReplayEngine(db_path=db_file)
    yield engine, tracer, db_file, root.span_id, planner.span_id, tool.span_id
    try:
        tracer.shutdown()
    except Exception:
        pass


def test_replay_get_node_context_success(replay_setup):
    engine, tracer, db_file, root_id, planner_id, tool_id = replay_setup

    ctx = engine.get_node_context(tool_id)
    assert ctx["target_span"]["span_id"] == tool_id
    assert ctx["target_span"]["name"] == "tool: fetch_ledger"
    assert len(ctx["ancestors"]) == 2
    # Ancestors should be root_agent then planner_node
    assert ctx["ancestors"][0]["span_id"] == root_id
    assert ctx["ancestors"][1]["span_id"] == planner_id
    assert ctx["total_trace_spans"] == 3


def test_replay_get_node_context_not_found(replay_setup):
    engine, tracer, db_file, root_id, planner_id, tool_id = replay_setup

    with pytest.raises(ReplayError) as exc_info:
        engine.get_node_context("nonexistent_span_id_12345")
    assert "Span not found" in str(exc_info.value)


def test_replay_fork_and_replay_node(replay_setup):
    engine, tracer, db_file, root_id, planner_id, tool_id = replay_setup

    res = engine.fork_and_replay_node(
        span_id=planner_id,
        prompt="Break down queries with tax deductions included",
        model="claude-3-5-sonnet",
        temperature=0.2,
    )

    assert isinstance(res, ForkResult)
    assert res.original_span_id == planner_id
    assert res.model == "claude-3-5-sonnet"
    assert res.forked_prompt == "Break down queries with tax deductions included"
    assert res.forked_trace_id != res.original_trace_id
    assert res.forked_span_id != planner_id
    assert res.forked_tokens > 0
    assert res.forked_cost_usd >= 0.0

    # Query DuckDB to verify the forked span was written
    forked_rows = engine._get_sink().query(
        f"SELECT * FROM spans WHERE span_id = '{res.forked_span_id}'"
    )
    assert len(forked_rows) == 1
    row = forked_rows[0]
    assert row["name"] == "fork: planner_node"
    assert row["gen_ai_request_model"] == "claude-3-5-sonnet"
    assert "nanotrace.replay.forked" in row["attributes_json"]


def test_replay_fork_with_mock_response_and_diff(replay_setup):
    engine, tracer, db_file, root_id, planner_id, tool_id = replay_setup

    mock_resp = "Plan:\n1. Fetch ledger\n2. Compute margin\n3. Calculate net tax"
    res = engine.fork_and_replay_node(
        span_id=planner_id,
        mock_response=mock_resp,
    )

    assert res.forked_completion == mock_resp
    assert "Calculate net tax" in res.forked_completion
    # Diff summary should exist
    assert res.diff_summary != ""
    assert res.to_dict()["status"] == "OK"
