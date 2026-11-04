"""Lightweight local dashboard server for NanoTrace.

Runs a zero-dependency FastAPI server to visualize trace waterfalls,
inspect LLM prompts and tool calls, and run evaluation diagnostics.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from nanotrace.storage.duckdb_sink import DuckDBSink
from nanotrace.eval.heuristics import LocalHeuristicEvaluator

STATIC_DIR = Path(__file__).parent / "static"


def create_app(db_path: str = "./.traces/nanotrace.duckdb") -> FastAPI:
    """Create FastAPI application for NanoTrace UI."""
    app = FastAPI(title="NanoTrace Observability Dashboard", version="0.1.0")

    def get_sink() -> DuckDBSink:
        return DuckDBSink(db_path=db_path)

    @app.get("/api/stats")
    def get_stats():
        sink = get_sink()
        try:
            return sink.get_stats()
        finally:
            sink.close()

    @app.get("/api/traces")
    def get_traces(limit: int = 50):
        sink = get_sink()
        try:
            return sink.get_recent_traces(limit=limit)
        finally:
            sink.close()

    @app.get("/api/traces/{trace_id}")
    def get_trace(trace_id: str):
        sink = get_sink()
        try:
            spans = sink.get_trace_tree(trace_id)
            if not spans:
                raise HTTPException(status_code=404, detail="Trace not found")
            return spans
        finally:
            sink.close()

    @app.get("/api/evals/{trace_id}")
    def evaluate_trace(trace_id: str):
        sink = get_sink()
        try:
            spans = sink.get_trace_tree(trace_id)
            if not spans:
                raise HTTPException(status_code=404, detail="Trace not found")
            heuristics = LocalHeuristicEvaluator.evaluate_all(spans)
            return [
                {
                    "metric_name": h.metric_name,
                    "score": h.score,
                    "passed": h.passed,
                    "details": h.details,
                }
                for h in heuristics
            ]
        finally:
            sink.close()

    @app.get("/", response_class=HTMLResponse)
    def serve_dashboard():
        html_file = STATIC_DIR / "index.html"
        if html_file.exists():
            return html_file.read_text(encoding="utf-8")
        return "<h1>NanoTrace UI static files not found</h1>"

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


def start_ui(db_path: str = "./.traces/nanotrace.duckdb", host: str = "127.0.0.1", port: int = 7777):
    """Launch the dashboard in uvicorn."""
    import uvicorn
    app = create_app(db_path=db_path)
    print(f"\n⚡️ [NanoTrace] Dashboard running at: http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")
