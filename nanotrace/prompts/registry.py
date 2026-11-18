"""In-process DuckDB-backed prompt registry with microsecond in-memory caching."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import duckdb

from nanotrace.exceptions import PromptError
from nanotrace.prompts.models import PromptTemplate


class PromptRegistry:
    """Manages versioned prompt templates in DuckDB with zero-overhead in-memory caching."""

    def __init__(self, db_path: str = "./.traces/nanotrace.duckdb"):
        self.db_path = str(db_path)
        self._ensure_storage_dir()
        self._cache: Dict[Tuple[str, Optional[str], Optional[str]], PromptTemplate] = {}
        self._ensure_schema()

    def _ensure_storage_dir(self) -> None:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.db_path)

    def _ensure_schema(self) -> None:
        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prompts (
                    prompt_id VARCHAR PRIMARY KEY,
                    name VARCHAR,
                    version VARCHAR,
                    template TEXT,
                    variables_json TEXT,
                    tags_json TEXT,
                    author VARCHAR,
                    created_at VARCHAR,
                    updated_at VARCHAR
                );
            """)
        finally:
            conn.close()

    def save(self, prompt: PromptTemplate) -> PromptTemplate:
        """Save or update a prompt version into the registry."""
        conn = self._get_connection()
        now_str = datetime.now(timezone.utc).isoformat()
        prompt.updated_at = now_str

        try:
            # Check if this exact (name, version) already exists
            existing = conn.execute(
                "SELECT prompt_id FROM prompts WHERE name = ? AND version = ?",
                [prompt.name, prompt.version]
            ).fetchone()

            if existing:
                conn.execute("""
                    UPDATE prompts
                    SET template = ?, variables_json = ?, tags_json = ?, author = ?, updated_at = ?
                    WHERE name = ? AND version = ?
                """, [
                    prompt.template,
                    json.dumps(prompt.variables),
                    json.dumps(prompt.tags),
                    prompt.author,
                    prompt.updated_at,
                    prompt.name,
                    prompt.version,
                ])
                prompt.prompt_id = existing[0]
            else:
                conn.execute("""
                    INSERT INTO prompts (
                        prompt_id, name, version, template, variables_json, tags_json, author, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    prompt.prompt_id,
                    prompt.name,
                    prompt.version,
                    prompt.template,
                    json.dumps(prompt.variables),
                    json.dumps(prompt.tags),
                    prompt.author,
                    prompt.created_at,
                    prompt.updated_at,
                ])

            self._invalidate_cache(prompt.name)
            return prompt
        finally:
            conn.close()

    def get(
        self,
        name: str,
        tag: Optional[str] = None,
        version: Optional[str] = None,
    ) -> PromptTemplate:
        """Fetch prompt by name and optional tag or version with microsecond cache lookup."""
        cache_key = (name, tag, version)
        if cache_key in self._cache:
            return self._cache[cache_key]

        conn = self._get_connection()
        try:
            if version:
                row = conn.execute(
                    "SELECT * FROM prompts WHERE name = ? AND version = ? ORDER BY created_at DESC LIMIT 1",
                    [name, version]
                ).fetchone()
            elif tag:
                # Search where tags_json contains the tag string
                rows = conn.execute(
                    "SELECT * FROM prompts WHERE name = ? ORDER BY created_at DESC",
                    [name]
                ).fetchall()
                cols = [d[0] for d in conn.description]
                matching = None
                for r in rows:
                    rd = dict(zip(cols, r))
                    t_list = json.loads(rd.get("tags_json") or "[]")
                    if tag in t_list:
                        matching = rd
                        break
                if not matching:
                    raise PromptError(f"Prompt '{name}' with tag '{tag}' not found.")
                p = self._row_to_prompt(matching)
                self._cache[cache_key] = p
                return p
            else:
                # Default: fetch the latest version
                row = conn.execute(
                    "SELECT * FROM prompts WHERE name = ? ORDER BY created_at DESC LIMIT 1",
                    [name]
                ).fetchone()

            if not row:
                qualifier = f" (version={version})" if version else ""
                raise PromptError(f"Prompt '{name}'{qualifier} not found in registry.")

            cols = [d[0] for d in conn.description]
            p = self._row_to_prompt(dict(zip(cols, row)))
            self._cache[cache_key] = p
            return p
        finally:
            conn.close()

    def list_prompts(self) -> List[Dict[str, Any]]:
        """List summary of all distinct prompts with their latest version and active tags."""
        conn = self._get_connection()
        try:
            rows = conn.execute("""
                SELECT 
                    name,
                    COUNT(*) as total_versions,
                    MAX(version) as latest_version,
                    MAX(updated_at) as last_updated
                FROM prompts
                GROUP BY name
                ORDER BY name ASC
            """).fetchall()

            summaries = []
            for r in rows:
                p_name = r[0]
                latest_p = self.get(p_name)
                summaries.append({
                    "name": p_name,
                    "total_versions": int(r[1]),
                    "latest_version": latest_p.version,
                    "active_tags": latest_p.tags,
                    "variables": latest_p.variables,
                    "template_preview": latest_p.template[:100],
                    "last_updated": str(r[3]),
                })
            return summaries
        finally:
            conn.close()

    def list_versions(self, name: str) -> List[PromptTemplate]:
        """List all version iterations of a specific prompt."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM prompts WHERE name = ? ORDER BY created_at DESC",
                [name]
            ).fetchall()
            cols = [d[0] for d in conn.description]
            return [self._row_to_prompt(dict(zip(cols, r))) for r in rows]
        finally:
            conn.close()

    def promote(self, name: str, version: str, tag: str) -> PromptTemplate:
        """Promote a specific prompt version to a tag (e.g. 'production', 'staging')."""
        versions = self.list_versions(name)
        if not versions:
            raise PromptError(f"No prompt found with name '{name}'.")

        target = next((v for v in versions if v.version == version), None)
        if not target:
            raise PromptError(f"Version '{version}' for prompt '{name}' not found.")

        conn = self._get_connection()
        try:
            # 1. Remove tag from any other versions of this prompt
            for v in versions:
                if tag in v.tags and v.version != version:
                    new_tags = [t for t in v.tags if t != tag]
                    conn.execute(
                        "UPDATE prompts SET tags_json = ?, updated_at = ? WHERE prompt_id = ?",
                        [json.dumps(new_tags), datetime.now(timezone.utc).isoformat(), v.prompt_id]
                    )

            # 2. Add tag to target version if not present
            if tag not in target.tags:
                target.tags.append(tag)
                target.updated_at = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE prompts SET tags_json = ?, updated_at = ? WHERE prompt_id = ?",
                    [json.dumps(target.tags), target.updated_at, target.prompt_id]
                )

            self._invalidate_cache(name)
            return target
        finally:
            conn.close()

    def delete(self, name: str, version: Optional[str] = None) -> bool:
        """Delete a prompt or specific version from the registry."""
        conn = self._get_connection()
        try:
            if version:
                conn.execute("DELETE FROM prompts WHERE name = ? AND version = ?", [name, version])
            else:
                conn.execute("DELETE FROM prompts WHERE name = ?", [name])
            self._invalidate_cache(name)
            return True
        finally:
            conn.close()

    def _row_to_prompt(self, rd: Dict[str, Any]) -> PromptTemplate:
        return PromptTemplate(
            name=rd["name"],
            template=rd["template"],
            version=rd.get("version", "v1.0.0"),
            variables=json.loads(rd.get("variables_json") or "[]"),
            tags=json.loads(rd.get("tags_json") or "[]"),
            author=rd.get("author", "system"),
            prompt_id=rd["prompt_id"],
            created_at=str(rd.get("created_at") or ""),
            updated_at=str(rd.get("updated_at") or ""),
        )

    def _invalidate_cache(self, name: Optional[str] = None) -> None:
        if name:
            self._cache = {k: v for k, v in self._cache.items() if k[0] != name}
        else:
            self._cache.clear()
