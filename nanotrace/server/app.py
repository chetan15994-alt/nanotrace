"""FastAPI Application for NanoTrace Server: Multi-Tenant Team Control Plane."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from nanotrace.server.alerts import AlertEngine
from nanotrace.server.auth import check_permission, generate_api_key, verify_api_key
from nanotrace.server.datasets import GoldenDatasetEngine
from nanotrace.server.ingest import IngestionRelayEngine
from nanotrace.server.models import (
    APIKey,
    AlertIncident,
    AlertRule,
    AlertTriggerCondition,
    GoldenDataset,
    GoldenTestCase,
    IngestBatchRequest,
    IngestBatchResponse,
    KeyType,
    Permission,
    Project,
    Prompt,
    PromptTag,
    PromptVersion,
    Role,
    User,
    Workspace,
)
from nanotrace.server.prompts import PromptRegistryEngine
from nanotrace.server.storage import ServerMetadataStorage


# --- Request and Response Models (Module-Level for FastAPI reflection) ---

class CreateWorkspaceRequest(BaseModel):
    name: str
    slug: str
    owner_email: str
    plan: str = "team"


class CreateProjectRequest(BaseModel):
    workspace_id: str
    name: str
    slug: str
    description: str = ""


class CreateKeyRequest(BaseModel):
    workspace_id: str
    name: str
    key_type: KeyType = KeyType.INGEST_ONLY
    project_id: Optional[str] = None


class KeyCreationResponse(BaseModel):
    key_id: str
    workspace_id: str
    project_id: Optional[str]
    name: str
    key_prefix: str
    key_type: KeyType
    raw_key: str


class CreatePromptRequest(BaseModel):
    workspace_id: str
    project_id: str
    name: str
    template: str
    author_email: str
    description: str = ""
    system_prompt: Optional[str] = None
    commit_message: str = "Update prompt"
    semver: Optional[str] = None
    tags: Optional[List[PromptTag]] = None
    model_config_defaults: Optional[Dict[str, Any]] = None


class RenderPromptRequest(BaseModel):
    variables: Dict[str, Any]


class CreateDatasetRequest(BaseModel):
    workspace_id: str
    project_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"


class PromoteTraceRequest(BaseModel):
    span_data: Dict[str, Any]
    curated_by: str = "engineer"
    expected_output: Optional[str] = None
    custom_assertions: Optional[Dict[str, Any]] = None


class CreateAlertRuleRequest(BaseModel):
    workspace_id: str
    name: str
    condition: AlertTriggerCondition
    threshold_value: float = 0.0
    channel_type: str  # "slack", "discord", "pagerduty", "webhook"
    webhook_url: str
    secret_token: Optional[str] = None
    rate_limit_cooldown_s: int = 60
    project_id: Optional[str] = None


class QueryTracesRequest(BaseModel):
    workspace_id: str
    project_id: str
    sql_query: Optional[str] = None
    limit: int = 100


def create_server_app(
    db_path: Optional[str] = None,
    lakehouse_dir: Optional[str] = None,
) -> FastAPI:
    """Factory creating configured NanoTrace Server FastAPI application."""
    storage = ServerMetadataStorage(db_path=db_path)
    ingestion_relay = IngestionRelayEngine(lakehouse_dir=lakehouse_dir)
    prompt_engine = PromptRegistryEngine(storage=storage)
    dataset_engine = GoldenDatasetEngine(storage=storage)
    alert_engine = AlertEngine(storage=storage)

    app = FastAPI(
        title="NanoTrace Cloud Server",
        description="Multi-tenant team control plane and high-throughput ingestion relay for AI agents.",
        version="0.2.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.storage = storage
    app.state.ingestion_relay = ingestion_relay
    app.state.prompt_engine = prompt_engine
    app.state.dataset_engine = dataset_engine
    app.state.alert_engine = alert_engine

    # --- Authentication Dependency ---

    async def get_current_api_key(
        x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    ) -> Optional[APIKey]:
        if not x_api_key:
            return None
        import hashlib
        hashed = hashlib.sha256(x_api_key.encode("utf-8")).hexdigest()
        key = storage.get_api_key_by_hash(hashed)
        if not key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked API key",
            )
        storage.update_key_last_used(key.key_id)
        return key

    async def require_ingest_key(
        key: Optional[APIKey] = Depends(get_current_api_key),
    ) -> APIKey:
        if not key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-API-Key header required for ingestion",
            )
        return key

    async def require_admin_key(
        key: Optional[APIKey] = Depends(get_current_api_key),
    ) -> APIKey:
        if not key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-API-Key header required",
            )
        if key.key_type != KeyType.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin API key required for this operation",
            )
        return key

    # --- Health & Metadata ---

    @app.get("/health")
    def health():
        return {
            "status": "healthy",
            "service": "nanotrace-server",
            "version": "0.2.0",
            "storage_db": storage.db_path,
            "lakehouse": ingestion_relay.lakehouse_dir,
        }

    # --- Ingestion Endpoint ---

    @app.post("/api/v1/ingest", response_model=IngestBatchResponse)
    def ingest_spans(
        batch: IngestBatchRequest,
        key: APIKey = Depends(require_ingest_key),
    ):
        workspace_id = key.workspace_id
        project_id = key.project_id or batch.project_id or "default"

        resp = ingestion_relay.ingest_batch(
            workspace_id=workspace_id,
            project_id=project_id,
            batch=batch,
        )

        for sp in batch.spans:
            if "nanoshield" in sp.name.lower() or "circuit_breaker" in sp.name.lower() or "killswitch" in sp.name.lower():
                alert_engine.evaluate_and_dispatch(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    condition=AlertTriggerCondition.KILLSWITCH_TRIGGERED,
                    metric_value=1.0,
                    trace_id=sp.trace_id,
                    context={"span_name": sp.name, "error": sp.error_message},
                )
            elif sp.duration_ms > 0:
                alert_engine.evaluate_and_dispatch(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    condition=AlertTriggerCondition.LATENCY_THRESHOLD,
                    metric_value=sp.duration_ms,
                    trace_id=sp.trace_id,
                    context={"span_name": sp.name},
                )
            elif sp.cost_usd > 0:
                alert_engine.evaluate_and_dispatch(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    condition=AlertTriggerCondition.COST_THRESHOLD,
                    metric_value=sp.cost_usd,
                    trace_id=sp.trace_id,
                    context={"span_name": sp.name},
                )

        return resp

    # --- Workspaces & Projects ---

    @app.post("/api/v1/workspaces", response_model=Workspace)
    def create_workspace(req: CreateWorkspaceRequest):
        existing = storage.get_workspace_by_slug(req.slug)
        if existing:
            raise HTTPException(status_code=400, detail=f"Slug '{req.slug}' already in use")
        ws = Workspace(
            name=req.name,
            slug=req.slug,
            owner_email=req.owner_email,
            plan=req.plan,
        )
        return storage.create_workspace(ws)

    @app.get("/api/v1/workspaces", response_model=List[Workspace])
    def list_workspaces():
        return storage.list_workspaces()

    @app.post("/api/v1/projects", response_model=Project)
    def create_project(req: CreateProjectRequest):
        ws = storage.get_workspace(req.workspace_id)
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")
        proj = Project(
            workspace_id=req.workspace_id,
            name=req.name,
            slug=req.slug,
            description=req.description,
        )
        return storage.create_project(proj)

    @app.get("/api/v1/projects", response_model=List[Project])
    def list_projects(workspace_id: str = Query(...)):
        return storage.list_projects(workspace_id)

    # --- API Keys ---

    @app.post("/api/v1/api-keys", response_model=KeyCreationResponse)
    def create_key(req: CreateKeyRequest):
        ws = storage.get_workspace(req.workspace_id)
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")
        api_key, raw_token = generate_api_key(
            workspace_id=req.workspace_id,
            name=req.name,
            key_type=req.key_type,
            project_id=req.project_id,
        )
        saved = storage.create_api_key(api_key)
        return KeyCreationResponse(
            key_id=saved.key_id,
            workspace_id=saved.workspace_id,
            project_id=saved.project_id,
            name=saved.name,
            key_prefix=saved.key_prefix,
            key_type=saved.key_type,
            raw_key=raw_token,
        )

    @app.get("/api/v1/api-keys", response_model=List[APIKey])
    def list_keys(workspace_id: str = Query(...)):
        return storage.list_api_keys(workspace_id)

    # --- Prompts ---

    @app.post("/api/v1/prompts")
    def create_or_update_prompt(req: CreatePromptRequest):
        prompt, version = prompt_engine.create_or_update_prompt(
            workspace_id=req.workspace_id,
            project_id=req.project_id,
            name=req.name,
            template=req.template,
            author_email=req.author_email,
            description=req.description,
            system_prompt=req.system_prompt,
            commit_message=req.commit_message,
            semver=req.semver,
            tags=req.tags,
            model_config_defaults=req.model_config_defaults,
        )
        return {"prompt": prompt, "latest_version": version}

    @app.get("/api/v1/prompts", response_model=List[Prompt])
    def list_prompts(workspace_id: str = Query(...), project_id: Optional[str] = Query(None)):
        return storage.list_prompts(workspace_id, project_id)

    @app.get("/api/v1/prompts/{name}")
    def get_prompt(
        name: str,
        workspace_id: str = Query(...),
        project_id: str = Query(...),
        tag: Optional[PromptTag] = Query(None),
    ):
        prompt = storage.get_prompt(workspace_id, project_id, name)
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")
        if tag:
            ver = prompt_engine.get_prompt_by_tag(workspace_id, project_id, name, tag)
            if not ver:
                raise HTTPException(status_code=404, detail=f"No prompt version found with tag '{tag}'")
            return {"prompt": prompt, "version": ver}
        return {"prompt": prompt, "latest_version": prompt.versions[-1] if prompt.versions else None}

    @app.post("/api/v1/prompts/{name}/render")
    def render_prompt(
        name: str,
        req: RenderPromptRequest,
        workspace_id: str = Query(...),
        project_id: str = Query(...),
        version_number: Optional[int] = Query(None),
    ):
        prompt = storage.get_prompt(workspace_id, project_id, name)
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")
        
        target = prompt.versions[-1]
        if version_number:
            for v in prompt.versions:
                if v.version_number == version_number:
                    target = v
                    break

        rendered_text = prompt_engine.render_template(target.template, req.variables)
        return {
            "name": name,
            "version_number": target.version_number,
            "semver": target.semver,
            "rendered": rendered_text,
        }

    @app.get("/api/v1/prompts/{name}/diff")
    def diff_prompt_versions(
        name: str,
        from_ver: int = Query(...),
        to_ver: int = Query(...),
        workspace_id: str = Query(...),
        project_id: str = Query(...),
    ):
        prompt = storage.get_prompt(workspace_id, project_id, name)
        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")

        v_from = next((v for v in prompt.versions if v.version_number == from_ver), None)
        v_to = next((v for v in prompt.versions if v.version_number == to_ver), None)

        if not v_from or not v_to:
            raise HTTPException(status_code=404, detail="One or both versions not found")

        return prompt_engine.compute_diff(v_from, v_to)

    # --- Golden Datasets ---

    @app.post("/api/v1/datasets", response_model=GoldenDataset)
    def create_dataset(req: CreateDatasetRequest):
        return dataset_engine.create_dataset(
            workspace_id=req.workspace_id,
            project_id=req.project_id,
            name=req.name,
            description=req.description,
            version=req.version,
        )

    @app.get("/api/v1/datasets", response_model=List[GoldenDataset])
    def list_datasets(workspace_id: str = Query(...), project_id: Optional[str] = Query(None)):
        return dataset_engine.storage.list_datasets(workspace_id, project_id)

    @app.post("/api/v1/datasets/{dataset_id}/promote-trace", response_model=GoldenTestCase)
    def promote_trace_to_gold(dataset_id: str, req: PromoteTraceRequest):
        try:
            return dataset_engine.promote_trace_to_gold(
                dataset_id=dataset_id,
                span_data=req.span_data,
                curated_by=req.curated_by,
                expected_output=req.expected_output,
                custom_assertions=req.custom_assertions,
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    @app.get("/api/v1/datasets/{dataset_id}/cases", response_model=List[GoldenTestCase])
    def list_dataset_cases(dataset_id: str):
        return storage.list_test_cases(dataset_id)

    @app.get("/api/v1/datasets/{dataset_id}/export")
    def export_dataset(dataset_id: str, format: str = Query("jsonl")):
        if format.lower() == "csv":
            content = dataset_engine.export_dataset_csv(dataset_id)
            return Response(content=content, media_type="text/csv")
        else:
            content = dataset_engine.export_dataset_jsonl(dataset_id)
            return Response(content=content, media_type="application/x-ndjson")

    # --- Alerts ---

    @app.post("/api/v1/alerts/rules", response_model=AlertRule)
    def create_alert_rule(req: CreateAlertRuleRequest):
        from nanotrace.server.models import AlertChannelType
        rule = AlertRule(
            workspace_id=req.workspace_id,
            project_id=req.project_id,
            name=req.name,
            condition=req.condition,
            threshold_value=req.threshold_value,
            channel_type=AlertChannelType(req.channel_type),
            webhook_url=req.webhook_url,
            secret_token=req.secret_token,
            rate_limit_cooldown_s=req.rate_limit_cooldown_s,
        )
        return storage.create_alert_rule(rule)

    @app.get("/api/v1/alerts/rules", response_model=List[AlertRule])
    def list_alert_rules(workspace_id: str = Query(...), project_id: Optional[str] = Query(None)):
        return storage.list_alert_rules(workspace_id, project_id)

    @app.get("/api/v1/alerts/incidents", response_model=List[AlertIncident])
    def list_incidents(workspace_id: str = Query(...), limit: int = Query(50)):
        return storage.list_incidents(workspace_id, limit)

    # --- Lakehouse Trace Query ---

    @app.post("/api/v1/traces/query")
    def query_lakehouse_traces(req: QueryTracesRequest):
        records = ingestion_relay.query_traces(
            workspace_id=req.workspace_id,
            project_id=req.project_id,
            sql_query=req.sql_query,
            limit=req.limit,
        )
        return {"count": len(records), "traces": records}

    return app
