"""NanoTrace Command Line Interface (CLI).

Provides commands to view stats, launch the web dashboard, run SQL queries,
and export trace datasets to Parquet or JSONL.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from nanotrace.storage.duckdb_sink import DuckDBSink
from nanotrace.eval.heuristics import LocalHeuristicEvaluator

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
    output: str = typer.Option("./traces.parquet", "--output", "-o", help="Output file path (.parquet)"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """Export all stored traces into an optimized Parquet dataset."""
    sink = DuckDBSink(db_path=db_path)
    try:
        sink.export_parquet(output)
        console.print(f"[green]✓ Successfully exported traces to:[/green] [bold]{output}[/bold]")
    finally:
        sink.close()


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


if __name__ == "__main__":
    app()
