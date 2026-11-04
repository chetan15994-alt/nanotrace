import os
import tempfile
import pytest
from nanotrace.core.span import Span
from nanotrace.storage.duckdb_sink import DuckDBSink
from nanotrace.schema.otel import GenAIAttributes, StatusCode


def test_duckdb_sink_write_and_query():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.duckdb")
        sink = DuckDBSink(db_path=db_path)

        spans = []
        for i in range(5):
            s = Span(
                name=f"agent_step_{i}",
                attributes={
                    GenAIAttributes.SYSTEM: "anthropic",
                    GenAIAttributes.REQUEST_MODEL: "claude-3-5-sonnet",
                    GenAIAttributes.USAGE_TOTAL_TOKENS: 50 * (i + 1),
                    GenAIAttributes.USAGE_COST_USD: 0.001 * (i + 1),
                }
            )
            s.end()
            spans.append(s)

        inserted = sink.write_spans(spans)
        assert inserted == 5

        # Query
        rows = sink.query("SELECT * FROM spans WHERE gen_ai_system = 'anthropic'")
        assert len(rows) == 5

        # Stats
        stats = sink.get_stats()
        assert stats["total_spans"] == 5
        assert stats["total_tokens"] == sum(50 * (i + 1) for i in range(5))

        # Native Parquet Export
        parquet_file = os.path.join(tmpdir, "export.parquet")
        sink.export_parquet(parquet_file)
        assert os.path.exists(parquet_file)
        assert os.path.getsize(parquet_file) > 0

        sink.close()


def test_duckdb_trace_tree_retrieval():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "tree.duckdb")
        sink = DuckDBSink(db_path=db_path)

        root = Span(name="RootAgent")
        root.end()

        child1 = Span(name="ToolCall1", trace_id=root.trace_id, parent_span_id=root.span_id)
        child1.end()

        child2 = Span(name="ToolCall2", trace_id=root.trace_id, parent_span_id=root.span_id)
        child2.end()

        sink.write_spans([root, child1, child2])

        tree = sink.get_trace_tree(root.trace_id)
        assert len(tree) == 3
        assert tree[0]["name"] == "RootAgent"
        assert tree[1]["parent_span_id"] == root.span_id
        assert tree[2]["parent_span_id"] == root.span_id

        sink.close()
