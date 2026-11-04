"""Automated integration tests for the showcase agents and pipeline validator."""

import pytest
import duckdb
from showcase._simulator import estimate_tokens, compute_cost, mock_llm_call, mock_tool_call
from showcase.run_all_and_validate import validate_telemetry_pipeline, DB_PATH
import os


def test_simulator_primitives():
    tokens = estimate_tokens("Hello world this is a test")
    assert tokens > 0

    cost = compute_cost("gpt-4o", 1000, 500)
    assert cost > 0.0

    res = mock_llm_call(
        model="gpt-4o-mini",
        system_prompt="Test",
        user_message="Ping",
        response="Pong",
    )
    assert res == "Pong"

    tool_res = mock_tool_call("calc", {"a": 1}, 2)
    assert tool_res == 2


def test_showcase_duckdb_integrity():
    # Verify that the generated showcase database contains the expected traces
    if not os.path.exists(DB_PATH):
        from showcase.run_all_and_validate import run_full_suite
        run_full_suite()

    conn = duckdb.connect(DB_PATH)
    try:
        count = conn.execute("SELECT count(*) FROM spans").fetchone()[0]
        assert count >= 200

        # Check for multiple providers
        providers = [r[0] for r in conn.execute("SELECT DISTINCT gen_ai_system FROM spans WHERE gen_ai_system != ''").fetchall()]
        assert "openai" in providers
        assert "anthropic" in providers
        assert "google" in providers
    finally:
        conn.close()
