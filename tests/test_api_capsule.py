"""Tests for API routes related to capsule export."""

import os
import tempfile
from fastapi.testclient import TestClient

from nanotrace.ui.server import create_app
from nanotrace.core.span import Span
from nanotrace.storage.duckdb_sink import DuckDBSink


def test_api_export_html_route():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "api_test.duckdb")
        sink = DuckDBSink(db_path=db_path)
        sp = Span(name="api_trace_root", attributes={"gen_ai.system": "anthropic"})
        sp.end()
        sink.write_spans([sp])
        sink.close()

        trace_id = sp.context.trace_id

        app = create_app(db_path=db_path)
        client = TestClient(app)

        # GET /api/traces/{trace_id}/export-html
        resp = client.get(f"/api/traces/{trace_id}/export-html")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert f'filename="{trace_id}.ntrace.html"' in resp.headers.get("content-disposition", "")
        assert trace_id in resp.text
        assert "NanoTrace Capsule" in resp.text


def test_api_export_html_not_found():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "api_empty.duckdb")
        sink = DuckDBSink(db_path=db_path)
        sink.close()

        app = create_app(db_path=db_path)
        client = TestClient(app)

        resp = client.get("/api/traces/00000000000000000000000000000000/export-html")
        assert resp.status_code == 404
