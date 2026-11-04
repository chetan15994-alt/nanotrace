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

    def resolve_db_path(custom_db: Optional[str] = None) -> str:
        if not custom_db:
            return db_path
        clean_name = os.path.basename(custom_db)
        if not clean_name.endswith(".duckdb") and clean_name != ":memory:":
            clean_name += ".duckdb"
        base_dir = Path(db_path).parent
        return str(base_dir / clean_name)

    def get_sink(custom_db: Optional[str] = None) -> DuckDBSink:
        target = resolve_db_path(custom_db)
        return DuckDBSink(db_path=target)

    @app.get("/api/databases")
    def list_databases():
        base_dir = Path(db_path).parent
        results = []
        if base_dir.exists():
            for f in sorted(base_dir.glob("*.duckdb")):
                try:
                    s = DuckDBSink(db_path=str(f))
                    st = s.get_stats()
                    s.close()
                    results.append({
                        "name": f.name,
                        "total_spans": st.get("total_spans", 0),
                        "total_traces": st.get("total_traces", 0),
                        "is_default": (f.name == Path(db_path).name),
                    })
                except Exception:
                    pass
        return results

    @app.get("/api/stats")
    def get_stats(db: Optional[str] = None):
        sink = get_sink(db)
        try:
            return sink.get_stats()
        finally:
            sink.close()

    @app.get("/api/traces")
    def get_traces(limit: int = 50, db: Optional[str] = None):
        sink = get_sink(db)
        try:
            return sink.get_recent_traces(limit=limit)
        finally:
            sink.close()

    @app.get("/api/traces/{trace_id}")
    def get_trace(trace_id: str, db: Optional[str] = None):
        sink = get_sink(db)
        try:
            spans = sink.get_trace_tree(trace_id)
            if not spans:
                raise HTTPException(status_code=404, detail="Trace not found")
            return spans
        finally:
            sink.close()

    @app.get("/api/evals/{trace_id}")
    def evaluate_trace(trace_id: str, db: Optional[str] = None):
        sink = get_sink(db)
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
