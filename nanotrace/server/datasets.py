"""Collaborative Golden Dataset Hub for NanoTrace Server.

Provides centralized test dataset curation, 1-click trace-to-gold promotion
from production incidents, and export to JSONL/Parquet for CI/CD matrix tests.
"""

from __future__ import annotations

import csv
import io
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from nanotrace.server.models import GoldenDataset, GoldenTestCase
from nanotrace.server.storage import ServerMetadataStorage


class GoldenDatasetEngine:
    """Manages team golden evaluation datasets and trace promotion."""

    def __init__(self, storage: ServerMetadataStorage):
        self.storage = storage

    def create_dataset(
        self,
        workspace_id: str,
        project_id: str,
        name: str,
        description: str = "",
        version: str = "1.0.0",
    ) -> GoldenDataset:
        """Creates a new team golden evaluation dataset."""
        dataset = GoldenDataset(
            workspace_id=workspace_id,
            project_id=project_id,
            name=name,
            description=description,
            version=version,
        )
        return self.storage.create_dataset(dataset)

    def promote_trace_to_gold(
        self,
        dataset_id: str,
        span_data: Dict[str, Any],
        curated_by: str = "engineer",
        expected_output: Optional[str] = None,
        custom_assertions: Optional[Dict[str, Any]] = None,
    ) -> GoldenTestCase:
        """Promotes a production trace or span into a permanent golden test case."""
        dataset = self.storage.get_dataset(dataset_id)
        if not dataset:
            raise ValueError(f"Dataset {dataset_id} not found")

        input_prompt = span_data.get("input") or span_data.get("prompt") or ""
        output = expected_output or span_data.get("output") or span_data.get("response") or ""

        # Auto-extract default assertions from runtime performance
        assertions = custom_assertions or {}
        if "max_duration_ms" not in assertions and span_data.get("duration_ms"):
            # Set SLA to 1.5x of recorded runtime
            assertions["max_duration_ms"] = round(float(span_data["duration_ms"]) * 1.5, 1)

        case = GoldenTestCase(
            dataset_id=dataset_id,
            input_prompt=str(input_prompt),
            expected_output=str(output) if output else None,
            assertions=assertions,
            source_trace_id=str(span_data.get("trace_id") or span_data.get("span_id")),
            curated_by=curated_by,
        )

        return self.storage.add_test_case(case)

    def export_dataset_jsonl(self, dataset_id: str) -> str:
        """Exports dataset test cases in standard JSONL format for CI/CD."""
        cases = self.storage.list_test_cases(dataset_id)
        lines = []
        for c in cases:
            lines.append(json.dumps(c.model_dump()))
        return "\n".join(lines)

    def export_dataset_csv(self, dataset_id: str) -> str:
        """Exports dataset test cases in standard CSV format."""
        cases = self.storage.list_test_cases(dataset_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["case_id", "input_prompt", "expected_output", "assertions", "source_trace_id", "curated_by"])
        for c in cases:
            writer.writerow([
                c.case_id,
                c.input_prompt,
                c.expected_output or "",
                json.dumps(c.assertions),
                c.source_trace_id or "",
                c.curated_by,
            ])
        return output.getvalue()

    def import_dataset_jsonl(
        self,
        dataset_id: str,
        jsonl_content: str,
        curated_by: str = "import",
    ) -> int:
        """Imports test cases from a JSONL file."""
        dataset = self.storage.get_dataset(dataset_id)
        if not dataset:
            raise ValueError(f"Dataset {dataset_id} not found")

        count = 0
        for line in jsonl_content.splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            case = GoldenTestCase(
                dataset_id=dataset_id,
                input_prompt=item.get("input_prompt") or item.get("input") or "",
                expected_output=item.get("expected_output") or item.get("output"),
                context_chunks=item.get("context_chunks", []),
                assertions=item.get("assertions", {}),
                source_trace_id=item.get("source_trace_id"),
                curated_by=curated_by,
            )
            self.storage.add_test_case(case)
            count += 1
        return count
