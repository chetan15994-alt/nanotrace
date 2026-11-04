"""Embedded DuckDB storage sink for NanoTrace.

Provides ultra-fast columnar storage, zero-infra local database, native Parquet export,
and sub-millisecond analytical SQL queries.
"""

from __future__ import annotations

import os
import json
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional

import duckdb

from nanotrace.core.span import Span
from nanotrace.storage.base import StorageSink


class DuckDBSink(StorageSink):
    """Zero-infra, embedded DuckDB storage engine for OpenTelemetry traces."""

    SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS spans (
        trace_id VARCHAR,
        span_id VARCHAR,
        parent_span_id VARCHAR,
        name VARCHAR,
        kind VARCHAR,
        start_time_ns BIGINT,
        end_time_ns BIGINT,
        duration_ms DOUBLE,
        status VARCHAR,
        status_message VARCHAR,
        gen_ai_system VARCHAR,
        gen_ai_operation VARCHAR,
        gen_ai_request_model VARCHAR,
        gen_ai_response_model VARCHAR,
        gen_ai_agent_name VARCHAR,
        gen_ai_tool_name VARCHAR,
        gen_ai_input_tokens INTEGER,
        gen_ai_output_tokens INTEGER,
        gen_ai_total_tokens INTEGER,
        gen_ai_cost_usd DOUBLE,
        prompt_payload VARCHAR,
        completion_payload VARCHAR,
        attributes_json VARCHAR,
        events_json VARCHAR
    );

    CREATE INDEX IF NOT EXISTS idx_trace_id ON spans(trace_id);
    CREATE INDEX IF NOT EXISTS idx_span_id ON spans(span_id);
    CREATE INDEX IF NOT EXISTS idx_start_time ON spans(start_time_ns);
    CREATE INDEX IF NOT EXISTS idx_operation ON spans(gen_ai_operation);
    """

    INSERT_SQL = """
    INSERT INTO spans VALUES (
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
        ?, ?, ?, ?
    );
    """

    def __init__(self, db_path: str = "./.traces/nanotrace.duckdb"):
        self.db_path = db_path
        if db_path != ":memory:":
            path_obj = Path(db_path)
            path_obj.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._conn = duckdb.connect(self.db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize tables and indexes."""
        with self._lock:
            self._conn.execute(self.SCHEMA_SQL)

    def write_spans(self, spans: List[Span]) -> int:
        """Persist a batch of spans via vectorized insert."""
        if not spans:
            return 0

        rows = []
        for s in spans:
            flat = s.to_flat_dict()
            rows.append((
                flat["trace_id"],
                flat["span_id"],
                flat["parent_span_id"],
                flat["name"],
                flat["kind"],
                flat["start_time_ns"],
                flat["end_time_ns"],
                flat["duration_ms"],
                flat["status"],
                flat["status_message"],
                flat["gen_ai_system"],
                flat["gen_ai_operation"],
                flat["gen_ai_request_model"],
                flat["gen_ai_response_model"],
                flat["gen_ai_agent_name"],
                flat["gen_ai_tool_name"],
                flat["gen_ai_input_tokens"],
                flat["gen_ai_output_tokens"],
                flat["gen_ai_total_tokens"],
                flat["gen_ai_cost_usd"],
                flat["prompt_payload"],
                flat["completion_payload"],
                flat["attributes_json"],
                flat["events_json"],
            ))

        with self._lock:
            self._conn.executemany(self.INSERT_SQL, rows)
        return len(rows)

    def query(self, sql_or_filter: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Run SQL query against DuckDB and return list of dictionaries."""
        sql = sql_or_filter.strip()
        if not sql.lower().startswith("select"):
            sql = f"SELECT * FROM spans WHERE {sql}"

        with self._lock:
            rel = self._conn.execute(sql)
            columns = [desc[0] for desc in rel.description] if rel.description else []
            rows = rel.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    def get_trace_tree(self, trace_id: str) -> List[Dict[str, Any]]:
        """Retrieve all spans for a trace ordered by start time to reconstruct the tree."""
        query_sql = """
        SELECT * FROM spans 
        WHERE trace_id = ? 
        ORDER BY start_time_ns ASC;
        """
        with self._lock:
            rel = self._conn.execute(query_sql, [trace_id])
            columns = [desc[0] for desc in rel.description] if rel.description else []
            rows = rel.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    def get_recent_traces(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get summary of recent root agent runs."""
        query_sql = f"""
        SELECT 
            trace_id,
            COUNT(*) as total_spans,
            MIN(start_time_ns) as start_time_ns,
            MAX(end_time_ns) as end_time_ns,
            ROUND((MAX(end_time_ns) - MIN(start_time_ns)) / 1000000.0, 2) as duration_ms,
            SUM(gen_ai_input_tokens) as total_input_tokens,
            SUM(gen_ai_output_tokens) as total_output_tokens,
            SUM(gen_ai_total_tokens) as total_tokens,
            SUM(gen_ai_cost_usd) as total_cost_usd,
            MAX(CASE WHEN status = 'ERROR' THEN 'ERROR' ELSE 'OK' END) as status,
            FIRST(name) as root_name
        FROM spans
        GROUP BY trace_id
        ORDER BY start_time_ns DESC
        LIMIT {limit};
        """
        with self._lock:
            rel = self._conn.execute(query_sql)
            columns = [desc[0] for desc in rel.description] if rel.description else []
            rows = rel.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    def get_stats(self) -> Dict[str, Any]:
        """Aggregate statistical metrics for the system."""
        query_sql = """
        SELECT 
            COUNT(DISTINCT trace_id) as total_traces,
            COUNT(*) as total_spans,
            COALESCE(SUM(gen_ai_input_tokens), 0) as total_input_tokens,
            COALESCE(SUM(gen_ai_output_tokens), 0) as total_output_tokens,
            COALESCE(SUM(gen_ai_total_tokens), 0) as total_tokens,
            COALESCE(ROUND(SUM(gen_ai_cost_usd), 4), 0.0) as total_cost_usd,
            COALESCE(ROUND(quantile_cont(duration_ms, 0.50), 2), 0.0) as p50_duration_ms,
            COALESCE(ROUND(quantile_cont(duration_ms, 0.95), 2), 0.0) as p95_duration_ms,
            COALESCE(ROUND(quantile_cont(duration_ms, 0.99), 2), 0.0) as p99_duration_ms,
            COALESCE(ROUND(COUNT(CASE WHEN status = 'ERROR' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 2), 0.0) as error_rate_pct
        FROM spans;
        """
        with self._lock:
            rel = self._conn.execute(query_sql)
            row = rel.fetchone()
            columns = [desc[0] for desc in rel.description] if rel.description else []
            if row:
                return dict(zip(columns, row))
            return {
                "total_traces": 0,
                "total_spans": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "p50_duration_ms": 0.0,
                "p95_duration_ms": 0.0,
                "p99_duration_ms": 0.0,
                "error_rate_pct": 0.0,
            }

    def export_parquet(self, output_path: str) -> str:
        """Export all traces to an optimized Parquet file using DuckDB native engine."""
        path_obj = Path(output_path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        sql = f"COPY spans TO '{output_path}' (FORMAT PARQUET, COMPRESSION ZSTD);"
        with self._lock:
            self._conn.execute(sql)
        return output_path

    def flush(self) -> None:
        """Flush transactions."""
        pass

    def close(self) -> None:
        """Close database connection cleanly."""
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
