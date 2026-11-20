"""Server metadata storage engine for NanoTrace multi-tenant control plane.

Uses embedded SQLite for transactional ACID metadata management (Workspaces,
Projects, Users, API Keys, Prompts, Golden Datasets, Alert Rules).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from nanotrace.server.models import (
    APIKey,
    AlertIncident,
    AlertRule,
    GoldenDataset,
    GoldenTestCase,
    KeyType,
    Project,
    Prompt,
    PromptTag,
    PromptVersion,
    Role,
    User,
    Workspace,
)


class ServerMetadataStorage:
    """Thread-safe ACID repository for NanoTrace Server multi-tenant metadata."""

    _lock = threading.Lock()

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = os.path.expanduser("~/.nanotrace/server")
            os.makedirs(base_dir, exist_ok=True)
            db_path = os.path.join(base_dir, "metadata.db")
        else:
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        self.db_path = db_path
        self._init_tables()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    workspace_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    owner_email TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
                    UNIQUE(workspace_id, slug)
                );

                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
                    UNIQUE(workspace_id, email)
                );

                CREATE TABLE IF NOT EXISTS api_keys (
                    key_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT,
                    name TEXT NOT NULL,
                    key_prefix TEXT NOT NULL,
                    hashed_secret TEXT UNIQUE NOT NULL,
                    key_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(workspace_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS prompts (
                    prompt_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    latest_version INTEGER NOT NULL DEFAULT 1,
                    versions_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(workspace_id, project_id, name)
                );

                CREATE TABLE IF NOT EXISTS golden_datasets (
                    dataset_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(workspace_id, project_id, name)
                );

                CREATE TABLE IF NOT EXISTS golden_test_cases (
                    case_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    input_prompt TEXT NOT NULL,
                    expected_output TEXT,
                    context_chunks_json TEXT,
                    assertions_json TEXT,
                    source_trace_id TEXT,
                    curated_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (dataset_id) REFERENCES golden_datasets(dataset_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS alert_rules (
                    rule_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT,
                    name TEXT NOT NULL,
                    condition TEXT NOT NULL,
                    threshold_value REAL NOT NULL,
                    channel_type TEXT NOT NULL,
                    webhook_url TEXT NOT NULL,
                    secret_token TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    rate_limit_cooldown_s INTEGER NOT NULL DEFAULT 60,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS alert_incidents (
                    incident_id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    trigger_condition TEXT NOT NULL,
                    trace_id TEXT,
                    metrics_json TEXT,
                    dispatched_at TEXT NOT NULL,
                    dispatch_status TEXT NOT NULL,
                    response_code INTEGER,
                    error_detail TEXT
                );
                """
            )
            conn.commit()

    # --- Workspaces ---

    def create_workspace(self, workspace: Workspace) -> Workspace:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO workspaces (workspace_id, name, slug, owner_email, plan, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace.workspace_id,
                    workspace.name,
                    workspace.slug,
                    workspace.owner_email,
                    workspace.plan,
                    workspace.created_at,
                ),
            )
            conn.commit()
        return workspace

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE workspace_id = ?", (workspace_id,)
            ).fetchone()
            if not row:
                return None
            return Workspace(**dict(row))

    def get_workspace_by_slug(self, slug: str) -> Optional[Workspace]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE slug = ?", (slug,)
            ).fetchone()
            if not row:
                return None
            return Workspace(**dict(row))

    def list_workspaces(self) -> List[Workspace]:
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM workspaces ORDER BY created_at DESC").fetchall()
            return [Workspace(**dict(r)) for r in rows]

    # --- Projects ---

    def create_project(self, project: Project) -> Project:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO projects (project_id, workspace_id, name, slug, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project.project_id,
                    project.workspace_id,
                    project.name,
                    project.slug,
                    project.description,
                    project.created_at,
                ),
            )
            conn.commit()
        return project

    def get_project(self, project_id: str) -> Optional[Project]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if not row:
                return None
            return Project(**dict(row))

    def list_projects(self, workspace_id: str) -> List[Project]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM projects WHERE workspace_id = ? ORDER BY created_at ASC",
                (workspace_id,),
            ).fetchall()
            return [Project(**dict(r)) for r in rows]

    # --- Users & RBAC ---

    def create_user(self, user: User) -> User:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, workspace_id, email, name, role, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user.user_id,
                    user.workspace_id,
                    user.email,
                    user.name,
                    user.role.value,
                    user.created_at,
                ),
            )
            conn.commit()
        return user

    def get_user(self, user_id: str) -> Optional[User]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            data["role"] = Role(data["role"])
            return User(**data)

    def list_users(self, workspace_id: str) -> List[User]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM users WHERE workspace_id = ? ORDER BY created_at ASC",
                (workspace_id,),
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["role"] = Role(d["role"])
                result.append(User(**d))
            return result

    # --- API Keys ---

    def create_api_key(self, api_key: APIKey) -> APIKey:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO api_keys (
                    key_id, workspace_id, project_id, name, key_prefix,
                    hashed_secret, key_type, created_at, last_used_at, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    api_key.key_id,
                    api_key.workspace_id,
                    api_key.project_id,
                    api_key.name,
                    api_key.key_prefix,
                    api_key.hashed_secret,
                    api_key.key_type.value,
                    api_key.created_at,
                    api_key.last_used_at,
                    1 if api_key.is_active else 0,
                ),
            )
            conn.commit()
        return api_key

    def get_api_key_by_hash(self, hashed_secret: str) -> Optional[APIKey]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE hashed_secret = ? AND is_active = 1",
                (hashed_secret,),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            d["key_type"] = KeyType(d["key_type"])
            d["is_active"] = bool(d["is_active"])
            return APIKey(**d)

    def update_key_last_used(self, key_id: str) -> None:
        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock, self._get_connection() as conn:
            conn.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE key_id = ?",
                (now_str, key_id),
            )
            conn.commit()

    def list_api_keys(self, workspace_id: str) -> List[APIKey]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM api_keys WHERE workspace_id = ? ORDER BY created_at DESC",
                (workspace_id,),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["key_type"] = KeyType(d["key_type"])
                d["is_active"] = bool(d["is_active"])
                results.append(APIKey(**d))
            return results

    # --- Prompt Registry ---

    def save_prompt(self, prompt: Prompt) -> Prompt:
        versions_str = json.dumps([v.model_dump() for v in prompt.versions])
        prompt.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO prompts (
                    prompt_id, workspace_id, project_id, name, description,
                    latest_version, versions_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, project_id, name) DO UPDATE SET
                    description = excluded.description,
                    latest_version = excluded.latest_version,
                    versions_json = excluded.versions_json,
                    updated_at = excluded.updated_at
                """,
                (
                    prompt.prompt_id,
                    prompt.workspace_id,
                    prompt.project_id,
                    prompt.name,
                    prompt.description,
                    prompt.latest_version,
                    versions_str,
                    prompt.created_at,
                    prompt.updated_at,
                ),
            )
            conn.commit()
        return prompt

    def get_prompt(self, workspace_id: str, project_id: str, name: str) -> Optional[Prompt]:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM prompts
                WHERE workspace_id = ? AND project_id = ? AND name = ?
                """,
                (workspace_id, project_id, name),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            versions_raw = json.loads(d["versions_json"])
            versions = [PromptVersion(**v) for v in versions_raw]
            d["versions"] = versions
            del d["versions_json"]
            return Prompt(**d)

    def list_prompts(self, workspace_id: str, project_id: Optional[str] = None) -> List[Prompt]:
        with self._get_connection() as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM prompts WHERE workspace_id = ? AND project_id = ? ORDER BY updated_at DESC",
                    (workspace_id, project_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM prompts WHERE workspace_id = ? ORDER BY updated_at DESC",
                    (workspace_id,),
                ).fetchall()
            
            results = []
            for r in rows:
                d = dict(r)
                versions_raw = json.loads(d["versions_json"])
                versions = [PromptVersion(**v) for v in versions_raw]
                d["versions"] = versions
                del d["versions_json"]
                results.append(Prompt(**d))
            return results

    # --- Golden Datasets ---

    def create_dataset(self, dataset: GoldenDataset) -> GoldenDataset:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO golden_datasets (
                    dataset_id, workspace_id, project_id, name, description,
                    version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset.dataset_id,
                    dataset.workspace_id,
                    dataset.project_id,
                    dataset.name,
                    dataset.description,
                    dataset.version,
                    dataset.created_at,
                    dataset.updated_at,
                ),
            )
            conn.commit()
        return dataset

    def get_dataset(self, dataset_id: str) -> Optional[GoldenDataset]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM golden_datasets WHERE dataset_id = ?", (dataset_id,)
            ).fetchone()
            if not row:
                return None
            count = conn.execute(
                "SELECT COUNT(*) FROM golden_test_cases WHERE dataset_id = ?", (dataset_id,)
            ).fetchone()[0]
            d = dict(row)
            d["cases_count"] = count
            return GoldenDataset(**d)

    def list_datasets(self, workspace_id: str, project_id: Optional[str] = None) -> List[GoldenDataset]:
        with self._get_connection() as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM golden_datasets WHERE workspace_id = ? AND project_id = ? ORDER BY created_at DESC",
                    (workspace_id, project_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM golden_datasets WHERE workspace_id = ? ORDER BY created_at DESC",
                    (workspace_id,),
                ).fetchall()
            
            results = []
            for r in rows:
                d = dict(r)
                count = conn.execute(
                    "SELECT COUNT(*) FROM golden_test_cases WHERE dataset_id = ?", (d["dataset_id"],)
                ).fetchone()[0]
                d["cases_count"] = count
                results.append(GoldenDataset(**d))
            return results

    def add_test_case(self, case: GoldenTestCase) -> GoldenTestCase:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO golden_test_cases (
                    case_id, dataset_id, input_prompt, expected_output,
                    context_chunks_json, assertions_json, source_trace_id,
                    curated_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.case_id,
                    case.dataset_id,
                    case.input_prompt,
                    case.expected_output,
                    json.dumps(case.context_chunks),
                    json.dumps(case.assertions),
                    case.source_trace_id,
                    case.curated_by,
                    case.created_at,
                ),
            )
            conn.commit()
        return case

    def list_test_cases(self, dataset_id: str) -> List[GoldenTestCase]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM golden_test_cases WHERE dataset_id = ? ORDER BY created_at ASC",
                (dataset_id,),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["context_chunks"] = json.loads(d.get("context_chunks_json") or "[]")
                d["assertions"] = json.loads(d.get("assertions_json") or "{}")
                if "context_chunks_json" in d:
                    del d["context_chunks_json"]
                if "assertions_json" in d:
                    del d["assertions_json"]
                results.append(GoldenTestCase(**d))
            return results

    # --- Alert Rules & Incidents ---

    def create_alert_rule(self, rule: AlertRule) -> AlertRule:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO alert_rules (
                    rule_id, workspace_id, project_id, name, condition,
                    threshold_value, channel_type, webhook_url, secret_token,
                    is_active, rate_limit_cooldown_s, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.rule_id,
                    rule.workspace_id,
                    rule.project_id,
                    rule.name,
                    rule.condition.value,
                    rule.threshold_value,
                    rule.channel_type.value,
                    rule.webhook_url,
                    rule.secret_token,
                    1 if rule.is_active else 0,
                    rule.rate_limit_cooldown_s,
                    rule.created_at,
                ),
            )
            conn.commit()
        return rule

    def list_alert_rules(self, workspace_id: str, project_id: Optional[str] = None) -> List[AlertRule]:
        with self._get_connection() as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM alert_rules WHERE workspace_id = ? AND (project_id = ? OR project_id IS NULL) AND is_active = 1",
                    (workspace_id, project_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM alert_rules WHERE workspace_id = ? AND is_active = 1",
                    (workspace_id,),
                ).fetchall()
            
            results = []
            for r in rows:
                d = dict(r)
                d["is_active"] = bool(d["is_active"])
                results.append(AlertRule(**d))
            return results

    def record_incident(self, incident: AlertIncident) -> AlertIncident:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO alert_incidents (
                    incident_id, rule_id, workspace_id, project_id, title,
                    description, severity, trigger_condition, trace_id,
                    metrics_json, dispatched_at, dispatch_status, response_code, error_detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident.incident_id,
                    incident.rule_id,
                    incident.workspace_id,
                    incident.project_id,
                    incident.title,
                    incident.description,
                    incident.severity,
                    incident.trigger_condition.value,
                    incident.trace_id,
                    json.dumps(incident.metrics),
                    incident.dispatched_at,
                    incident.dispatch_status,
                    incident.response_code,
                    incident.error_detail,
                ),
            )
            conn.commit()
        return incident

    def list_incidents(self, workspace_id: str, limit: int = 50) -> List[AlertIncident]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM alert_incidents WHERE workspace_id = ? ORDER BY dispatched_at DESC LIMIT ?",
                (workspace_id, limit),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["metrics"] = json.loads(d.get("metrics_json") or "{}")
                if "metrics_json" in d:
                    del d["metrics_json"]
                results.append(AlertIncident(**d))
            return results
