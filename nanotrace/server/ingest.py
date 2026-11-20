"""High-Throughput Remote Ingestion Relay for NanoTrace Server.

Receives streaming span batches from distributed agent nodes, validates schemas,
deduplicates spans, and writes them into multi-tenant Parquet partitions using DuckDB.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional
import duckdb

from nanotrace.server.models import IngestBatchRequest, IngestBatchResponse, IngestSpanPayload


class IngestionRelayEngine:
    """High-throughput multi-tenant ingestion engine writing to Parquet lakehouse."""

    _lock = threading.Lock()

    def __init__(self, lakehouse_dir: Optional[str] = None):
        if lakehouse_dir is None:
            lakehouse_dir = os.path.expanduser("~/.nanotrace/server/lakehouse")
        os.makedirs(lakehouse_dir, exist_ok=True)
        self.lakehouse_dir = os.path.abspath(lakehouse_dir)

    def get_partition_path(self, workspace_id: str, project_id: str) -> str:
        """Returns the isolated Parquet file path for a workspace/project partition."""
        partition_dir = os.path.join(self.lakehouse_dir, workspace_id, project_id)
        os.makedirs(partition_dir, exist_ok=True)
        return os.path.join(partition_dir, "traces.parquet")

    def ingest_batch(
        self,
        workspace_id: str,
        project_id: str,
        batch: IngestBatchRequest,
    ) -> IngestBatchResponse:
        """Ingests a batch of spans into the tenant's lakehouse partition."""
        t0 = time.perf_counter()
        if not batch.spans:
            return IngestBatchResponse(
                success=True,
                accepted_spans=0,
                workspace_id=workspace_id,
                project_id=project_id,
                lakehouse_partition=self.get_partition_path(workspace_id, project_id),
                latency_ms=0.0,
            )

        parquet_path = self.get_partition_path(workspace_id, project_id)
        node_id = batch.node_id or "unknown_node"

        # Prepare normalized rows for DuckDB ingestion
        rows = []
        for sp in batch.spans:
            attrs_str = json.dumps(sp.attributes) if sp.attributes else "{}"
            rows.append({
                "span_id": str(sp.span_id),
                "trace_id": str(sp.trace_id),
                "parent_span_id": str(sp.parent_span_id) if sp.parent_span_id else None,
                "name": str(sp.name),
                "span_type": str(sp.span_type),
                "status": str(sp.status),
                "start_time_ns": int(sp.start_time_ns),
                "end_time_ns": int(sp.end_time_ns),
                "duration_ms": float(sp.duration_ms) if sp.duration_ms > 0 else (sp.end_time_ns - sp.start_time_ns) / 1_000_000.0,
                "model": str(sp.model) if sp.model else None,
                "tokens_in": int(sp.tokens_in),
                "tokens_out": int(sp.tokens_out),
                "cost_usd": float(sp.cost_usd),
                "input": str(sp.input) if sp.input else None,
                "output": str(sp.output) if sp.output else None,
                "error_message": str(sp.error_message) if sp.error_message else None,
                "attributes": attrs_str,
                "node_id": str(sp.node_id or node_id),
                "workspace_id": workspace_id,
                "project_id": project_id,
                "ingested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })

        with self._lock:
            conn = duckdb.connect()
            try:
                # Native DuckDB table creation without external dependencies
                conn.execute(
                    """
                    CREATE TEMP TABLE incoming_spans (
                        span_id VARCHAR,
                        trace_id VARCHAR,
                        parent_span_id VARCHAR,
                        name VARCHAR,
                        span_type VARCHAR,
                        status VARCHAR,
                        start_time_ns BIGINT,
                        end_time_ns BIGINT,
                        duration_ms DOUBLE,
                        model VARCHAR,
                        tokens_in BIGINT,
                        tokens_out BIGINT,
                        cost_usd DOUBLE,
                        input VARCHAR,
                        output VARCHAR,
                        error_message VARCHAR,
                        attributes VARCHAR,
                        node_id VARCHAR,
                        workspace_id VARCHAR,
                        project_id VARCHAR,
                        ingested_at VARCHAR
                    );
                    """
                )

                cols = [
                    "span_id", "trace_id", "parent_span_id", "name", "span_type", "status",
                    "start_time_ns", "end_time_ns", "duration_ms", "model", "tokens_in",
                    "tokens_out", "cost_usd", "input", "output", "error_message",
                    "attributes", "node_id", "workspace_id", "project_id", "ingested_at"
                ]

                values = [[r[c] for c in cols] for r in rows]
                placeholders = ", ".join(["?"] * len(cols))
                conn.executemany(f"INSERT INTO incoming_spans VALUES ({placeholders})", values)

                if os.path.exists(parquet_path) and os.path.getsize(parquet_path) > 0:
                    # Deduplicated append into existing Parquet file
                    conn.execute(
                        f"""
                        CREATE TEMP TABLE temp_existing AS 
                        SELECT * FROM read_parquet('{parquet_path}');
                        """
                    )
                    conn.execute(
                        """
                        CREATE TEMP TABLE merged_spans AS 
                        SELECT * FROM temp_existing
                        UNION ALL BY NAME
                        SELECT * FROM incoming_spans
                        WHERE span_id NOT IN (SELECT span_id FROM temp_existing);
                        """
                    )
                    conn.execute(
                        f"""
                        COPY merged_spans TO '{parquet_path}' (FORMAT PARQUET, COMPRESSION ZSTD);
                        """
                    )
                else:
                    # First write
                    conn.execute(
                        f"""
                        COPY incoming_spans TO '{parquet_path}' (FORMAT PARQUET, COMPRESSION ZSTD);
                        """
                    )
            finally:
                conn.close()

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        return IngestBatchResponse(
            success=True,
            accepted_spans=len(rows),
            workspace_id=workspace_id,
            project_id=project_id,
            lakehouse_partition=parquet_path,
            latency_ms=round(elapsed_ms, 2),
        )

    def query_traces(
        self,
        workspace_id: str,
        project_id: str,
        sql_query: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Executes analytical DuckDB query directly against the tenant Parquet partition."""
        parquet_path = self.get_partition_path(workspace_id, project_id)
        if not os.path.exists(parquet_path) or os.path.getsize(parquet_path) == 0:
            return []

        conn = duckdb.connect()
        try:
            if not sql_query:
                query = f"SELECT * FROM read_parquet('{parquet_path}') ORDER BY start_time_ns DESC LIMIT {limit}"
            else:
                # Safely replace table placeholder if present
                clean_query = sql_query.replace("{traces}", f"read_parquet('{parquet_path}')")
                if "read_parquet" not in clean_query:
                    clean_query = clean_query.replace("traces", f"read_parquet('{parquet_path}')")
                query = clean_query

            rel = conn.execute(query)
            cols = [desc[0] for desc in rel.description]
            records = [dict(zip(cols, row)) for row in rel.fetchall()]
            return records
        finally:
            conn.close()
