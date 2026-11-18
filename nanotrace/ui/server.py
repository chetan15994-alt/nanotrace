"""Lightweight local dashboard server for NanoTrace.

Runs a zero-dependency FastAPI server to visualize trace waterfalls,
inspect LLM prompts and tool calls, and run evaluation diagnostics.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nanotrace.storage.duckdb_sink import DuckDBSink
from nanotrace.eval.heuristics import LocalHeuristicEvaluator
from nanotrace.export.capsule import generate_trace_capsule
from nanotrace.core.replay import ReplayEngine


class ForkRequest(BaseModel):
    span_id: str
    prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    mock_response: Optional[str] = None

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

    @app.get("/api/traces/{trace_id}/export-html")
    def export_trace_html(trace_id: str, db: Optional[str] = None):
        sink = get_sink(db)
        try:
            spans = sink.get_trace_tree(trace_id)
            if not spans:
                raise HTTPException(status_code=404, detail="Trace not found")
            html_content = generate_trace_capsule(trace_id=trace_id, spans=spans)
            return Response(
                content=html_content,
                media_type="text/html",
                headers={
                    "Content-Disposition": f'attachment; filename="{trace_id}.ntrace.html"'
                }
            )
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

    @app.post("/api/traces/{trace_id}/fork")
    def fork_trace_node(trace_id: str, payload: ForkRequest, db: Optional[str] = None):
        target_db = resolve_db_path(db)
        engine = ReplayEngine(db_path=target_db)
        try:
            res = engine.fork_and_replay_node(
                span_id=payload.span_id,
                prompt=payload.prompt,
                model=payload.model,
                temperature=payload.temperature,
                mock_response=payload.mock_response,
            )
            return res.to_dict()
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/replay/{span_id}/context")
    def get_replay_context(span_id: str, db: Optional[str] = None):
        target_db = resolve_db_path(db)
        engine = ReplayEngine(db_path=target_db)
        try:
            return engine.get_node_context(span_id)
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.get("/api/shield/stats")
    def get_shield_stats(db: Optional[str] = None):
        sink = get_sink(db)
        try:
            tripped_rows = sink.query("""
                SELECT 
                    SUM(CASE WHEN status = 'ERROR' AND attributes_json LIKE '%nanotrace.shield.tripped%' THEN 1 ELSE 0 END) as total_tripped,
                    SUM(CASE WHEN attributes_json LIKE '%MaxLoopBreaker%' THEN 1 ELSE 0 END) as loops_intercepted,
                    SUM(CASE WHEN attributes_json LIKE '%nanotrace.shield.pii_redacted%' THEN 1 ELSE 0 END) as pii_redactions
                FROM spans 
                WHERE attributes_json LIKE '%nanotrace.shield%'
            """)
            tripped_count = int(tripped_rows[0]["total_tripped"] or 0) if tripped_rows else 0
            loops_count = int(tripped_rows[0]["loops_intercepted"] or 0) if tripped_rows else 0
            pii_count = int(tripped_rows[0]["pii_redactions"] or 0) if tripped_rows else 0
            est_saved = (loops_count * 14.20) + (max(0, tripped_count - loops_count) * 2.50) + (pii_count * 5.00)

            return {
                "active": True,
                "total_tripped": tripped_count,
                "loops_intercepted": loops_count,
                "pii_redactions": pii_count,
                "estimated_spend_saved_usd": round(est_saved, 2),
                "configured_breakers": [
                    {"name": "MaxLoopBreaker", "status": "active", "rule": "Halt recursion >= 5"},
                    {"name": "BudgetCapBreaker", "status": "active", "rule": "Cap spend <= $1.00"},
                    {"name": "PIIRedaction", "status": "active", "rule": "Auto-mask API keys, SSN, Emails"},
                    {"name": "TimeoutBreaker", "status": "active", "rule": "Execution limit <= 60s"},
                ]
            }
        finally:
            sink.close()

    @app.get("/", response_class=HTMLResponse)
    def serve_dashboard():
        html_file = STATIC_DIR / "index.html"
        if html_file.exists():
            return html_file.read_text(encoding="utf-8")
        return "<h1>NanoTrace UI static files not found</h1>"

    @app.get("/guide", response_class=HTMLResponse)
    @app.get("/architecture", response_class=HTMLResponse)
    @app.get("/infographic", response_class=HTMLResponse)
    def serve_guide():
        html_file = STATIC_DIR / "index.html"
        if html_file.exists():
            content = html_file.read_text(encoding="utf-8")
            # Automatically activate the Architecture & Guide view
            return (
                content.replace('class="view-container active" id="viewTraces"', 'class="view-container" id="viewTraces"')
                .replace('class="view-container" id="viewGuide"', 'class="view-container active" id="viewGuide"')
                .replace('class="nav-tab active" id="tabTracesBtn"', 'class="nav-tab" id="tabTracesBtn"')
                .replace('class="nav-tab" id="tabGuideBtn"', 'class="nav-tab active" id="tabGuideBtn"')
            )
        return "<h1>NanoTrace UI static files not found</h1>"

    @app.get("/manual", response_class=HTMLResponse)
    def serve_manual():
        manual_path = Path(__file__).resolve().parent.parent.parent / "docs" / "USER_MANUAL.html"
        if manual_path.exists():
            return manual_path.read_text(encoding="utf-8")
        return "<h1>User Manual not found</h1>"

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


def start_ui(db_path: str = "./.traces/nanotrace.duckdb", host: str = "127.0.0.1", port: int = 7777):
    """Launch the dashboard in uvicorn."""
    import uvicorn
    app = create_app(db_path=db_path)
    print(f"\n⚡️ [NanoTrace] Dashboard running at: http://{host}:{port}\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")
