"""Unit and functional tests for NanoTrace Phase 1 CLI commands: run, export-capsule, export."""

import os
import sys
import tempfile
from pathlib import Path
from typer.testing import CliRunner

from nanotrace.cli import app
from nanotrace.core.span import Span
from nanotrace.storage.duckdb_sink import DuckDBSink

runner = CliRunner()


def test_cli_export_capsule():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.duckdb")
        sink = DuckDBSink(db_path=db_path)
        sp = Span(name="cli_root_test", attributes={"gen_ai.system": "openai"})
        sp.end()
        sink.write_spans([sp])
        sink.close()

        trace_id = sp.context.trace_id
        out_file = os.path.join(tmpdir, "out.html")

        # Command: nanotrace export-capsule <trace_id> -o out.html --db db_path
        res = runner.invoke(app, ["export-capsule", trace_id, "-o", out_file, "--db", db_path])
        assert res.exit_code == 0
        assert os.path.exists(out_file)
        assert trace_id in Path(out_file).read_text(encoding="utf-8")


def test_cli_export_with_format_html():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.duckdb")
        sink = DuckDBSink(db_path=db_path)
        sp = Span(name="format_html_test")
        sp.end()
        sink.write_spans([sp])
        sink.close()

        out_file = os.path.join(tmpdir, "auto.html")
        res = runner.invoke(app, ["export", "-o", out_file, "--format", "html", "--db", db_path])
        assert res.exit_code == 0
        assert os.path.exists(out_file)


def test_cli_run_script_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "run_test.duckdb")
        script_path = os.path.join(tmpdir, "sample_agent.py")

        # Create a mock agent script that runs some computation
        Path(script_path).write_text(
            "import os\n"
            "print('Agent executing...')\n"
            "x = 10 * 2\n"
            "assert x == 20\n",
            encoding="utf-8"
        )

        res = runner.invoke(app, ["run", script_path, "--db", db_path])
        assert res.exit_code == 0
        assert "Execution Telemetry Summary" in res.output

        # Verify spans were written into DuckDB
        sink = DuckDBSink(db_path=db_path)
        traces = sink.get_recent_traces(limit=10)
        sink.close()

        assert len(traces) == 1
        assert "sample_agent.py" in traces[0]["root_name"]


def test_cli_run_python_prefix_syntax():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "run_prefix.duckdb")
        script_path = os.path.join(tmpdir, "calc_agent.py")
        Path(script_path).write_text("print('Prefix test passed!')", encoding="utf-8")

        res = runner.invoke(app, ["run", "python", script_path, "--db", db_path])
        assert res.exit_code == 0
        assert "Execution Telemetry Summary" in res.output


def test_cli_run_with_nested_spans():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "run_nested.duckdb")
        script_path = os.path.join(tmpdir, "nested_agent.py")
        Path(script_path).write_text(
            "import nanotrace\n"
            "@nanotrace.trace_tool(name='calculator')\n"
            "def calculate(a, b):\n"
            "    return a + b\n\n"
            "@nanotrace.trace_agent(name='WorkerAgent')\n"
            "def run_worker():\n"
            "    return calculate(10, 32)\n\n"
            "ans = run_worker()\n"
            "assert ans == 42\n",
            encoding="utf-8"
        )

        res = runner.invoke(app, ["run", script_path, "--db", db_path])
        assert res.exit_code == 0
        assert "Execution Telemetry Summary" in res.output

        sink = DuckDBSink(db_path=db_path)
        traces = sink.get_recent_traces(limit=5)
        assert len(traces) == 1
        trace_id = traces[0]["trace_id"]
        spans = sink.get_trace_tree(trace_id)
        sink.close()

        # Should have 3 spans: run: nested_agent.py, WorkerAgent, and calculator
        span_names = [s["name"] for s in spans]
        assert any("nested_agent.py" in n for n in span_names)
        assert any("WorkerAgent" in n for n in span_names)
        assert any("calculator" in n for n in span_names)

        # Check hierarchy
        root = next(s for s in spans if "nested_agent.py" in s["name"])
        worker = next(s for s in spans if "WorkerAgent" in s["name"])
        calc = next(s for s in spans if "calculator" in s["name"])
        assert worker["parent_span_id"] == root["span_id"]
        assert calc["parent_span_id"] == worker["span_id"]


def test_cli_run_script_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "run_err.duckdb")
        script_path = os.path.join(tmpdir, "faulty_agent.py")
        Path(script_path).write_text(
            "raise ValueError('Intentional simulation failure in agent step')",
            encoding="utf-8"
        )

        res = runner.invoke(app, ["run", script_path, "--db", db_path])
        # Even though the script failed, the trace must be persisted to DuckDB with status=ERROR
        sink = DuckDBSink(db_path=db_path)
        traces = sink.get_recent_traces(limit=5)
        assert len(traces) == 1
        trace_id = traces[0]["trace_id"]
        spans = sink.get_trace_tree(trace_id)
        sink.close()

        root = spans[0]
        assert root["status"] == "ERROR"
        assert "Intentional simulation failure" in root.get("status_message", "")


def test_cli_run_with_cli_arguments():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "run_args.duckdb")
        script_path = os.path.join(tmpdir, "cli_param_agent.py")
        Path(script_path).write_text(
            "import sys\n"
            "assert len(sys.argv) >= 3\n"
            "assert sys.argv[1] == '--iterations'\n"
            "assert sys.argv[2] == '10'\n",
            encoding="utf-8"
        )

        res = runner.invoke(app, ["run", script_path, "--db", db_path, "--iterations", "10"])
        assert res.exit_code == 0
        assert "Execution Telemetry Summary" in res.output


def test_cli_run_auto_capsule_flag():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "run_cap.duckdb")
        script_path = os.path.join(tmpdir, "simple_agent.py")
        Path(script_path).write_text("print('Capsule test')", encoding="utf-8")

        res = runner.invoke(app, ["run", script_path, "--db", db_path, "--capsule"])
        assert res.exit_code == 0
        assert "Exported standalone HTML capsule:" in res.output

