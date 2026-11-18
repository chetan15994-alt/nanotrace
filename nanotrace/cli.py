"""NanoTrace Command Line Interface (CLI).

Provides commands to view stats, launch the web dashboard, run SQL queries,
and export trace datasets to Parquet or JSONL.
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from nanotrace.storage.duckdb_sink import DuckDBSink
from nanotrace.eval.heuristics import LocalHeuristicEvaluator
from nanotrace.export.capsule import export_trace_capsule

app = typer.Typer(
    name="nanotrace",
    help="⚡️ Ultra-low latency, zero-infra OpenTelemetry tracing & evaluation engine for AI agents.",
)
console = Console()


@app.command()
def stats(
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB database file"),
):
    """Display aggregate statistics of recorded agent traces."""
    sink = DuckDBSink(db_path=db_path)
    try:
        metrics = sink.get_stats()
        table = Table(title="⚡️ NanoTrace Aggregate Metrics", border_style="blue")
        table.add_column("Metric", style="cyan", no_wrap=True)
        table.add_column("Value", style="green")

        table.add_row("Total Traces", str(metrics["total_traces"]))
        table.add_row("Total Spans", str(metrics["total_spans"]))
        table.add_row("Total Input Tokens", f"{metrics['total_input_tokens']:,}")
        table.add_row("Total Output Tokens", f"{metrics['total_output_tokens']:,}")
        table.add_row("Total Tokens", f"{metrics['total_tokens']:,}")
        table.add_row("Estimated Cost (USD)", f"${metrics['total_cost_usd']:.4f}")
        table.add_row("p50 Latency (ms)", f"{metrics['p50_duration_ms']:.2f}")
        table.add_row("p95 Latency (ms)", f"{metrics['p95_duration_ms']:.2f}")
        table.add_row("p99 Latency (ms)", f"{metrics['p99_duration_ms']:.2f}")
        table.add_row("Error Rate", f"{metrics['error_rate_pct']:.1f}%")

        console.print(table)
    finally:
        sink.close()


@app.command()
def ui(
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB database file"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host interface"),
    port: int = typer.Option(7777, "--port", "-p", help="Port number"),
):
    """Launch the interactive web dashboard."""
    from nanotrace.ui.server import start_ui
    start_ui(db_path=db_path, host=host, port=port)


@app.command()
def query(
    sql: str = typer.Argument(..., help="SQL query to execute against spans table"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """Execute analytical SQL query directly on DuckDB traces."""
    sink = DuckDBSink(db_path=db_path)
    try:
        rows = sink.query(sql)
        if not rows:
            console.print("[yellow]Query returned 0 rows.[/yellow]")
            return

        table = Table(title=f"Query Results ({len(rows)} rows)", border_style="cyan")
        columns = list(rows[0].keys())
        for col in columns:
            table.add_column(col)

        for r in rows[:50]:
            table.add_row(*[str(r[c]) for c in columns])

        console.print(table)
        if len(rows) > 50:
            console.print(f"[dim]Showing first 50 of {len(rows)} rows[/dim]")
    finally:
        sink.close()


@app.command()
def export(
    output: str = typer.Option("./traces.parquet", "--output", "-o", help="Output file path (.parquet or .html)"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
    format: str = typer.Option("parquet", "--format", "-f", help="Export format: parquet or html"),
    trace_id: Optional[str] = typer.Option(None, "--trace-id", "-t", help="Specific trace ID (required if exporting to HTML)"),
):
    """Export stored traces into Parquet dataset or standalone HTML capsule."""
    is_html = (format.lower() == "html") or output.lower().endswith(".html") or output.lower().endswith(".ntrace.html")

    if is_html:
        sink = DuckDBSink(db_path=db_path)
        try:
            target_id = trace_id
            if not target_id:
                traces = sink.get_recent_traces(limit=1)
                if not traces:
                    console.print("[yellow]No traces found in DuckDB to export.[/yellow]")
                    return
                target_id = traces[0]["trace_id"]
        finally:
            sink.close()

        out_file = export_trace_capsule(trace_id=target_id, db_path=db_path, output_path=output)
        console.print(f"[green]✓ Successfully exported standalone HTML capsule for trace [bold]{target_id[:8]}[/bold]:[/green]")
        console.print(f"  [bold cyan]{out_file}[/bold cyan]")
        return

    sink = DuckDBSink(db_path=db_path)
    try:
        sink.export_parquet(output)
        console.print(f"[green]✓ Successfully exported traces to:[/green] [bold]{output}[/bold]")
    finally:
        sink.close()


@app.command("export-capsule")
def export_capsule_cmd(
    trace_id: str = typer.Argument(..., help="Trace ID to package into standalone HTML capsule"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output .html file path"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB database file"),
    open_browser: bool = typer.Option(False, "--open", help="Automatically open generated capsule in web browser"),
):
    """Export an execution trace as a 100% self-contained standalone HTML capsule."""
    try:
        out_file = export_trace_capsule(trace_id=trace_id, db_path=db_path, output_path=output)
        console.print(f"[green]✓ Standalone HTML Capsule generated:[/green] [bold]{out_file}[/bold]")
        console.print("[dim]Open this file in any web browser without Python or Docker running.[/dim]")
        if open_browser:
            import webbrowser
            webbrowser.open(f"file://{out_file}")
    except Exception as e:
        console.print(f"[red]Error exporting capsule:[/red] {e}")
        raise typer.Exit(code=1)


@app.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def run_script(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="Target Python script or 'python' followed by script path"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="DuckDB database path for trace logging"),
    open_ui: bool = typer.Option(False, "--ui", "-u", help="Open web dashboard after script execution completes"),
    export_capsule: bool = typer.Option(False, "--capsule", "-c", help="Automatically export standalone HTML capsule after run"),
    port: int = typer.Option(7777, "--port", "-p", help="Port for web dashboard if --ui is specified"),
):
    """Zero-code auto-pilot runner: executes and traces any Python agent script."""
    import sys
    import os
    import runpy
    from pathlib import Path
    import nanotrace
    from nanotrace.schema.otel import SpanKind

    # Handle cases where user types: nanotrace run python agent.py [args...]
    args = ctx.args
    if target in ("python", "python3") and args:
        script_path = args[0]
        script_args = args[1:]
    else:
        script_path = target
        script_args = args

    if not os.path.exists(script_path):
        console.print(f"[red]Error: Target script not found:[/red] {script_path}")
        raise typer.Exit(code=1)

    resolved_path = Path(script_path).resolve()
    script_name = resolved_path.name

    # 1. Initialize NanoTrace global tracer with auto_patch enabled (< 15 µs ring buffer overhead)
    tracer = nanotrace.init(storage_path=db_path, auto_patch=True)

    console.print(Panel(
        f"[bold cyan]⚡️ NanoTrace Auto-Pilot Runner[/bold cyan]\n"
        f"[dim]Executing:[/dim] [bold]{resolved_path}[/bold]\n"
        f"[dim]Overhead Engine:[/dim] In-Process Lock-Free Ring Buffer (<15µs per span)\n"
        f"[dim]Auto-Instrumenting:[/dim] OpenAI, Anthropic, LiteLLM\n"
        f"[dim]DuckDB Sink:[/dim] {db_path}",
        border_style="cyan"
    ))

    # Prepare sys.argv and sys.path
    orig_argv = sys.argv
    orig_path0 = sys.path[0] if sys.path else ""
    sys.argv = [str(resolved_path)] + script_args
    sys.path.insert(0, str(resolved_path.parent))

    trace_id = None
    script_error = None
    try:
        with tracer.span(f"run: {script_name}", kind=SpanKind.SERVER, attributes={"code.filepath": str(resolved_path)}) as root_span:
            trace_id = root_span.trace_id
            try:
                runpy.run_path(str(resolved_path), run_name="__main__")
            except SystemExit as se:
                if se.code not in (0, None):
                    root_span.record_exception(se)
                    script_error = se
            except Exception as exc:
                root_span.record_exception(exc)
                script_error = exc
                raise
    finally:
        sys.argv = orig_argv
        if orig_path0:
            sys.path[0] = orig_path0
        
        # Ensure all buffered spans are safely persisted to DuckDB
        tracer.flush()
        tracer.shutdown()

    # Display execution telemetry summary
    if trace_id:
        from nanotrace.storage.duckdb_sink import DuckDBSink
        sink = DuckDBSink(db_path=db_path)
        try:
            spans = sink.get_trace_tree(trace_id)
        finally:
            sink.close()

        if spans:
            root_sp = spans[0]
            tot_tokens = sum(int(s.get("gen_ai_total_tokens") or 0) for s in spans)
            tot_cost = sum(float(s.get("gen_ai_cost_usd") or 0.0) for s in spans)

            summary_table = Table(title="⚡️ Execution Telemetry Summary", border_style="green")
            summary_table.add_column("Property", style="cyan")
            summary_table.add_column("Value", style="bold")
            summary_table.add_row("Trace ID", trace_id)
            summary_table.add_row("Root Operation", root_sp.get("name", script_name))
            summary_table.add_row("Total Spans", str(len(spans)))
            summary_table.add_row("Turnaround Latency", f"{root_sp.get('duration_ms', 0):.2f} ms")
            summary_table.add_row("Tokens Consumed", f"{tot_tokens:,}")
            summary_table.add_row("Estimated Spend", f"${tot_cost:.5f}")
            summary_table.add_row("Status", "[green]SUCCESS[/green]" if not script_error else "[red]FAILED[/red]")
            console.print(summary_table)

            console.print(f"\n[green]✓ Trace recorded successfully![/green] Inspect via:")
            console.print(f"  [bold]nanotrace ui --port {port}[/bold]")
            console.print(f"  [bold]nanotrace export-capsule {trace_id}[/bold]\n")

            if export_capsule:
                capsule_file = export_trace_capsule(trace_id=trace_id, db_path=db_path)
                console.print(f"[green]✓ Exported standalone HTML capsule:[/green] [bold]{capsule_file}[/bold]")

    if open_ui:
        from nanotrace.ui.server import start_ui
        start_ui(db_path=db_path, port=port)


@app.command("eval")
def run_evals(
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """Run local heuristic evaluations on all traces."""
    sink = DuckDBSink(db_path=db_path)
    try:
        spans = sink.query("SELECT * FROM spans")
        if not spans:
            console.print("[yellow]No spans found to evaluate.[/yellow]")
            return

        results = LocalHeuristicEvaluator.evaluate_all(spans)
        table = Table(title="⚡️ NanoTrace Evaluation Diagnostics", border_style="magenta")
        table.add_column("Heuristic Metric", style="cyan")
        table.add_column("Score", style="yellow")
        table.add_column("Status")
        table.add_column("Details", style="dim")

        for r in results:
            status_text = "[green]PASSED[/green]" if r.passed else "[red]FAILED[/red]"
            table.add_row(
                r.metric_name,
                f"{r.score * 100:.1f}%",
                status_text,
                str(r.details),
            )

        console.print(table)
    finally:
        sink.close()


@app.command("ingest")
def ingest_file(
    file_path: str = typer.Argument(..., help="Path to JSON, JSONL, or text log file to ingest"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """Ingest and self-heal messy or non-standard telemetry from a file."""
    import os
    from pathlib import Path
    from nanotrace.core.healer import TraceHealer

    if not os.path.exists(file_path):
        console.print(f"[red]Error: File not found: {file_path}[/red]")
        raise typer.Exit(code=1)

    content = Path(file_path).read_text(encoding="utf-8")
    healer = TraceHealer()
    spans = healer.parse_and_heal(content)

    if not spans:
        console.print("[yellow]Warning: No spans could be extracted from file.[/yellow]")
        return

    sink = DuckDBSink(db_path=db_path)
    try:
        inserted = sink.write_spans(spans)
        console.print(f"[green]✓ Successfully healed and ingested [bold]{inserted}[/bold] spans into DuckDB![/green]")
    finally:
        sink.close()


@app.command("demo")
def run_demo(
    open_ui: bool = typer.Option(False, "--ui", "-u", help="Automatically launch web dashboard after running demo"),
    port: int = typer.Option(7777, "--port", "-p", help="Port number for dashboard"),
):
    """Run the complete showcase suite: 6 agents, multi-agent council, and 10-point validator."""
    from showcase.run_all_and_validate import run_full_suite, DB_PATH
    run_full_suite()
    if open_ui:
        from nanotrace.ui.server import start_ui
        start_ui(db_path=DB_PATH, port=port)


if __name__ == "__main__":
    app()
