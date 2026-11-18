"""Round 3 Tests: Phase 6 CLI Commands for Fleet Lakehouse Sync and Swarm Topology Optimizer."""

import os
import tempfile
import pytest
from typer.testing import CliRunner

from nanotrace.cli import app
from nanotrace.core.span import Span
from nanotrace.storage.duckdb_sink import DuckDBSink

runner = CliRunner()


def test_cli_fleet_sync_nodes_and_pull():
    """Verify nanotrace fleet sync, nodes, and pull CLI commands."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "cli_fleet.duckdb")
        sink = DuckDBSink(db_path=db_path)

        for i in range(3):
            sp = Span(name=f"cli_step_{i}", trace_id="trace_cli_fleet")
            sp.end_time_ns = sp.start_time_ns + 15_000_000
            sink.write_spans([sp])
        sink.close()

        sync_dir = os.path.join(tmpdir, "parquet_out")

        # 1. Test fleet sync
        res_sync = runner.invoke(app, ["fleet", "sync", "--target", sync_dir, "--db", db_path, "--node-id", "test_pod_01"])
        assert res_sync.exit_code == 0
        assert "NanoFleet Export Complete" in res_sync.stdout
        assert "Spans Exported: 3" in res_sync.stdout

        # 2. Test fleet nodes
        res_nodes = runner.invoke(app, ["fleet", "nodes", "--db", db_path])
        assert res_nodes.exit_code == 0
        assert "test_pod_01" in res_nodes.stdout

        # 3. Test fleet pull into secondary database
        db_target = os.path.join(tmpdir, "aggregated_lakehouse.duckdb")
        res_pull = runner.invoke(app, ["fleet", "pull", "--source", sync_dir, "--db", db_target])
        assert res_pull.exit_code == 0
        assert "Aggregated 3 new spans" in res_pull.stdout


def test_cli_topology_analyzer():
    """Verify nanotrace topology CLI command execution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "cli_topo.duckdb")
        sink = DuckDBSink(db_path=db_path)

        t_id = "trace_cli_topo_99"
        root = Span(name="CouncilLeader", trace_id=t_id)
        root.start_time_ns = 1_000_000_000
        root.end_time_ns = 1_600_000_000
        root.gen_ai_agent_name = "CouncilLeader"

        sub = Span(name="LegalAgent", trace_id=t_id, parent_span_id=root.span_id)
        sub.start_time_ns = 1_100_000_000
        sub.end_time_ns = 1_500_000_000
        sub.gen_ai_agent_name = "LegalAgent"

        sink.write_spans([root, sub])
        sink.close()

        # Run CLI topology
        res_topo = runner.invoke(app, ["topology", t_id, "--db", db_path])
        assert res_topo.exit_code == 0
        assert "Swarm Topology Analysis" in res_topo.stdout
        assert "LegalAgent" in res_topo.stdout
        assert "Critical Path" in res_topo.stdout
