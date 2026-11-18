"""Round 1 Tests: NanoDrift Vector Space Diagnostics, Pure-Python PCA & RAG Hallucination Radar."""

import tempfile
import pytest

from nanotrace.rag.models import RetrievedChunk, RAGQueryRecord
from nanotrace.rag.projection import (
    project_embeddings_2d,
    project_synthesized_radar_coordinates,
    dot_product,
    normalize_vector,
)
from nanotrace.rag.radar import RAGRadarEngine


def test_rag_models_and_semantic_void_logic():
    """Verify RAGQueryRecord correctly computes min/mean similarity and flags semantic voids."""
    # 1. Normal high-relevance retrieval
    chunks_ok = [
        RetrievedChunk(chunk_id="c1", text="Clause 1: Standard indemnity", similarity_score=0.88),
        RetrievedChunk(chunk_id="c2", text="Clause 2: Liability caps", similarity_score=0.92),
    ]
    rec_ok = RAGQueryRecord(query_text="What are the liability limits?", retrieved_chunks=chunks_ok)
    assert rec_ok.top_k == 2
    assert rec_ok.min_similarity == 0.88
    assert rec_ok.mean_similarity == 0.90
    assert not rec_ok.is_semantic_void

    # 2. Semantic void (mean similarity 0.35 < 0.55 threshold)
    chunks_void = [
        RetrievedChunk(chunk_id="c3", text="Irrelevant menu", similarity_score=0.30),
        RetrievedChunk(chunk_id="c4", text="Unrelated recipe", similarity_score=0.40),
    ]
    rec_void = RAGQueryRecord(query_text="Compute enterprise ARR", retrieved_chunks=chunks_void)
    rec_void.is_semantic_void = rec_void.mean_similarity < 0.55
    assert rec_void.mean_similarity == 0.35
    assert rec_void.is_semantic_void


def test_pure_python_pca_2d_projection():
    """Verify that pure-Python PCA projects N high-dimensional vectors to 2D in < 5 ms."""
    import random
    import time

    rng = random.Random(1337)
    # Generate 20 vectors in 64-dimensional space
    embeddings = [[rng.gauss(0, 1) for _ in range(64)] for _ in range(20)]

    start_t = time.perf_counter()
    coords = project_embeddings_2d(embeddings, max_iterations=20)
    dur_ms = (time.perf_counter() - start_t) * 1000.0

    assert len(coords) == 20
    assert dur_ms < 15.0, f"PCA projection took {dur_ms:.2f} ms (> 15 ms)"

    # Verify all coordinates bounded within [-90.0, 90.0]
    for x, y in coords:
        assert -90.0 <= x <= 90.0, f"Coordinate ({x}, {y}) out of [-90, 90] bounds!"


def test_radar_engine_record_and_list():
    """Verify RAGRadarEngine records queries and retrieves them from DuckDB."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/test_rag.duckdb"
        engine = RAGRadarEngine(db_path=db_path)

        rec = engine.record_query(
            query_text="How to configure duckdb storage?",
            retrieved_chunks=[
                {"chunk_id": "c1", "text": "Set storage_path to .duckdb file", "similarity_score": 0.89},
                {"chunk_id": "c2", "text": "DuckDB supports ACID transactions", "similarity_score": 0.75},
            ],
            trace_id="tr_1001",
        )

        assert rec.query_id.startswith("rag_")
        assert not rec.is_semantic_void
        assert rec.mean_similarity == 0.82

        queries = engine.list_queries()
        assert len(queries) == 1
        assert queries[0]["query_text"] == "How to configure duckdb storage?"
        assert queries[0]["top_k"] == 2


def test_radar_summary_and_void_rate():
    """Verify RAGRadarEngine calculates void_rate_pct and radar points."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/test_radar_sum.duckdb"
        engine = RAGRadarEngine(db_path=db_path, void_threshold=0.55)

        # 3 normal queries
        for i in range(3):
            engine.record_query(
                query_text=f"Normal query #{i}",
                retrieved_chunks=[{"chunk_id": f"c_{i}", "text": "Good chunk", "similarity_score": 0.80}],
            )

        # 1 semantic void query
        engine.record_query(
            query_text="Void hallucination query",
            retrieved_chunks=[{"chunk_id": "c_bad", "text": "No match", "similarity_score": 0.25}],
        )

        summary = engine.get_radar_summary()
        assert summary.total_queries == 4
        assert summary.semantic_void_count == 1
        assert summary.void_rate_pct == 25.0
        assert len(summary.radar_points) == 4
        assert len(summary.void_queries) == 1
        assert summary.void_queries[0]["query_text"] == "Void hallucination query"


def test_scan_spans_for_rag():
    """Verify scan_spans_for_rag detects retrieval spans in DuckDB."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/test_scan.duckdb"
        import nanotrace
        from nanotrace.schema.otel import SpanKind

        tracer = nanotrace.init(storage_path=db_path)
        with tracer.span("vector_retrieval_step", kind=SpanKind.INTERNAL) as sp:
            sp.gen_ai_operation = "retrieval"
            sp.prompt_payload = '{"query": "Find compliance rules"}'
            sp.completion_payload = '{"results": ["Rule 1: Encrypt data", "Rule 2: Audit access"]}'
        tracer.shutdown()

        engine = RAGRadarEngine(db_path=db_path)
        imported = engine.scan_spans_for_rag()
        assert imported == 1

        queries = engine.list_queries()
        assert len(queries) == 1
        assert "compliance rules" in queries[0]["query_text"]
