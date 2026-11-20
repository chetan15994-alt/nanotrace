"""Team Collaborative Prompt Registry for NanoTrace Server.

Provides versioned prompt management, semver tagging, visual diffing,
and dynamic variable interpolation for agent workflows.
"""

from __future__ import annotations

import difflib
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from nanotrace.server.models import Prompt, PromptTag, PromptVersion
from nanotrace.server.storage import ServerMetadataStorage


class PromptRegistryEngine:
    """Manages team prompt templates, versioning, diffs, and rendering."""

    def __init__(self, storage: ServerMetadataStorage):
        self.storage = storage

    @staticmethod
    def extract_variables(template: str) -> List[str]:
        """Extracts template variables enclosed in {{var}} or {var}."""
        # Match {{var}} or {var} where var is an identifier
        matches = re.findall(r"\{\{?\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}?\}", template)
        # Deduplicate while preserving order
        seen = set()
        variables = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                variables.append(m)
        return variables

    @staticmethod
    def render_template(template: str, variables: Dict[str, Any]) -> str:
        """Interpolates variables into template supporting {var} and {{var}}."""
        rendered = template
        for k, v in variables.items():
            str_val = str(v)
            # Replace {{k}} and {k}
            escaped_k = re.escape(k)
            pattern_double = r"\{\{\s*" + escaped_k + r"\s*\}\}"
            pattern_single = r"\{\s*" + escaped_k + r"\s*\}"
            rendered = re.sub(pattern_double, str_val, rendered)
            rendered = re.sub(pattern_single, str_val, rendered)
        return rendered

    @staticmethod
    def compute_diff(version_a: PromptVersion, version_b: PromptVersion) -> Dict[str, Any]:
        """Computes unified line-by-line diff between two prompt versions."""
        lines_a = version_a.template.splitlines(keepends=True)
        lines_b = version_b.template.splitlines(keepends=True)

        diff = list(
            difflib.unified_diff(
                lines_a,
                lines_b,
                fromfile=f"v{version_a.version_number} ({version_a.semver})",
                tofile=f"v{version_b.version_number} ({version_b.semver})",
            )
        )

        additions = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))

        return {
            "from_version": version_a.version_number,
            "to_version": version_b.version_number,
            "from_semver": version_a.semver,
            "to_semver": version_b.semver,
            "additions": additions,
            "deletions": deletions,
            "unified_diff": "".join(diff),
        }

    def create_or_update_prompt(
        self,
        workspace_id: str,
        project_id: str,
        name: str,
        template: str,
        author_email: str,
        description: str = "",
        system_prompt: Optional[str] = None,
        commit_message: str = "Update prompt",
        semver: Optional[str] = None,
        tags: Optional[List[PromptTag]] = None,
        model_config_defaults: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Prompt, PromptVersion]:
        """Creates a new prompt or appends a new immutable version to an existing prompt."""
        variables = self.extract_variables(template)
        existing = self.storage.get_prompt(workspace_id, project_id, name)

        if not existing:
            # Create first version
            v1 = PromptVersion(
                version_number=1,
                semver=semver or "1.0.0",
                template=template,
                system_prompt=system_prompt,
                variables=variables,
                author_email=author_email,
                commit_message=commit_message,
                tags=tags or [PromptTag.EXPERIMENTAL],
                model_config_defaults=model_config_defaults or {},
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            prompt = Prompt(
                workspace_id=workspace_id,
                project_id=project_id,
                name=name,
                description=description,
                latest_version=1,
                versions=[v1],
            )
            saved = self.storage.save_prompt(prompt)
            return saved, v1
        else:
            # Append new version
            next_num = existing.latest_version + 1
            if not semver:
                # Default increment minor version: 1.0.0 -> 1.1.0
                parts = existing.versions[-1].semver.split(".")
                if len(parts) == 3:
                    parts[1] = str(int(parts[1]) + 1)
                    semver = ".".join(parts)
                else:
                    semver = f"1.{next_num}.0"

            new_v = PromptVersion(
                version_number=next_num,
                semver=semver,
                template=template,
                system_prompt=system_prompt if system_prompt is not None else existing.versions[-1].system_prompt,
                variables=variables,
                author_email=author_email,
                commit_message=commit_message,
                tags=tags or [PromptTag.EXPERIMENTAL],
                model_config_defaults=model_config_defaults or existing.versions[-1].model_config_defaults,
                created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            existing.versions.append(new_v)
            existing.latest_version = next_num
            if description:
                existing.description = description
            saved = self.storage.save_prompt(existing)
            return saved, new_v

    def get_prompt_by_tag(
        self,
        workspace_id: str,
        project_id: str,
        name: str,
        tag: PromptTag = PromptTag.PRODUCTION,
    ) -> Optional[PromptVersion]:
        """Finds the latest prompt version tagged with the given tag (e.g. 'production')."""
        prompt = self.storage.get_prompt(workspace_id, project_id, name)
        if not prompt:
            return None

        # Look in reverse for latest version with tag
        for v in reversed(prompt.versions):
            if tag in v.tags:
                return v
        return None

    def promote_tag(
        self,
        workspace_id: str,
        project_id: str,
        name: str,
        version_number: int,
        tag_to_apply: PromptTag,
    ) -> Optional[Prompt]:
        """Applies a tag (e.g. PRODUCTION) to a version while removing it from other versions."""
        prompt = self.storage.get_prompt(workspace_id, project_id, name)
        if not prompt:
            return None

        target_version = None
        for v in prompt.versions:
            if tag_to_apply in v.tags:
                v.tags.remove(tag_to_apply)
            if v.version_number == version_number:
                target_version = v

        if not target_version:
            return None

        if tag_to_apply not in target_version.tags:
            target_version.tags.append(tag_to_apply)

        return self.storage.save_prompt(prompt)
