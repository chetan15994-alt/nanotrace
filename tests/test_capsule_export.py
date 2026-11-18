"""Unit and functional tests for NanoTrace Standalone HTML Capsule generator."""

import os
import json
import tempfile
import pytest

from nanotrace.core.span import Span
from nanotrace.storage.duckdb_sink import DuckDBSink
from nanotrace.export.capsule import generate_trace_capsule, export_trace_capsule


def test_generate_trace_capsule_structure():
    spans = [
        {
            "trace_id": "0123456789abcdef0123456789abcdef",
            "span_id": "root001",
            "parent_span_id": None,
            "name": "agent_master_run",
            "kind": "SERVER",
            "start_time_ns": 1_000_000_000,
            "end_time_ns": 1_500_000_000,
            "duration_ms": 500.0,
            "status": "OK",
            "attributes_json": json.dumps({"gen_ai.agent.name": "MasterAgent"}),
            "events_json": "[]",
            "prompt_payload": "Execute financial analysis",
            "completion_payload": "Analysis complete: ROI is 24%",
            "gen_ai_system": "openai",
            "gen_ai_request_model": "gpt-4o",
            "gen_ai_operation": "agent_run",
            "gen_ai_input_tokens": 120,
            "gen_ai_output_tokens": 80,
            "gen_ai_total_tokens": 200,
            "gen_ai_cost_usd": 0.0011,
            "gen_ai_tool_name": None,
            "created_at": "2026-11-18 08:00:00",
        },
        {
            "trace_id": "0123456789abcdef0123456789abcdef",
            "span_id": "tool001",
            "parent_span_id": "root001",
            "name": "execute_tool: fetch_market_data",
            "kind": "INTERNAL",
            "start_time_ns": 1_100_000_000,
            "end_time_ns": 1_300_000_000,
            "duration_ms": 200.0,
            "status": "OK",
            "attributes_json": json.dumps({"db.query": "SELECT * FROM market"}),
            "events_json": "[]",
            "prompt_payload": '{"symbol": "NVDA"}',
            "completion_payload": '{"price": 142.50}',
            "gen_ai_system": None,
            "gen_ai_request_model": None,
            "gen_ai_operation": "execute_tool",
            "gen_ai_input_tokens": 0,
            "gen_ai_output_tokens": 0,
            "gen_ai_total_tokens": 0,
            "gen_ai_cost_usd": 0.0,
            "gen_ai_tool_name": "fetch_market_data",
            "created_at": "2026-11-18 08:00:00",
        }
    ]

    html = generate_trace_capsule("0123456789abcdef0123456789abcdef", spans)

    # 1. Zero external network dependencies (no unpkg, cdnjs, fonts.googleapis)
    assert "https://" not in html
    assert "http://" not in html
    assert "<!DOCTYPE html>" in html

    # 2. Contains embedded script JSON data
    assert '<script id="nanotrace-data" type="application/json">' in html
    assert "0123456789abcdef0123456789abcdef" in html

    # 3. Contains Dual-Audience Lens elements
    assert "Business Lens" in html
    assert "Hacker Lens" in html
    assert 'id="viewBusiness"' in html
    assert 'id="viewHacker"' in html

    # 4. Contains evaluations
    assert "Automated Quality &amp; Safety Evaluations" in html


def test_export_trace_capsule_file_creation():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.duckdb")
        sink = DuckDBSink(db_path=db_path)
        sp = Span(name="test_root", attributes={"gen_ai.system": "openai", "gen_ai.usage.total_tokens": 50})
        sp.end()
        sink.write_spans([sp])
        sink.close()

        out_html = os.path.join(tmpdir, "exported_capsule.html")
        result_path = export_trace_capsule(trace_id=sp.context.trace_id, db_path=db_path, output_path=out_html)

        assert os.path.exists(result_path)
        assert os.path.getsize(result_path) > 1000
        content = open(result_path, "r", encoding="utf-8").read()
        assert sp.context.trace_id in content
        assert "NanoTrace Capsule" in content


def test_export_trace_capsule_not_found():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.duckdb")
        sink = DuckDBSink(db_path=db_path)
        sink.close()

        with pytest.raises(ValueError, match="Trace not found"):
            export_trace_capsule(trace_id="nonexistent_id", db_path=db_path)
