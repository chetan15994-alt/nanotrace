"""Round 2 Tests: Swarm Topology Analyzer, Critical Path, Chatter Detection & DAG Optimization."""

import os
import tempfile
import pytest

from nanotrace.core.span import Span
from nanotrace.storage.duckdb_sink import DuckDBSink
from nanotrace.topology.optimizer import TopologyOptimizer


def test_topology_dag_node_and_edge_extraction():
    """Verify nodes and directed delegation edges are cleanly extracted from span tree."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_topo.duckdb")
        sink = DuckDBSink(db_path=db_path)

        # Build Supervisor -> WorkerAgent -> Tool tree
        t_id = "trace_topo_01"
        root_sp = Span(name="SupervisorAgent", trace_id=t_id)
        root_sp.start_time_ns = 1_000_000_000
        root_sp.end_time_ns = 1_500_000_000  # 500ms
        root_sp.gen_ai_agent_name = "SupervisorAgent"

        worker_sp = Span(name="WorkerAgent", trace_id=t_id, parent_span_id=root_sp.span_id)
        worker_sp.start_time_ns = 1_050_000_000
        worker_sp.end_time_ns = 1_400_000_000  # 350ms
        worker_sp.gen_ai_agent_name = "WorkerAgent"

        tool_sp = Span(name="tool: db_query", trace_id=t_id, parent_span_id=worker_sp.span_id)
        tool_sp.start_time_ns = 1_100_000_000
        tool_sp.end_time_ns = 1_250_000_000  # 150ms
        tool_sp.gen_ai_tool_name = "db_query"

        sink.write_spans([root_sp, worker_sp, tool_sp])
        sink.close()

        optimizer = TopologyOptimizer(db_path=db_path)
        analysis = optimizer.analyze_trace(t_id)

        assert analysis.trace_id == t_id
        assert analysis.total_steps == 3
        assert analysis.total_agents >= 2
        assert analysis.critical_path_ms >= 500.0

        node_names = {n.name for n in analysis.nodes}
        assert "SupervisorAgent" in node_names
        assert "WorkerAgent" in node_names
        assert "tool: db_query" in node_names

        # Verify edge from SupervisorAgent to WorkerAgent, and WorkerAgent to tool: db_query
        edge_pairs = {(e.source, e.target) for e in analysis.edges}
        assert ("SupervisorAgent", "WorkerAgent") in edge_pairs
        assert ("WorkerAgent", "tool: db_query") in edge_pairs


def test_topology_ping_pong_chatter_detection():
    """Verify bidirectional communication cycles between sub-agents are identified."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_chatter.duckdb")
        sink = DuckDBSink(db_path=db_path)

        t_id = "trace_chatter_01"
        # Turn 1: AgentA -> AgentB
        s1 = Span(name="AgentA", trace_id=t_id)
        s1.start_time_ns = 1_000_000
        s1.end_time_ns = 2_000_000
        s1.gen_ai_agent_name = "AgentA"

        s2 = Span(name="AgentB", trace_id=t_id, parent_span_id=s1.span_id)
        s2.start_time_ns = 1_100_000
        s2.end_time_ns = 1_900_000
        s2.gen_ai_agent_name = "AgentB"

        # Turn 2: AgentB -> AgentA (Ping-pong reflection)
        s3 = Span(name="AgentA", trace_id=t_id, parent_span_id=s2.span_id)
        s3.start_time_ns = 1_200_000
        s3.end_time_ns = 1_800_000
        s3.gen_ai_agent_name = "AgentA"

        sink.write_spans([s1, s2, s3])
        sink.close()

        optimizer = TopologyOptimizer(db_path=db_path)
        analysis = optimizer.analyze_trace(t_id)

        # Verify chatter recommendation was generated
        chatter_recs = [r for r in analysis.recommendations if r.category == "chatter_reduction"]
        assert len(chatter_recs) >= 1
        assert "Ping-Pong" in chatter_recs[0].title
        assert chatter_recs[0].estimated_savings_pct > 0.0


def test_topology_sequential_parallelizability():
    """Verify independent sequential tools under a common parent are flagged for parallelization."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_seq.duckdb")
        sink = DuckDBSink(db_path=db_path)

        t_id = "trace_seq_01"
        root = Span(name="ResearchAgent", trace_id=t_id)
        root.start_time_ns = 1_000_000_000
        root.end_time_ns = 2_000_000_000
        root.gen_ai_agent_name = "ResearchAgent"

        # Tool 1: 100ms - 200ms
        t1 = Span(name="tool: search_a", trace_id=t_id, parent_span_id=root.span_id)
        t1.start_time_ns = 1_100_000_000
        t1.end_time_ns = 1_200_000_000
        t1.gen_ai_tool_name = "search_a"

        # Tool 2: 300ms - 400ms (strictly sequential after Tool 1)
        t2 = Span(name="tool: search_b", trace_id=t_id, parent_span_id=root.span_id)
        t2.start_time_ns = 1_300_000_000
        t2.end_time_ns = 1_400_000_000
        t2.gen_ai_tool_name = "search_b"

        sink.write_spans([root, t1, t2])
        sink.close()

        optimizer = TopologyOptimizer(db_path=db_path)
        analysis = optimizer.analyze_trace(t_id)

        parallel_recs = [r for r in analysis.recommendations if r.category == "parallelize"]
        assert len(parallel_recs) >= 1
        assert "Parallelize" in parallel_recs[0].title
        assert parallel_recs[0].estimated_savings_pct >= 40.0


def test_topology_empty_trace_handling():
    """Verify graceful handling of non-existent trace IDs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "empty_topo.duckdb")
        optimizer = TopologyOptimizer(db_path=db_path)
        analysis = optimizer.analyze_trace("non_existent_trace_xyz")
        assert analysis.total_steps == 0
        assert len(analysis.nodes) == 0
        assert len(analysis.edges) == 0
