"""RAG Hallucination Radar Engine & DuckDB Vector Analytics.

Analyzes retrieval distance metrics, projects vector spaces into 2D scatter coordinates,
and detects semantic voids that correlate with agent hallucinations.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Union

import duckdb

from nanotrace.exceptions import RAGDriftError
from nanotrace.rag.models import RAGQueryRecord, RAGRadarPoint, RAGRadarSummary, RetrievedChunk
from nanotrace.rag.projection import project_embeddings_2d, project_synthesized_radar_coordinates

logger = logging.getLogger("nanotrace.rag")


class RAGRadarEngine:
    """Embedded Vector Space Diagnostics & RAG Hallucination Radar Engine."""

    def __init__(self, db_path: str = "./.traces/nanotrace.duckdb", void_threshold: float = 0.55):
        self.db_path = db_path
        self.void_threshold = void_threshold
        self._mem_conn = duckdb.connect(":memory:") if db_path == ":memory:" else None
        self._init_schema()

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        if self._mem_conn is not None:
            return self._mem_conn
        try:
            return duckdb.connect(self.db_path)
        except Exception as e:
            raise RAGDriftError(f"Failed to connect to DuckDB at '{self.db_path}': {e}") from e

    def _close_conn(self, conn: duckdb.DuckDBPyConnection) -> None:
        if conn is not self._mem_conn:
            conn.close()

    def _init_schema(self) -> None:
        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rag_queries (
                    query_id VARCHAR PRIMARY KEY,
                    trace_id VARCHAR,
                    query_text VARCHAR,
                    top_k INTEGER,
                    min_similarity DOUBLE,
                    mean_similarity DOUBLE,
                    is_semantic_void BOOLEAN,
                    query_embedding_json VARCHAR,
                    retrieved_chunks_json VARCHAR,
                    created_at VARCHAR
                )
            """)
        finally:
            self._close_conn(conn)

    def record_query(
        self,
        query_text: str,
        retrieved_chunks: List[Union[RetrievedChunk, Dict[str, Any]]],
        query_embedding: Optional[List[float]] = None,
        trace_id: Optional[str] = None,
        void_threshold: Optional[float] = None,
    ) -> RAGQueryRecord:
        """Record a RAG query and its retrieved document chunks."""
        threshold = void_threshold if void_threshold is not None else self.void_threshold

        chunks: List[RetrievedChunk] = []
        for c in retrieved_chunks:
            if isinstance(c, RetrievedChunk):
                chunks.append(c)
            elif isinstance(c, dict):
                chunks.append(
                    RetrievedChunk(
                        chunk_id=c.get("chunk_id", f"chk_{len(chunks)}"),
                        text=c.get("text", ""),
                        similarity_score=float(c.get("similarity_score", 0.0)),
                        embedding=c.get("embedding"),
                        metadata=c.get("metadata", {}),
                    )
                )

        record = RAGQueryRecord(
            trace_id=trace_id,
            query_text=query_text,
            query_embedding=query_embedding,
            retrieved_chunks=chunks,
        )
        record.is_semantic_void = record.mean_similarity < threshold

        # Store in DuckDB
        conn = self._get_connection()
        try:
            q_emb_json = json.dumps(record.query_embedding) if record.query_embedding else None
            chunks_json = json.dumps([c.to_dict() for c in record.retrieved_chunks])
            conn.execute(
                """
                INSERT OR REPLACE INTO rag_queries (
                    query_id, trace_id, query_text, top_k, min_similarity,
                    mean_similarity, is_semantic_void, query_embedding_json,
                    retrieved_chunks_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    record.query_id,
                    record.trace_id,
                    record.query_text,
                    record.top_k,
                    record.min_similarity,
                    record.mean_similarity,
                    record.is_semantic_void,
                    q_emb_json,
                    chunks_json,
                    record.created_at,
                ],
            )
        finally:
            self._close_conn(conn)

        return record

    def list_queries(self, limit: int = 100, void_only: bool = False) -> List[Dict[str, Any]]:
        """List recorded RAG queries ordered by creation date."""
        conn = self._get_connection()
        try:
            where_clause = "WHERE is_semantic_void = TRUE" if void_only else ""
            rows = conn.execute(
                f"""
                SELECT query_id, trace_id, query_text, top_k, min_similarity,
                       mean_similarity, is_semantic_void, retrieved_chunks_json, created_at
                FROM rag_queries
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                [limit],
            ).fetchall()

            result = []
            for r in rows:
                chunks = []
                try:
                    chunks = json.loads(r[7]) if r[7] else []
                except Exception:
                    pass

                result.append({
                    "query_id": r[0],
                    "trace_id": r[1],
                    "query_text": r[2],
                    "top_k": r[3],
                    "min_similarity": round(float(r[4]), 4) if r[4] is not None else 0.0,
                    "mean_similarity": round(float(r[5]), 4) if r[5] is not None else 0.0,
                    "is_semantic_void": bool(r[6]),
                    "retrieved_chunks": chunks,
                    "created_at": r[8],
                })
            return result
        finally:
            self._close_conn(conn)

    def get_radar_summary(self, limit: int = 150) -> RAGRadarSummary:
        """Compute aggregated RAG diagnostics and 2D radar points for visualization."""
        conn = self._get_connection()
        try:
            stats_row = conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN is_semantic_void THEN 1 END) as void_cnt,
                    AVG(mean_similarity) as avg_sim
                FROM rag_queries
            """).fetchone()

            total_q = stats_row[0] if stats_row else 0
            void_q = stats_row[1] if stats_row else 0
            avg_sim = float(stats_row[2]) if stats_row and stats_row[2] is not None else 0.0
            void_rate = (void_q / total_q * 100.0) if total_q > 0 else 0.0

            # Fetch rows with embedding JSON for 2D projection
            rows = conn.execute("""
                SELECT query_id, trace_id, query_text, min_similarity, mean_similarity,
                       is_semantic_void, query_embedding_json, retrieved_chunks_json
                FROM rag_queries
                ORDER BY created_at DESC
                LIMIT ?
            """, [limit]).fetchall()

            # Check if actual float vectors are available
            vector_list: List[List[float]] = []
            vector_indices: List[int] = []

            for i, r in enumerate(rows):
                if r[6]:  # query_embedding_json
                    try:
                        emb = json.loads(r[6])
                        if isinstance(emb, list) and len(emb) > 0 and isinstance(emb[0], (int, float)):
                            vector_list.append([float(x) for x in emb])
                            vector_indices.append(i)
                    except Exception:
                        pass

            coords_map: Dict[int, tuple] = {}
            if len(vector_list) >= 2:
                # High-dimensional embeddings available: run PCA projection
                proj_coords = project_embeddings_2d(vector_list)
                for idx, pt in zip(vector_indices, proj_coords):
                    coords_map[idx] = pt

            radar_points: List[RAGRadarPoint] = []
            void_queries: List[Dict[str, Any]] = []

            for i, r in enumerate(rows):
                qid = r[0]
                tid = r[1]
                qtext = r[2] or ""
                min_sim = float(r[3]) if r[3] is not None else 0.0
                mean_sim = float(r[4]) if r[4] is not None else 0.0
                is_void = bool(r[5])

                # Use PCA coordinates if available, otherwise deterministic polar projection
                if i in coords_map:
                    x, y = coords_map[i]
                else:
                    x, y = project_synthesized_radar_coordinates(qid, mean_sim, is_void, seed_index=i)

                pt_type = "void" if is_void else "query"
                radar_points.append(
                    RAGRadarPoint(
                        id=qid,
                        x=x,
                        y=y,
                        label=f"{'🚨 Void' if is_void else '🔍 Query'}: {qtext[:30]}...",
                        point_type=pt_type,
                        similarity=mean_sim,
                        text_snippet=qtext,
                        metadata={"trace_id": tid, "min_similarity": min_sim, "mean_similarity": mean_sim},
                    )
                )

                if is_void:
                    void_queries.append({
                        "query_id": qid,
                        "trace_id": tid,
                        "query_text": qtext,
                        "mean_similarity": round(mean_sim, 4),
                        "top_k": 0,
                    })

            return RAGRadarSummary(
                total_queries=total_q,
                semantic_void_count=void_q,
                void_rate_pct=void_rate,
                mean_similarity=avg_sim,
                radar_points=radar_points,
                void_queries=void_queries[:10],
            )
        finally:
            self._close_conn(conn)

    def scan_spans_for_rag(self) -> int:
        """Scan stored spans in DuckDB for retrieval operations and index them into rag_queries."""
        conn = self._get_connection()
        try:
            # Check if spans table exists
            table_check = conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'spans'").fetchone()
            if not table_check or table_check[0] == 0:
                return 0

            # Find spans with retrieval operations
            rows = conn.execute("""
                SELECT span_id, trace_id, name, prompt_payload, completion_payload, attributes_json, duration_ms
                FROM spans
                WHERE gen_ai_operation = 'retrieval' 
                   OR name LIKE '%retriev%' 
                   OR name LIKE '%search%' 
                   OR name LIKE '%vector%'
                   OR attributes_json LIKE '%rag%'
            """).fetchall()

            count = 0
            for r in rows:
                span_id, trace_id, name, prompt_p, comp_p, attrs_json, dur_ms = r
                
                # Parse attributes JSON for OTel GenAI conventions
                attrs: Dict[str, Any] = {}
                if attrs_json:
                    try:
                        attrs = json.loads(attrs_json)
                    except Exception:
                        pass

                # Parse query text (priority: OTel attribute -> JSON payload -> raw prompt -> span name)
                q_text = ""
                if "gen_ai.retrieval.query" in attrs:
                    q_text = str(attrs["gen_ai.retrieval.query"])
                elif prompt_p:
                    try:
                        parsed = json.loads(prompt_p)
                        if isinstance(parsed, dict) and "query" in parsed:
                            q_text = str(parsed["query"])
                        else:
                            q_text = str(prompt_p)
                    except Exception:
                        q_text = str(prompt_p)
                
                if not q_text:
                    q_text = f"Query for {name}"

                # Parse retrieved chunks (priority: OTel gen_ai.retrieval.documents -> completion payload -> fallback)
                chunks: List[RetrievedChunk] = []
                if "gen_ai.retrieval.documents" in attrs and isinstance(attrs["gen_ai.retrieval.documents"], list):
                    for idx, doc in enumerate(attrs["gen_ai.retrieval.documents"]):
                        if isinstance(doc, dict):
                            cid = str(doc.get("id") or doc.get("chunk_id") or f"chk_{span_id}_{idx}")
                            score = float(doc.get("score") or doc.get("similarity") or 0.82)
                            title = doc.get("title", "")
                            remedy = doc.get("remedy", "")
                            content = f"{title}: {remedy}" if title or remedy else json.dumps(doc)
                            chunks.append(RetrievedChunk(chunk_id=cid, text=content, similarity_score=score, metadata=doc))
                        elif isinstance(doc, str):
                            chunks.append(RetrievedChunk(chunk_id=f"chk_{span_id}_{idx}", text=doc, similarity_score=0.82))

                if not chunks and comp_p:
                    try:
                        c_parsed = json.loads(comp_p)
                        if isinstance(c_parsed, list):
                            for idx, item in enumerate(c_parsed):
                                chunks.append(RetrievedChunk(chunk_id=f"chk_{span_id}_{idx}", text=str(item), similarity_score=0.82))
                        elif isinstance(c_parsed, dict) and "results" in c_parsed:
                            for idx, item in enumerate(c_parsed["results"]):
                                chunks.append(RetrievedChunk(chunk_id=f"chk_{span_id}_{idx}", text=str(item), similarity_score=0.85))
                    except Exception:
                        pass

                if not chunks:
                    chunks.append(RetrievedChunk(
                        chunk_id=f"chk_{span_id}_0",
                        text=comp_p[:300] if comp_p else "Retrieved context document",
                        similarity_score=0.78,
                    ))

                # Check if already recorded
                existing = conn.execute("SELECT 1 FROM rag_queries WHERE trace_id = ? AND query_text = ?", [trace_id, q_text]).fetchone()
                if not existing:
                    self.record_query(query_text=q_text, retrieved_chunks=chunks, trace_id=trace_id)
                    count += 1

            return count
        finally:
            self._close_conn(conn)
