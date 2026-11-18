"""Prompt data models and template compilation engine for NanoTrace."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from nanotrace.exceptions import PromptError


@dataclass
class PromptTemplate:
    """Represents a versioned prompt template with variable schema."""
    name: str
    template: str
    version: str = "v1.0.0"
    variables: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    author: str = "system"
    prompt_id: str = field(default_factory=lambda: f"pmt_{uuid.uuid4().hex[:12]}")
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        # Auto-extract variables if not explicitly provided
        if not self.variables and self.template:
            found = re.findall(r"\{\{([a-zA-Z0-9_]+)\}\}", self.template)
            # Deduplicate while preserving order
            seen = set()
            self.variables = [x for x in found if not (x in seen or seen.add(x))]

    def compile(self, strict: bool = False, **kwargs) -> str:
        """Compile prompt by substituting {{variable}} parameters with supplied kwargs."""
        missing = [v for v in self.variables if v not in kwargs]
        if strict and missing:
            raise PromptError(f"Missing required prompt variables: {', '.join(missing)}")

        def repl(match: re.Match) -> str:
            var_name = match.group(1)
            if var_name in kwargs:
                val = kwargs[var_name]
                return str(val) if val is not None else ""
            if strict:
                raise PromptError(f"Missing required prompt variable: '{var_name}'")
            return match.group(0)  # Preserve {{var_name}} if non-strict

        return re.sub(r"\{\{([a-zA-Z0-9_]+)\}\}", repl, self.template)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_id": self.prompt_id,
            "name": self.name,
            "version": self.version,
            "template": self.template,
            "variables": self.variables,
            "tags": self.tags,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PromptTemplate:
        return cls(
            name=data["name"],
            template=data["template"],
            version=data.get("version", "v1.0.0"),
            variables=data.get("variables") or [],
            tags=data.get("tags") or [],
            author=data.get("author", "system"),
            prompt_id=data.get("prompt_id") or f"pmt_{uuid.uuid4().hex[:12]}",
            created_at=data.get("created_at") or datetime.now(timezone.utc).isoformat(),
            updated_at=data.get("updated_at") or datetime.now(timezone.utc).isoformat(),
        )
