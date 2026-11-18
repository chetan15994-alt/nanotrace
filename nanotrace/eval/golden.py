"""Trace-to-Gold Factory: Extract, curate, and persist golden evaluation datasets from production traces."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

import duckdb
from nanotrace.storage.duckdb_sink import DuckDBSink
from nanotrace.exceptions import NanoTraceError


class GoldenDatasetError(NanoTraceError):
    """Raised when golden dataset extraction or query fails."""
    pass


@dataclass
class GoldenCase:
    """A single versioned golden evaluation test case extracted from a trace."""
    case_id: str
    dataset_name: str
    name: str
    input_prompt: str
    expected_output: str
    source_trace_id: str = ""
    source_span_id: str = ""
    context_chunks: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "dataset_name": self.dataset_name,
            "name": self.name,
            "source_trace_id": self.source_trace_id,
            "source_span_id": self.source_span_id,
            "input_prompt": self.input_prompt,
            "expected_output": self.expected_output,
            "context_chunks": self.context_chunks,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoldenCase":
        ctx = data.get("context_chunks")
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except Exception:
                ctx = [ctx] if ctx else []
        elif not isinstance(ctx, list):
            ctx = []

        meta = data.get("metadata")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        elif not isinstance(meta, dict):
            meta = {}

        return cls(
            case_id=data["case_id"],
            dataset_name=data.get("dataset_name", "default"),
            name=data.get("name", "Untitled Test Case"),
            source_trace_id=data.get("source_trace_id", ""),
            source_span_id=data.get("source_span_id", ""),
            input_prompt=data.get("input_prompt", ""),
            expected_output=data.get("expected_output", ""),
            context_chunks=ctx,
            metadata=meta,
            created_at=data.get("created_at", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
        )


class GoldenDatasetManager:
    """Manages golden evaluation datasets stored in embedded DuckDB."""

    def __init__(self, db_path: str = "./.traces/nanotrace.duckdb"):
        self.db_path = db_path
        self._ensure_schema()

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(self.db_path)

    def _ensure_schema(self) -> None:
        """Create golden_cases table if it doesn't already exist."""
        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS golden_cases (
                    case_id VARCHAR PRIMARY KEY,
                    dataset_name VARCHAR,
                    name VARCHAR,
                    source_trace_id VARCHAR,
                    source_span_id VARCHAR,
                    input_prompt VARCHAR,
                    expected_output VARCHAR,
                    context_json VARCHAR,
                    metadata_json VARCHAR,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        finally:
            conn.close()

    def save_case(self, case: GoldenCase) -> GoldenCase:
        """Persist a GoldenCase into DuckDB."""
        conn = self._get_connection()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO golden_cases (
                    case_id, dataset_name, name, source_trace_id, source_span_id,
                    input_prompt, expected_output, context_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                case.case_id,
                case.dataset_name,
                case.name,
                case.source_trace_id,
                case.source_span_id,
                case.input_prompt,
                case.expected_output,
                json.dumps(case.context_chunks, default=str),
                json.dumps(case.metadata, default=str),
                case.created_at,
            ])
            return case
        finally:
            conn.close()

    def create_case_from_trace(
        self,
        trace_id: Optional[str] = None,
        span_id: Optional[str] = None,
        name: Optional[str] = None,
        dataset_name: str = "default",
        expected_output: Optional[str] = None,
        input_prompt: Optional[str] = None,
    ) -> GoldenCase:
        """Extract a golden test case directly from a recorded trace or span."""
        if not trace_id and not span_id:
            raise GoldenDatasetError("Either trace_id or span_id must be provided to create a golden case.")

        sink = DuckDBSink(db_path=self.db_path)
        try:
            if span_id:
                spans = sink.query(f"SELECT * FROM spans WHERE span_id = '{span_id}'")
            else:
                spans = sink.query(f"SELECT * FROM spans WHERE trace_id = '{trace_id}' ORDER BY start_time_ns ASC")

            if not spans:
                raise GoldenDatasetError(f"No spans found for trace '{trace_id}' (span '{span_id}')")

            target = spans[0]
            resolved_trace_id = trace_id or str(target.get("trace_id") or "")
            # Determine prompt & completion
            raw_prompt = input_prompt if input_prompt is not None else (target.get("prompt_payload") or "")
            raw_output = expected_output if expected_output is not None else (target.get("completion_payload") or "")
            node_name = name or f"Test Case: {target.get('name', 'node')}"

            # Clean json serialization if needed
            if isinstance(raw_prompt, str) and (raw_prompt.startswith("{") or raw_prompt.startswith("[")):
                try:
                    p_parsed = json.loads(raw_prompt)
                    if isinstance(p_parsed, dict) and "prompt" in p_parsed:
                        raw_prompt = p_parsed["prompt"]
                except Exception:
                    pass

            case_id = f"gold_{uuid.uuid4().hex[:12]}"
            case = GoldenCase(
                case_id=case_id,
                dataset_name=dataset_name,
                name=node_name,
                source_trace_id=resolved_trace_id,
                source_span_id=target.get("span_id", ""),
                input_prompt=str(raw_prompt).strip(),
                expected_output=str(raw_output).strip(),
                context_chunks=[str(target.get("gen_ai_tool_name") or "")],
                metadata={
                    "model": target.get("gen_ai_request_model", ""),
                    "agent_name": target.get("gen_ai_agent_name", ""),
                    "tokens": int(target.get("gen_ai_total_tokens") or 0),
                    "cost_usd": float(target.get("gen_ai_cost_usd") or 0.0),
                },
            )
            return self.save_case(case)
        finally:
            sink.close()

    def get_dataset(self, dataset_name: str = "default") -> List[GoldenCase]:
        """Fetch all golden test cases for a given dataset."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM golden_cases WHERE dataset_name = ? ORDER BY created_at ASC",
                [dataset_name]
            ).fetchall()
            cols = [d[0] for d in conn.description]
            cases = []
            for r in rows:
                row_dict = dict(zip(cols, r))
                cases.append(GoldenCase(
                    case_id=row_dict["case_id"],
                    dataset_name=row_dict["dataset_name"],
                    name=row_dict["name"],
                    source_trace_id=row_dict.get("source_trace_id") or "",
                    source_span_id=row_dict.get("source_span_id") or "",
                    input_prompt=row_dict.get("input_prompt") or "",
                    expected_output=row_dict.get("expected_output") or "",
                    context_chunks=json.loads(row_dict.get("context_json") or "[]"),
                    metadata=json.loads(row_dict.get("metadata_json") or "{}"),
                    created_at=str(row_dict.get("created_at") or ""),
                ))
            return cases
        finally:
            conn.close()

    def list_datasets(self) -> List[Dict[str, Any]]:
        """List all datasets and their respective test case counts."""
        conn = self._get_connection()
        try:
            rows = conn.execute("""
                SELECT 
                    dataset_name,
                    COUNT(*) as case_count,
                    MIN(created_at) as created_at,
                    MAX(created_at) as updated_at
                FROM golden_cases
                GROUP BY dataset_name
                ORDER BY case_count DESC
            """).fetchall()
            return [
                {
                    "dataset_name": r[0],
                    "name": r[0],
                    "case_count": int(r[1]),
                    "count": int(r[1]),
                    "created_at": str(r[2]),
                    "updated_at": str(r[3]),
                }
                for r in rows
            ]
        finally:
            conn.close()

    def delete_case(self, case_id: str) -> bool:
        """Delete a golden test case by case_id."""
        conn = self._get_connection()
        try:
            conn.execute("DELETE FROM golden_cases WHERE case_id = ?", [case_id])
            return True
        finally:
            conn.close()

    def export_jsonl(self, dataset_name: str, filepath: str) -> int:
        """Export dataset to standard JSONL format (compatible with OpenAI FineTuning & DeepEval)."""
        cases = self.get_dataset(dataset_name)
        with open(filepath, "w", encoding="utf-8") as f:
            for c in cases:
                f.write(json.dumps(c.to_dict()) + "\n")
        return len(cases)

    def import_jsonl(self, dataset_name: str, filepath: str) -> int:
        """Import test cases from JSONL."""
        count = 0
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                d["dataset_name"] = dataset_name
                if "case_id" not in d:
                    d["case_id"] = f"gold_{uuid.uuid4().hex[:12]}"
                case = GoldenCase.from_dict(d)
                self.save_case(case)
                count += 1
        return count
