import os
import json
import tempfile
from typer.testing import CliRunner
from nanotrace.cli import app
from nanotrace.storage.duckdb_sink import DuckDBSink
from nanotrace.core.span import Span

runner = CliRunner()


def test_cli_stats_and_query():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "cli_test.duckdb")
        sink = DuckDBSink(db_path=db_path)
        s = Span(name="test_span", attributes={"gen_ai.usage.total_tokens": 100})
        s.end()
        sink.write_spans([s])
        sink.close()

        # Test stats
        res = runner.invoke(app, ["stats", "--db", db_path])
        assert res.exit_code == 0
        assert "Total Spans" in res.output
        assert "1" in res.output

        # Test query
        res = runner.invoke(app, ["query", "SELECT name, gen_ai_total_tokens FROM spans", "--db", db_path])
        assert res.exit_code == 0
        assert "test_span" in res.output

        # Test eval command
        res = runner.invoke(app, ["eval", "--db", db_path])
        assert res.exit_code == 0
        assert "tool_reliability" in res.output

        # Test export
        parquet_out = os.path.join(tmpdir, "cli_out.parquet")
        res = runner.invoke(app, ["export", "--output", parquet_out, "--db", db_path])
        assert res.exit_code == 0
        assert os.path.exists(parquet_out)

        # Test ingest command with JSON file
        json_file = os.path.join(tmpdir, "messy_trace.json")
        with open(json_file, "w") as f:
            json.dump({
                "agent": "CLI_Ingest_Agent",
                "task": "Test CLI ingestion",
                "output": "CLI ingestion successful",
                "usage": {"prompt_tokens": 120, "completion_tokens": 40}
            }, f)

        res_ingest = runner.invoke(app, ["ingest", json_file, "--db", db_path])
        assert res_ingest.exit_code == 0
        assert "Successfully healed and ingested" in res_ingest.output

        # Verify ingested span is in DuckDB
        sink2 = DuckDBSink(db_path=db_path)
        rows = sink2.query("SELECT * FROM spans WHERE name = 'CLI_Ingest_Agent'")
        assert len(rows) == 1
        assert rows[0]["gen_ai_input_tokens"] == 120
        sink2.close()
