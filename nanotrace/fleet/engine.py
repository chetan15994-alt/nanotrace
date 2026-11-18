"""NanoFleet Synchronization & Distributed Swarm Lakehouse Engine.

Facilitates zero-latency multi-node telemetry aggregation using compressed Parquet
micro-batches and DuckDB lakehouse ingestion.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import platform
import socket
import time
from typing import Any, Dict, List, Optional

import duckdb

from nanotrace.exceptions import NanoTraceError
from nanotrace.fleet.models import FleetNode, FleetOverview, SyncResult

logger = logging.getLogger("nanotrace.fleet")


class FleetSyncEngine:
    """Orchestrates multi-node trace snapshot exports and fleet lakehouse aggregation."""

    def __init__(self, db_path: str = "./.traces/nanotrace.duckdb"):
        self.db_path = db_path
        self._mem_conn = duckdb.connect(":memory:") if db_path == ":memory:" else None
        self._init_schema()

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        if self._mem_conn is not None:
            return self._mem_conn
        try:
            return duckdb.connect(self.db_path)
        except Exception as e:
            raise NanoTraceError(f"Failed to connect to DuckDB at '{self.db_path}': {e}") from e

    def _close_conn(self, conn: duckdb.DuckDBPyConnection) -> None:
        if conn is not self._mem_conn:
            conn.close()

    def _init_schema(self) -> None:
        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fleet_nodes (
                    node_id VARCHAR PRIMARY KEY,
                    hostname VARCHAR,
                    ip_address VARCHAR,
                    status VARCHAR,
                    spans_synced INTEGER,
                    last_sync_at VARCHAR,
                    target_uri VARCHAR,
                    metadata_json VARCHAR
                );
                CREATE TABLE IF NOT EXISTS fleet_sync_log (
                    sync_id VARCHAR PRIMARY KEY,
                    node_id VARCHAR,
                    target_uri VARCHAR,
                    spans_exported INTEGER,
                    files_written_json VARCHAR,
                    elapsed_ms DOUBLE,
                    status VARCHAR,
                    error VARCHAR,
                    created_at VARCHAR
                );
            """)
        finally:
            self._close_conn(conn)

    def register_node(
        self,
        node_id: Optional[str] = None,
        hostname: Optional[str] = None,
        ip_address: Optional[str] = None,
        target_uri: str = "local",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> FleetNode:
        """Register or update a distributed agent worker node."""
        h_name = hostname or platform.node() or "localhost"
        try:
            ip_addr = ip_address or socket.gethostbyname(socket.gethostname())
        except Exception:
            ip_addr = "127.0.0.1"

        nid = node_id or f"node_{h_name.replace('.', '_')[:12]}_{abs(hash(h_name)) % 10000}"
        node = FleetNode(
            node_id=nid,
            hostname=h_name,
            ip_address=ip_addr,
            status="active",
            target_uri=target_uri,
            metadata=metadata or {},
        )

        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO fleet_nodes (
                    node_id, hostname, ip_address, status, spans_synced,
                    last_sync_at, target_uri, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    node.node_id,
                    node.hostname,
                    node.ip_address,
                    node.status,
                    node.spans_synced,
                    node.last_sync_at,
                    node.target_uri,
                    json.dumps(node.metadata),
                ],
            )
        finally:
            self._close_conn(conn)

        return node

    def list_nodes(self) -> List[FleetNode]:
        """List all registered worker nodes in the swarm."""
        conn = self._get_connection()
        try:
            rows = conn.execute("""
                SELECT node_id, hostname, ip_address, status, spans_synced, last_sync_at, target_uri, metadata_json
                FROM fleet_nodes
                ORDER BY last_sync_at DESC
            """).fetchall()

            nodes = []
            for r in rows:
                meta = {}
                try:
                    meta = json.loads(r[7]) if r[7] else {}
                except Exception:
                    pass

                nodes.append(
                    FleetNode(
                        node_id=r[0],
                        hostname=r[1],
                        ip_address=r[2],
                        status=r[3],
                        spans_synced=int(r[4] or 0),
                        last_sync_at=r[5],
                        target_uri=r[6],
                        metadata=meta,
                    )
                )
            return nodes
        finally:
            self._close_conn(conn)

    def export_snapshot(
        self,
        target_dir: str,
        since_timestamp_ns: Optional[int] = None,
        node_id: Optional[str] = None,
    ) -> SyncResult:
        """Export local spans snapshot to a ZSTD-compressed Parquet micro-batch file."""
        start_t = time.perf_counter()
        os.makedirs(target_dir, exist_ok=True)

        nid = node_id or f"node_{platform.node().replace('.', '_')[:12]}"
        timestamp_str = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        out_filename = f"fleet_{nid}_{timestamp_str}.parquet"
        out_path = os.path.join(target_dir, out_filename)

        # Ensure node is registered in fleet registry
        self.register_node(node_id=nid, target_uri=out_path)

        conn = self._get_connection()
        try:
            # Check if spans table exists
            table_check = conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'spans'").fetchone()
            if not table_check or table_check[0] == 0:
                return SyncResult(
                    node_id=nid,
                    target_uri=out_path,
                    spans_exported=0,
                    files_written=[],
                    elapsed_ms=(time.perf_counter() - start_t) * 1000.0,
                    status="no_op",
                    error="No spans table found",
                )

            where_clause = ""
            if since_timestamp_ns is not None:
                where_clause = f"WHERE start_time_ns >= {since_timestamp_ns}"

            count_row = conn.execute(f"SELECT COUNT(*) FROM spans {where_clause}").fetchone()
            span_count = count_row[0] if count_row else 0

            if span_count == 0:
                return SyncResult(
                    node_id=nid,
                    target_uri=out_path,
                    spans_exported=0,
                    files_written=[],
                    elapsed_ms=(time.perf_counter() - start_t) * 1000.0,
                    status="no_op",
                )

            # Native DuckDB ZSTD Parquet Export
            conn.execute(f"""
                COPY (
                    SELECT * FROM spans {where_clause}
                ) TO '{out_path}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """)

            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            res = SyncResult(
                node_id=nid,
                target_uri=out_path,
                spans_exported=span_count,
                files_written=[out_path],
                elapsed_ms=elapsed_ms,
                status="success",
            )

            # Update node synced count and log
            conn.execute("""
                UPDATE fleet_nodes 
                SET spans_synced = spans_synced + ?, last_sync_at = ?
                WHERE node_id = ?
            """, [span_count, res.created_at, nid])

            conn.execute("""
                INSERT INTO fleet_sync_log (
                    sync_id, node_id, target_uri, spans_exported, files_written_json,
                    elapsed_ms, status, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                f"sync_{int(time.time()*1000)}",
                nid,
                out_path,
                span_count,
                json.dumps([out_path]),
                elapsed_ms,
                "success",
                None,
                res.created_at,
            ])

            return res

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_t) * 1000.0
            logger.error(f"Snapshot export failed: {e}")
            return SyncResult(
                node_id=nid,
                target_uri=out_path,
                spans_exported=0,
                files_written=[],
                elapsed_ms=elapsed_ms,
                status="failed",
                error=str(e),
            )
        finally:
            self._close_conn(conn)

    def import_fleet_snapshots(self, source_path_or_dir: str) -> int:
        """Scan and aggregate remote Parquet fleet snapshots into the local DuckDB lakehouse."""
        if os.path.isdir(source_path_or_dir):
            pattern = os.path.join(source_path_or_dir, "*.parquet")
        else:
            pattern = source_path_or_dir

        parquet_files = glob.glob(pattern)
        if not parquet_files and not pattern.endswith(".parquet"):
            parquet_files = glob.glob(os.path.join(source_path_or_dir, "**", "*.parquet"), recursive=True)

        if not parquet_files:
            return 0

        from nanotrace.storage.duckdb_sink import DuckDBSink

        conn = self._get_connection()
        try:
            # Check if spans table exists, otherwise initialize standard OTel schema
            table_check = conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'spans'").fetchone()
            if not table_check or table_check[0] == 0:
                conn.execute(DuckDBSink.SCHEMA_SQL)

            total_imported = 0
            for pf in parquet_files:
                # Count current rows before import
                before_cnt = conn.execute("SELECT COUNT(*) FROM spans").fetchone()[0]

                # Merge spans deduplicating on span_id
                conn.execute(f"""
                    INSERT INTO spans
                    SELECT * FROM read_parquet('{pf}')
                    WHERE span_id NOT IN (SELECT span_id FROM spans)
                """)

                after_cnt = conn.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
                total_imported += (after_cnt - before_cnt)

            return total_imported
        finally:
            self._close_conn(conn)

    def get_fleet_overview(self) -> FleetOverview:
        """Aggregate distributed swarm health and node statistics."""
        nodes = self.list_nodes()
        active_count = sum(1 for n in nodes if n.status == "active")

        conn = self._get_connection()
        try:
            # Aggregate spans count
            table_check = conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'spans'").fetchone()
            total_spans = 0
            if table_check and table_check[0] > 0:
                total_spans = conn.execute("SELECT COUNT(*) FROM spans").fetchone()[0]

            # Recent sync logs
            sync_rows = conn.execute("""
                SELECT node_id, target_uri, spans_exported, files_written_json, elapsed_ms, status, error, created_at
                FROM fleet_sync_log
                ORDER BY created_at DESC
                LIMIT 5
            """).fetchall()

            recent_syncs = []
            for sr in sync_rows:
                files = []
                try:
                    files = json.loads(sr[3]) if sr[3] else []
                except Exception:
                    pass
                recent_syncs.append(
                    SyncResult(
                        node_id=sr[0],
                        target_uri=sr[1],
                        spans_exported=int(sr[2] or 0),
                        files_written=files,
                        elapsed_ms=float(sr[4] or 0.0),
                        status=sr[5],
                        error=sr[6],
                        created_at=sr[7],
                    )
                )

            last_sync = recent_syncs[0].created_at if recent_syncs else "No sync executed"

            return FleetOverview(
                total_nodes=len(nodes),
                active_nodes=active_count,
                total_spans_aggregated=total_spans,
                last_sync_time=last_sync,
                nodes=nodes,
                recent_syncs=recent_syncs,
            )
        finally:
            self._close_conn(conn)
