"""Pydantic data models for NanoTrace Server: Multi-Tenant Control Plane."""

from __future__ import annotations

import enum
import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Role(str, enum.Enum):
    """Role-Based Access Control roles."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Permission(str, enum.Enum):
    """Granular permissions."""

    VIEW_TRACES = "view_traces"
    INGEST_TRACES = "ingest_traces"
    EXPORT_DATA = "export_data"
    MANAGE_PROMPTS = "manage_prompts"
    MANAGE_DATASETS = "manage_datasets"
    MANAGE_ALERTS = "manage_alerts"
    MANAGE_KEYS = "manage_keys"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_WORKSPACE = "manage_workspace"


ROLE_PERMISSIONS: Dict[Role, List[Permission]] = {
    Role.VIEWER: [
        Permission.VIEW_TRACES,
        Permission.EXPORT_DATA,
    ],
    Role.MEMBER: [
        Permission.VIEW_TRACES,
        Permission.INGEST_TRACES,
        Permission.EXPORT_DATA,
        Permission.MANAGE_PROMPTS,
        Permission.MANAGE_DATASETS,
    ],
    Role.ADMIN: [
        Permission.VIEW_TRACES,
        Permission.INGEST_TRACES,
        Permission.EXPORT_DATA,
        Permission.MANAGE_PROMPTS,
        Permission.MANAGE_DATASETS,
        Permission.MANAGE_ALERTS,
        Permission.MANAGE_KEYS,
        Permission.MANAGE_MEMBERS,
    ],
    Role.OWNER: [
        Permission.VIEW_TRACES,
        Permission.INGEST_TRACES,
        Permission.EXPORT_DATA,
        Permission.MANAGE_PROMPTS,
        Permission.MANAGE_DATASETS,
        Permission.MANAGE_ALERTS,
        Permission.MANAGE_KEYS,
        Permission.MANAGE_MEMBERS,
        Permission.MANAGE_WORKSPACE,
    ],
}


class KeyType(str, enum.Enum):
    """API Key types."""

    INGEST_ONLY = "ingest_only"  # Prefix: nt_live_
    ADMIN = "admin"              # Prefix: nt_adm_


class Workspace(BaseModel):
    """Multi-tenant organization/team workspace."""

    workspace_id: str = Field(default_factory=lambda: f"ws_{uuid.uuid4().hex[:10]}")
    name: str
    slug: str
    owner_email: str
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    plan: str = "team"  # "hobby", "team", "enterprise"


class Project(BaseModel):
    """Scoped project inside a workspace (e.g. 'Customer Support Agent')."""

    project_id: str = Field(default_factory=lambda: f"proj_{uuid.uuid4().hex[:10]}")
    workspace_id: str
    name: str
    slug: str
    description: str = ""
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


class User(BaseModel):
    """Collaborator user in a workspace."""

    user_id: str = Field(default_factory=lambda: f"usr_{uuid.uuid4().hex[:10]}")
    workspace_id: str
    email: str
    name: str
    role: Role = Role.MEMBER
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


class APIKey(BaseModel):
    """Cryptographic API key for agent cluster ingestion or admin access."""

    key_id: str = Field(default_factory=lambda: f"key_{uuid.uuid4().hex[:10]}")
    workspace_id: str
    project_id: Optional[str] = None
    name: str
    key_prefix: str  # First 12 chars e.g. "nt_live_abcd"
    hashed_secret: str  # SHA-256 of the secret
    key_type: KeyType = KeyType.INGEST_ONLY
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    last_used_at: Optional[str] = None
    is_active: bool = True


# --- Ingestion Models ---

class IngestSpanPayload(BaseModel):
    """Span payload sent by remote agents."""

    span_id: str
    trace_id: str
    parent_span_id: Optional[str] = None
    name: str
    span_type: str = "internal"
    status: str = "ok"
    start_time_ns: int
    end_time_ns: int
    duration_ms: float = 0.0
    model: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    input: Optional[str] = None
    output: Optional[str] = None
    error_message: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    node_id: Optional[str] = None


class IngestBatchRequest(BaseModel):
    """Batch ingestion request."""

    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    node_id: Optional[str] = None
    hostname: Optional[str] = None
    sent_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    spans: List[IngestSpanPayload] = Field(default_factory=list)


class IngestBatchResponse(BaseModel):
    """Ingestion confirmation response."""

    success: bool = True
    accepted_spans: int = 0
    workspace_id: str
    project_id: str
    lakehouse_partition: str
    latency_ms: float = 0.0
    error: Optional[str] = None


# --- Prompt Registry Models ---

class PromptTag(str, enum.Enum):
    """Tags indicating deployment maturity."""

    PRODUCTION = "production"
    STAGING = "staging"
    EXPERIMENTAL = "experimental"
    ARCHIVED = "archived"


class PromptVersion(BaseModel):
    """Specific immutable version of a prompt template."""

    version_id: str = Field(default_factory=lambda: f"ver_{uuid.uuid4().hex[:10]}")
    version_number: int = 1  # 1, 2, 3...
    semver: str = "1.0.0"     # "1.0.0", "1.1.0"
    template: str
    system_prompt: Optional[str] = None
    variables: List[str] = Field(default_factory=list)  # Detected variables e.g. ["query", "context"]
    author_email: str
    commit_message: str = "Initial version"
    tags: List[PromptTag] = Field(default_factory=lambda: [PromptTag.EXPERIMENTAL])
    model_config_defaults: Dict[str, Any] = Field(default_factory=dict)  # e.g. {"model": "gpt-4o", "temperature": 0.2}
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


class Prompt(BaseModel):
    """Team-shared prompt entity containing version history."""

    prompt_id: str = Field(default_factory=lambda: f"prm_{uuid.uuid4().hex[:10]}")
    workspace_id: str
    project_id: str
    name: str  # Identifier like "support_agent_system_v1"
    description: str = ""
    latest_version: int = 1
    versions: List[PromptVersion] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    updated_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


# --- Team Golden Datasets Models ---

class GoldenTestCase(BaseModel):
    """Single curated golden test case for CI/CD regression testing."""

    case_id: str = Field(default_factory=lambda: f"case_{uuid.uuid4().hex[:10]}")
    dataset_id: str
    input_prompt: str
    expected_output: Optional[str] = None
    context_chunks: List[str] = Field(default_factory=list)
    assertions: Dict[str, Any] = Field(default_factory=dict)  # e.g. {"max_duration_ms": 2000, "must_contain": ["refund"]}
    source_trace_id: Optional[str] = None  # If promoted from a production trace
    curated_by: str = "system"
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


class GoldenDataset(BaseModel):
    """Curated collection of golden test cases."""

    dataset_id: str = Field(default_factory=lambda: f"ds_{uuid.uuid4().hex[:10]}")
    workspace_id: str
    project_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    cases_count: int = 0
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    updated_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


# --- Real-Time Alerting Models ---

class AlertChannelType(str, enum.Enum):
    """Destination notification channel."""

    SLACK = "slack"
    DISCORD = "discord"
    PAGERDUTY = "pagerduty"
    GENERIC_WEBHOOK = "webhook"


class AlertTriggerCondition(str, enum.Enum):
    """Trigger conditions for firing alerts."""

    KILLSWITCH_TRIGGERED = "killswitch_triggered"  # NanoShield halted runaway loop
    LATENCY_THRESHOLD = "latency_threshold"        # Trace took > X ms
    COST_THRESHOLD = "cost_threshold"              # Trace cost > $X
    ERROR_SPIKE = "error_spike"                    # Error status detected
    RAG_HALLUCINATION = "rag_hallucination"        # NanoDrift score > threshold


class AlertRule(BaseModel):
    """Configured alert rule."""

    rule_id: str = Field(default_factory=lambda: f"rule_{uuid.uuid4().hex[:10]}")
    workspace_id: str
    project_id: Optional[str] = None
    name: str
    condition: AlertTriggerCondition
    threshold_value: float = 0.0  # e.g. 3000 ms, or $0.50
    channel_type: AlertChannelType
    webhook_url: str
    secret_token: Optional[str] = None  # For signing payloads with HMAC-SHA256
    is_active: bool = True
    rate_limit_cooldown_s: int = 60      # Minimum seconds between duplicate alerts
    created_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


class AlertIncident(BaseModel):
    """Dispatched alert event payload."""

    incident_id: str = Field(default_factory=lambda: f"inc_{uuid.uuid4().hex[:10]}")
    rule_id: str
    workspace_id: str
    project_id: Optional[str] = None
    title: str
    description: str
    severity: str = "warning"  # "critical", "warning", "info"
    trigger_condition: AlertTriggerCondition
    trace_id: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    dispatched_at: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    dispatch_status: str = "success"  # "success", "failed"
    response_code: Optional[int] = None
    error_detail: Optional[str] = None
