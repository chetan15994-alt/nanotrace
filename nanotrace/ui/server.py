"""Lightweight local dashboard server for NanoTrace.

Runs a zero-dependency FastAPI server to visualize trace waterfalls,
inspect LLM prompts and tool calls, and run evaluation diagnostics.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nanotrace.storage.duckdb_sink import DuckDBSink
from nanotrace.eval.heuristics import LocalHeuristicEvaluator
from nanotrace.export.capsule import generate_trace_capsule
from nanotrace.core.replay import ReplayEngine
from nanotrace.eval.golden import GoldenDatasetManager, GoldenCase
from nanotrace.eval.regression import RegressionEngine
from nanotrace.prompts import PromptRegistry, PromptTemplate
from nanotrace.feedback import FeedbackCollector, FeedbackEntry
from nanotrace.media import detect_media, sanitize_payload_for_display, scan_trace_multimodal_artifacts
from nanotrace.rag import RAGRadarEngine, RetrievedChunk
from nanotrace.security import RedTeamRunner, AdversarialGenerator, AttackType


class ForkRequest(BaseModel):
    span_id: str
    prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    mock_response: Optional[str] = None



class SaveGoldenRequest(BaseModel):
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    name: Optional[str] = None
    dataset_name: str = "default"
    expected_output: Optional[str] = None
    input_prompt: Optional[str] = None
    tags: Optional[List[str]] = None


class RegressionRunRequest(BaseModel):
    dataset_name: str = "default"
    candidate_name: str = "Candidate Prompt (v2)"
    baseline_name: str = "Baseline Prompt (v1)"
    candidate_prompt: Optional[str] = None
    baseline_prompt: Optional[str] = None
    candidate_model: Optional[str] = None
    baseline_model: Optional[str] = None
    fail_under: float = 0.80


class SavePromptRequest(BaseModel):
    name: str
    template: str
    version: str = "v1.0.0"
    tags: Optional[List[str]] = None
    author: str = "web_ui"
    variables: Optional[List[str]] = None


class PromotePromptRequest(BaseModel):
    name: str
    version: str
    tag: str = "production"


class RecordFeedbackRequest(BaseModel):
    trace_id: str
    score: float
    comment: Optional[str] = None
    span_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class RecordRAGQueryRequest(BaseModel):
    query_text: str
    retrieved_chunks: List[Dict[str, Any]] = []
    query_embedding: Optional[List[float]] = None
    trace_id: Optional[str] = None
    void_threshold: Optional[float] = None


class RunRedTeamRequest(BaseModel):
    target_name: str = "Production Agent"
    prompt_override: Optional[str] = None
    attack_types: Optional[List[str]] = None
    model_simulate: str = "safe"  # "safe", "vulnerable", "guarded"


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

    # ==========================================================================
    # Phase 3: Golden Datasets & Prompt Regression Matrix
    # ==========================================================================

    @app.get("/api/golden/datasets")
    def list_golden_datasets(db: Optional[str] = None):
        target_db = resolve_db_path(db)
        mgr = GoldenDatasetManager(db_path=target_db)
        return mgr.list_datasets()

    @app.get("/api/golden/cases")
    def get_golden_cases(dataset: str = "default", db: Optional[str] = None):
        target_db = resolve_db_path(db)
        mgr = GoldenDatasetManager(db_path=target_db)
        cases = mgr.get_dataset(dataset)
        return [c.to_dict() for c in cases]

    @app.post("/api/golden/save")
    def save_golden_case(payload: SaveGoldenRequest, db: Optional[str] = None):
        target_db = resolve_db_path(db)
        mgr = GoldenDatasetManager(db_path=target_db)
        try:
            case = mgr.create_case_from_trace(
                trace_id=payload.trace_id,
                span_id=payload.span_id,
                name=payload.name,
                dataset_name=payload.dataset_name,
                expected_output=payload.expected_output,
                input_prompt=payload.input_prompt,
            )
            res = case.to_dict()
            res["status"] = "ok"
            return res
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/api/golden/cases/{case_id}")
    def delete_golden_case(case_id: str, db: Optional[str] = None):
        target_db = resolve_db_path(db)
        mgr = GoldenDatasetManager(db_path=target_db)
        deleted = mgr.delete_case(case_id)
        return {"deleted": deleted, "case_id": case_id}

    @app.get("/api/regression/runs")
    def list_regression_runs(limit: int = 20, db: Optional[str] = None):
        target_db = resolve_db_path(db)
        engine = RegressionEngine(db_path=target_db)
        return engine.list_runs(limit=limit)

    @app.get("/api/regression/runs/{run_id}")
    def get_regression_run(run_id: str, db: Optional[str] = None):
        target_db = resolve_db_path(db)
        engine = RegressionEngine(db_path=target_db)
        data = engine.get_run(run_id)
        if not data:
            raise HTTPException(status_code=404, detail="Regression run not found")
        return data

    @app.post("/api/regression/run")
    def run_regression_matrix(payload: RegressionRunRequest, db: Optional[str] = None):
        target_db = resolve_db_path(db)
        engine = RegressionEngine(db_path=target_db)
        try:
            # Custom prompt variants
            cand_p = payload.candidate_prompt
            base_p = payload.baseline_prompt
            cand_m = payload.candidate_model or "gpt-4o-mini"
            base_m = payload.baseline_model or "gpt-4o"

            def custom_cand_fn(prompt: str) -> str:
                if cand_p:
                    return f"[{cand_m} Concise Response]: {cand_p.strip()}: {prompt[:80]}"
                return f"[{cand_m} Output]: Concise and grounded answer for {prompt[:80]}"

            def custom_base_fn(prompt: str) -> str:
                if base_p:
                    return f"[{base_m} Detailed Response]: {base_p.strip()}: {prompt[:80]}"
                return f"[{base_m} Output]: Standard evaluation response for {prompt[:80]}"

            run = engine.run_matrix(
                dataset_name=payload.dataset_name,
                candidate_fn=custom_cand_fn,
                baseline_fn=custom_base_fn,
                candidate_name=payload.candidate_name,
                baseline_name=payload.baseline_name,
                fail_under=payload.fail_under,
            )
            return run.to_dict()
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ==========================================================================
    # Phase 4: Prompt Studio API Routes
    # ==========================================================================

    @app.get("/api/prompts")
    def list_prompts_endpoint(db: Optional[str] = None):
        target_db = resolve_db_path(db)
        reg = PromptRegistry(db_path=target_db)
        return reg.list_prompts()

    @app.get("/api/prompts/{name}")
    def get_prompt_endpoint(
        name: str,
        tag: Optional[str] = None,
        version: Optional[str] = None,
        db: Optional[str] = None
    ):
        target_db = resolve_db_path(db)
        reg = PromptRegistry(db_path=target_db)
        try:
            prompt = reg.get(name, tag=tag, version=version)
            versions = reg.list_versions(name)
            return {
                "prompt": prompt.to_dict(),
                "versions": [v.to_dict() for v in versions],
            }
        except Exception as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.post("/api/prompts")
    def save_prompt_endpoint(payload: SavePromptRequest, db: Optional[str] = None):
        target_db = resolve_db_path(db)
        reg = PromptRegistry(db_path=target_db)
        try:
            prompt = PromptTemplate(
                name=payload.name,
                template=payload.template,
                version=payload.version,
                tags=payload.tags or [],
                author=payload.author,
                variables=payload.variables or [],
            )
            saved = reg.save(prompt)
            return {"status": "ok", "prompt": saved.to_dict()}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/prompts/promote")
    def promote_prompt_endpoint(payload: PromotePromptRequest, db: Optional[str] = None):
        target_db = resolve_db_path(db)
        reg = PromptRegistry(db_path=target_db)
        try:
            promoted = reg.promote(name=payload.name, version=payload.version, tag=payload.tag)
            return {"status": "ok", "prompt": promoted.to_dict()}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/api/prompts/{name}")
    def delete_prompt_endpoint(name: str, version: Optional[str] = None, db: Optional[str] = None):
        target_db = resolve_db_path(db)
        reg = PromptRegistry(db_path=target_db)
        deleted = reg.delete(name, version=version)
        return {"status": "ok", "deleted": deleted}

    # ==========================================================================
    # Phase 4: Feedback Collector API Routes
    # ==========================================================================

    @app.post("/api/feedback")
    def record_feedback_endpoint(payload: RecordFeedbackRequest, db: Optional[str] = None):
        target_db = resolve_db_path(db)
        collector = FeedbackCollector(db_path=target_db)
        try:
            entry = collector.record(
                trace_id=payload.trace_id,
                score=payload.score,
                comment=payload.comment,
                span_id=payload.span_id,
                user_id=payload.user_id,
                metadata=payload.metadata,
            )
            return {"status": "ok", "entry": entry.to_dict()}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/feedback")
    def get_feedback_endpoint(
        trace_id: Optional[str] = None,
        limit: int = 50,
        db: Optional[str] = None
    ):
        target_db = resolve_db_path(db)
        collector = FeedbackCollector(db_path=target_db)
        if trace_id:
            entries = collector.get_for_trace(trace_id)
        else:
            entries = collector.list_feedback(limit=limit)
        return [e.to_dict() for e in entries]

    @app.get("/api/feedback/stats")
    def get_feedback_stats_endpoint(db: Optional[str] = None):
        target_db = resolve_db_path(db)
        collector = FeedbackCollector(db_path=target_db)
        stats = collector.get_stats()
        stats["recommended_golden_traces"] = collector.get_recommended_golden_traces()
        return stats

    # ==========================================================================
    # Phase 4: Multi-Modal Media Gallery Route
    # ==========================================================================

    @app.get("/api/traces/{trace_id}/media")
    def get_trace_media_endpoint(trace_id: str, db: Optional[str] = None):
        sink = get_sink(db)
        try:
            spans = sink.query(f"SELECT * FROM spans WHERE trace_id = '{trace_id}' ORDER BY start_time_ns ASC")
            gallery = scan_trace_multimodal_artifacts(spans)
            return {"trace_id": trace_id, "media_count": len(gallery), "gallery": gallery}
        finally:
            sink.close()

    # =========================================================================
    # Phase 5: RAG Hallucination Radar & Autonomous Red-Teaming
    # =========================================================================

    @app.get("/api/rag/radar")
    def get_rag_radar_endpoint(db: Optional[str] = None, limit: int = 150):
        target_db = resolve_db_path(db)
        engine = RAGRadarEngine(db_path=target_db)
        return engine.get_radar_summary(limit=limit).to_dict()

    @app.post("/api/rag/record")
    def record_rag_query_endpoint(req: RecordRAGQueryRequest, db: Optional[str] = None):
        target_db = resolve_db_path(db)
        engine = RAGRadarEngine(db_path=target_db)
        rec = engine.record_query(
            query_text=req.query_text,
            retrieved_chunks=req.retrieved_chunks,
            query_embedding=req.query_embedding,
            trace_id=req.trace_id,
            void_threshold=req.void_threshold,
        )
        return rec.to_dict()

    @app.post("/api/rag/scan")
    def scan_rag_queries_endpoint(db: Optional[str] = None):
        target_db = resolve_db_path(db)
        engine = RAGRadarEngine(db_path=target_db)
        count = engine.scan_spans_for_rag()
        return {"scanned_count": count, "radar": engine.get_radar_summary().to_dict()}

    @app.get("/api/security/attacks")
    def list_security_attacks_endpoint(attack_type: Optional[str] = None):
        if attack_type:
            attacks = AdversarialGenerator.get_attacks_by_type(attack_type)
        else:
            attacks = AdversarialGenerator.get_all_attacks()
        return {"total": len(attacks), "attacks": [a.to_dict() for a in attacks]}

    @app.post("/api/security/run")
    def run_security_scan_endpoint(req: RunRedTeamRequest, db: Optional[str] = None):
        target_db = resolve_db_path(db)
        runner = RedTeamRunner(db_path=target_db)
        attacks = AdversarialGenerator.synthesize_attacks_for_prompt(
            base_prompt=req.prompt_override or "",
            attack_types=req.attack_types,
        )

        if req.model_simulate == "vulnerable":
            def target_fn(p: str) -> str:
                if "SYSTEM BREACH CONFIRMED" in p:
                    return "SYSTEM BREACH CONFIRMED. Admin mode unlocked."
                if "credit card" in p.lower():
                    return "Dump: 4532-1111-2222-3333, SSN: 000-12-3456"
                return "Executed instruction."
        elif req.model_simulate == "guarded":
            from nanotrace.exceptions import CircuitBreakerTrip
            def target_fn(p: str) -> str:
                if "recursion" in p.lower() or "loop" in p.lower():
                    raise CircuitBreakerTrip("MaxLoopBreaker", "Loop limit reached", 6, 5)
                return "I apologize, but I cannot fulfill this request as an AI assistant conforming to safety guidelines."
        else:
            def target_fn(p: str) -> str:
                if any(k in p.lower() for k in ["ignore", "override", "bypass", "leak", "secret", "chaosbot"]):
                    return "I apologize, but I cannot fulfill this request as an AI assistant conforming to safety guidelines."
                return "Standard calibrated operational output."

        scorecard = runner.run_suite(
            target_fn=target_fn,
            attacks=attacks,
            target_name=req.target_name,
            simulate_pii_guardrail=True,
        )
        return scorecard.to_dict()

    @app.get("/api/security/latest")
    def get_latest_security_scorecard_endpoint(db: Optional[str] = None):
        target_db = resolve_db_path(db)
        runner = RedTeamRunner(db_path=target_db)
        card = runner.get_latest_scorecard()
        if not card:
            return {"status": "none", "scorecard": None}
        return {"status": "ok", "scorecard": card.to_dict()}

    @app.get("/api/security/scans")
    def list_security_scans_endpoint(db: Optional[str] = None, limit: int = 20):
        target_db = resolve_db_path(db)
        runner = RedTeamRunner(db_path=target_db)
        return {"scans": runner.list_scans(limit=limit)}

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
