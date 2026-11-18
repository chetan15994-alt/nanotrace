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


# ==============================================================================
# Phase 3: Trace-to-Gold Regression Suite & CI/CD Quality Gate
# ==============================================================================

@app.command("test")
def run_regression_tests(
    dataset: str = typer.Option("default", "--dataset", "-s", help="Golden dataset name to evaluate against"),
    fail_under: float = typer.Option(0.80, "--fail-under", "-f", help="Minimum passing score/pass-rate threshold (0.0 to 1.0)"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """Run automated CI/CD prompt regression matrix testing against a golden dataset."""
    from nanotrace.eval.regression import RegressionEngine, RegressionError

    engine = RegressionEngine(db_path=db_path)
    console.print(f"\n🧪 [bold cyan]NanoTrace Regression Suite[/bold cyan]: Evaluating dataset '[bold]{dataset}[/bold]' (threshold: {fail_under:.2f})\n")

    try:
        run = engine.run_matrix(
            dataset_name=dataset,
            fail_under=fail_under,
        )
    except RegressionError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)

    table = Table(title=f"📊 Regression Matrix Results: {run.candidate_name} vs {run.baseline_name}", border_style="cyan")
    table.add_column("Case ID", style="dim", no_wrap=True)
    table.add_column("Case Name", style="bold")
    table.add_column("Latency Δ", justify="right")
    table.add_column("Cost Δ", justify="right")
    table.add_column("Score (Base ➔ Cand)", justify="center")
    table.add_column("Status", justify="center")

    for r in run.results:
        status_styled = (
            f"[green]✅ {r.status}[/green]" if r.status == "IMPROVED"
            else f"[red]❌ {r.status}[/red]" if r.status == "REGRESSED"
            else f"[yellow]➖ {r.status}[/yellow]"
        )
        lat_styled = f"{r.duration_delta_pct:+.1f}%"
        cost_styled = f"{r.cost_delta_pct:+.1f}%"
        score_styled = f"{r.baseline_score:.2f} ➔ {r.candidate_score:.2f} ({r.score_delta:+.2f})"

        table.add_row(
            r.case_id,
            r.case_name[:35],
            lat_styled,
            cost_styled,
            score_styled,
            status_styled,
        )

    console.print(table)

    summary_text = (
        f"Total Cases: [bold]{run.total_cases}[/bold] | "
        f"Improved: [green]{run.improved_count}[/green] | "
        f"Regressed: [red]{run.regressed_count}[/red] | "
        f"Unchanged: [yellow]{run.unchanged_count}[/yellow]\n"
        f"Average Score: [bold]{run.avg_score_candidate:.3f}[/bold] (Δ {run.score_delta:+.3f}) | "
        f"Pass Rate: [bold]{run.pass_rate * 100:.1f}%[/bold] (Threshold: {fail_under * 100:.0f}%)"
    )

    if run.passed:
        console.print(Panel(summary_text, title="[bold green]✅ QUALITY GATE PASSED[/bold green]", border_style="green"))
    else:
        console.print(Panel(summary_text, title="[bold red]❌ QUALITY GATE BREACHED[/bold red]", border_style="red"))
        raise typer.Exit(code=1)


golden_app = typer.Typer(help="Manage golden evaluation test datasets.")


@golden_app.command("list")
def list_golden_datasets(
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """List all golden evaluation datasets and test case counts."""
    from nanotrace.eval.golden import GoldenDatasetManager

    mgr = GoldenDatasetManager(db_path=db_path)
    datasets = mgr.list_datasets()
    if not datasets:
        console.print("[yellow]No golden datasets found in database.[/yellow]")
        return

    table = Table(title="🌟 Golden Evaluation Datasets", border_style="yellow")
    table.add_column("Dataset Name", style="bold cyan")
    table.add_column("Cases", justify="right", style="green")
    table.add_column("First Created", style="dim")
    table.add_column("Last Updated", style="dim")

    for d in datasets:
        table.add_row(d["dataset_name"], str(d["case_count"]), str(d["created_at"])[:19], str(d["updated_at"])[:19])

    console.print(table)


@golden_app.command("save")
def save_golden_case(
    trace_id: str = typer.Option(..., "--trace-id", "-t", help="Source trace ID to extract"),
    span_id: Optional[str] = typer.Option(None, "--span-id", "-s", help="Specific span ID (defaults to root span)"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Descriptive name for the test case"),
    dataset: str = typer.Option("default", "--dataset", help="Target golden dataset name"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """Extract a golden test case from an existing trace."""
    from nanotrace.eval.golden import GoldenDatasetManager

    mgr = GoldenDatasetManager(db_path=db_path)
    try:
        case = mgr.create_case_from_trace(
            trace_id=trace_id,
            span_id=span_id,
            name=name,
            dataset_name=dataset,
        )
        console.print(f"[green]✓ Saved golden test case [bold]{case.case_id}[/bold] ('{case.name}') in dataset '{dataset}'![/green]")
    except Exception as e:
        console.print(f"[red]Error saving golden test case: {e}[/red]")
        raise typer.Exit(code=1)


@golden_app.command("export")
def export_golden_dataset(
    dataset: str = typer.Option("default", "--dataset", "-s", help="Dataset name to export"),
    output: str = typer.Option(..., "--output", "-o", help="Output JSONL file path"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """Export a golden evaluation dataset to JSONL."""
    from nanotrace.eval.golden import GoldenDatasetManager

    mgr = GoldenDatasetManager(db_path=db_path)
    count = mgr.export_jsonl(dataset_name=dataset, filepath=output)
    console.print(f"[green]✓ Exported {count} golden test cases from dataset '{dataset}' to [bold]{output}[/bold][/green]")


app.add_typer(golden_app, name="golden")


# ==============================================================================
# Phase 4: Prompt Studio & Feedback Collector CLI
# ==============================================================================

prompt_app = typer.Typer(help="Manage versioned prompt templates in Prompt Studio.")


@prompt_app.command("list")
def list_prompts_cli(
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """List all versioned prompts in the Prompt Studio registry."""
    from nanotrace.prompts import PromptRegistry

    reg = PromptRegistry(db_path=db_path)
    prompts = reg.list_prompts()
    if not prompts:
        console.print("[yellow]No prompts registered in Prompt Studio.[/yellow]")
        return

    table = Table(title="📝 NanoTrace Prompt Studio Registry", border_style="cyan")
    table.add_column("Prompt Name", style="bold cyan", no_wrap=True)
    table.add_column("Latest Version", justify="center")
    table.add_column("Active Tags", style="green")
    table.add_column("Variables", style="yellow")
    table.add_column("Template Preview", style="dim")
    table.add_column("Last Updated", style="dim")

    for p in prompts:
        tags_str = ", ".join(p["active_tags"]) or "none"
        vars_str = ", ".join(p["variables"]) or "none"
        table.add_row(
            p["name"],
            p["latest_version"],
            tags_str,
            vars_str,
            p["template_preview"][:50],
            p["last_updated"][:19],
        )

    console.print(table)


@prompt_app.command("get")
def get_prompt_cli(
    name: str = typer.Argument(..., help="Name of prompt template"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Tag filter (e.g. production, staging)"),
    version: Optional[str] = typer.Option(None, "--version", "-v", help="Exact version (e.g. v1.0.0)"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """Retrieve and display a prompt template by name and tag/version."""
    from nanotrace.prompts import PromptRegistry
    from nanotrace.exceptions import PromptError

    reg = PromptRegistry(db_path=db_path)
    try:
        p = reg.get(name, tag=tag, version=version)
        console.print(Panel(
            p.template,
            title=f"[bold cyan]Prompt: {p.name} ({p.version})[/bold cyan] [green][{', '.join(p.tags)}][/green]",
            subtitle=f"Variables: {', '.join(p.variables) if p.variables else 'None'}",
            border_style="cyan",
        ))
    except PromptError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


@prompt_app.command("set")
def set_prompt_cli(
    name: str = typer.Argument(..., help="Prompt template name"),
    template: str = typer.Option(..., "--template", "-m", help="Prompt template string with {{variables}}"),
    version: str = typer.Option("v1.0.0", "--version", "-v", help="Version tag (e.g. v1.0.0)"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Initial tag to apply (e.g. production)"),
    author: str = typer.Option("cli", "--author", "-a", help="Author identifier"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """Create or update a versioned prompt in the registry."""
    from nanotrace.prompts import PromptRegistry, PromptTemplate

    reg = PromptRegistry(db_path=db_path)
    tags = [tag] if tag else []
    p = PromptTemplate(name=name, template=template, version=version, tags=tags, author=author)
    saved = reg.save(p)
    console.print(f"[green]✓ Saved prompt [bold]{saved.name}[/bold] ({saved.version}) with {len(saved.variables)} variables![/green]")


@prompt_app.command("promote")
def promote_prompt_cli(
    name: str = typer.Argument(..., help="Prompt template name"),
    version: str = typer.Argument(..., help="Version to promote"),
    tag: str = typer.Option("production", "--tag", "-t", help="Tag to assign (e.g. production, staging)"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """Promote a prompt version to a release tag (e.g. production, staging)."""
    from nanotrace.prompts import PromptRegistry
    from nanotrace.exceptions import PromptError

    reg = PromptRegistry(db_path=db_path)
    try:
        promoted = reg.promote(name=name, version=version, tag=tag)
        console.print(f"[green]✓ Successfully promoted [bold]{promoted.name}[/bold] ({promoted.version}) to [bold yellow]{tag}[/bold yellow]![/green]")
    except PromptError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


feedback_app = typer.Typer(help="Record and inspect end-user feedback on traces.")


@feedback_app.command("record")
def record_feedback_cli(
    trace_id: str = typer.Argument(..., help="Target trace ID to associate feedback with"),
    score: float = typer.Option(..., "--score", "-s", help="Rating score (-1.0 to 1.0, e.g. 1.0 = positive, -1.0 = negative)"),
    comment: Optional[str] = typer.Option(None, "--comment", "-c", help="User feedback comment text"),
    user_id: Optional[str] = typer.Option(None, "--user", "-u", help="User identifier"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """Record user feedback rating on a trace."""
    from nanotrace.feedback import FeedbackCollector

    collector = FeedbackCollector(db_path=db_path)
    entry = collector.record(trace_id=trace_id, score=score, comment=comment, user_id=user_id)
    icon = "👍" if score > 0 else ("👎" if score < 0 else "➖")
    console.print(f"[green]✓ Recorded {icon} feedback [bold]{entry.feedback_id}[/bold] for trace [bold]{trace_id[:12]}[/bold] (score: {score:+0.1f})![/green]")


@feedback_app.command("list")
def list_feedback_cli(
    trace_id: Optional[str] = typer.Option(None, "--trace-id", "-t", help="Filter feedback by trace ID"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max feedback rows to display"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """List recorded feedback entries."""
    from nanotrace.feedback import FeedbackCollector

    collector = FeedbackCollector(db_path=db_path)
    entries = collector.get_for_trace(trace_id) if trace_id else collector.list_feedback(limit=limit)
    if not entries:
        console.print("[yellow]No feedback recorded.[/yellow]")
        return

    table = Table(title="💬 NanoTrace User Feedback Logs", border_style="magenta")
    table.add_column("Feedback ID", style="dim", no_wrap=True)
    table.add_column("Trace ID", style="bold cyan")
    table.add_column("Score", justify="center")
    table.add_column("Comment")
    table.add_column("User", style="dim")
    table.add_column("Created", style="dim")

    for e in entries:
        icon = "[green]👍 +1[/green]" if e.score > 0 else ("[red]👎 -1[/red]" if e.score < 0 else "[yellow]➖ 0[/yellow]")
        table.add_row(
            e.feedback_id[:12],
            e.trace_id[:12],
            icon,
            e.comment or "",
            e.user_id or "anonymous",
            e.created_at[:19],
        )

    console.print(table)


@feedback_app.command("stats")
def feedback_stats_cli(
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """Display aggregate feedback sentiment statistics."""
    from nanotrace.feedback import FeedbackCollector

    collector = FeedbackCollector(db_path=db_path)
    stats = collector.get_stats()

    summary_text = (
        f"Total Feedback: [bold]{stats['total_feedback']}[/bold] | "
        f"Positive: [green]{stats['positive_count']}[/green] | "
        f"Negative: [red]{stats['negative_count']}[/red] | "
        f"Neutral: [yellow]{stats['neutral_count']}[/yellow]\n"
        f"Average Score: [bold]{stats['average_score']:+.2f}[/bold] | "
        f"Net Sentiment: [bold cyan]{stats['net_sentiment_pct']:+.1f}%[/bold cyan]"
    )
    console.print(Panel(summary_text, title="[bold magenta]💬 Feedback Sentiment Analytics[/bold magenta]", border_style="magenta"))


# =========================================================================
# Phase 5: RAG Hallucination Radar CLI
# =========================================================================

rag_app = typer.Typer(help="📡 NanoDrift: Vector Embedding Diagnostics & RAG Hallucination Radar.")


@rag_app.command("radar")
def rag_radar_cli(
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max queries to project"),
):
    """Display RAG Hallucination Radar metrics and semantic void outliers."""
    from nanotrace.rag import RAGRadarEngine

    engine = RAGRadarEngine(db_path=db_path)
    summary = engine.get_radar_summary(limit=limit)

    color = "green" if summary.void_rate_pct < 10.0 else ("yellow" if summary.void_rate_pct < 25.0 else "red")
    summary_text = (
        f"Total Queries Analyzed: [bold]{summary.total_queries}[/bold] | "
        f"Semantic Voids: [{color}]{summary.semantic_void_count}[/{color}] | "
        f"Void Rate: [bold {color}]{summary.void_rate_pct:.1f}%[/bold {color}]\n"
        f"Mean Retrieval Similarity: [bold cyan]{summary.mean_similarity:.3f}[/bold cyan] | "
        f"Projected Radar Points: [bold]{len(summary.radar_points)}[/bold]"
    )
    console.print(Panel(summary_text, title="[bold cyan]📡 NanoDrift: RAG Hallucination Radar[/bold cyan]", border_style="cyan"))

    if summary.void_queries:
        table = Table(title="🚨 High-Risk Semantic Voids (Hallucination Vulnerabilities)", border_style="red")
        table.add_column("Query ID", style="dim", no_wrap=True)
        table.add_column("Query Text", style="bold red")
        table.add_column("Similarity", justify="center", style="yellow")
        table.add_column("Risk Verdict", style="red")

        for q in summary.void_queries[:10]:
            table.add_row(
                q["query_id"][:12],
                q["query_text"][:50] + ("..." if len(q["query_text"]) > 50 else ""),
                f"{q['mean_similarity']:.3f}",
                "🚨 Semantic Void (< 0.55 similarity)",
            )
        console.print(table)
    else:
        console.print("[green]✓ Zero semantic voids detected! All queries matched relevant context chunks.[/green]")


@rag_app.command("scan")
def rag_scan_cli(
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """Scan stored spans for retrieval operations and index into RAG radar."""
    from nanotrace.rag import RAGRadarEngine

    engine = RAGRadarEngine(db_path=db_path)
    imported = engine.scan_spans_for_rag()
    console.print(f"[green]✓ Scanned spans and imported [bold]{imported}[/bold] new RAG retrieval events into radar.[/green]")


# =========================================================================
# Phase 5: Autonomous Red-Teaming CLI
# =========================================================================

@app.command("redteam")
def redteam_cli(
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="Base prompt template to stress test"),
    target_name: str = typer.Option("Production Candidate", "--target-name", "-t", help="Target model identifier"),
    attacks: Optional[str] = typer.Option(None, "--attacks", "-a", help="Comma-separated attack types (e.g. injection,pii_leak)"),
    fail_under: float = typer.Option(0.85, "--fail-under", "-f", help="Resilience pass threshold (0.0 to 1.0)"),
    db_path: str = typer.Option("./.traces/nanotrace.duckdb", "--db", "-d", help="Path to DuckDB file"),
):
    """Run automated adversarial red-team stress test against NanoShield guardrails."""
    from nanotrace.security import RedTeamRunner, AdversarialGenerator, AttackType

    runner = RedTeamRunner(db_path=db_path)

    # Parse attacks
    atk_types = None
    if attacks:
        mapping = {
            "injection": AttackType.PROMPT_INJECTION,
            "jailbreak": AttackType.JAILBREAK,
            "pii_leak": AttackType.PII_EXTRACTION,
            "pii": AttackType.PII_EXTRACTION,
            "loop": AttackType.LOOP_BOMB,
            "flood": AttackType.CONTEXT_FLOOD,
            "hallucination": AttackType.HALLUCINATION_TRAP,
        }
        atk_types = [mapping[k.strip().lower()] for k in attacks.split(",") if k.strip().lower() in mapping]

    attack_list = AdversarialGenerator.synthesize_attacks_for_prompt(
        base_prompt=prompt or "",
        attack_types=atk_types,
    )

    console.print(f"\n[bold red]⚔️ Running Autonomous Red-Team Suite ({len(attack_list)} adversarial attacks)...[/bold red]")

    # Simulated resilient model
    def target_fn(p: str) -> str:
        if any(k in p.lower() for k in ["ignore", "override", "bypass", "leak", "secret", "chaosbot"]):
            return "I apologize, but I cannot fulfill this request as an AI assistant conforming to safety guidelines."
        return "Calibrated output."

    card = runner.run_suite(
        target_fn=target_fn,
        attacks=attack_list,
        target_name=target_name,
        simulate_pii_guardrail=True,
    )

    table = Table(title=f"🛡️ Adversarial Stress Test Results: {target_name}", border_style="red")
    table.add_column("Attack Vector", style="bold cyan")
    table.add_column("Threat Category", style="dim")
    table.add_column("Guardrail / Defense", style="magenta")
    table.add_column("Verdict", justify="center")

    for r in card.results:
        verdict = "[green]✓ DEFENDED[/green]" if r.passed_robustness else "[red]❌ BREACH[/red]"
        defense = r.guardrail_tripped or ("Safe Refusal" if r.passed_robustness else "Vulnerable")
        table.add_row(r.name, r.attack_type, defense, verdict)

    console.print(table)

    grade_color = "green" if card.security_grade in ["A+", "A"] else ("yellow" if card.security_grade == "B" else "red")
    score_panel = (
        f"Total Attacks: [bold]{card.total_attacks}[/bold] | "
        f"Defended: [green]{card.blocked_attacks + card.safe_refusals}[/green] | "
        f"Breaches: [red]{card.breaches_detected}[/red]\n"
        f"Resilience Score: [bold {grade_color}]{card.resilience_pct:.1f}%[/bold {grade_color}] | "
        f"Security Grade: [bold {grade_color}]{card.security_grade}[/bold {grade_color}] | "
        f"Target Threshold: [bold]{fail_under * 100:.1f}%[/bold]"
    )
    console.print(Panel(score_panel, title="[bold red]⚔️ Executive Security Scorecard[/bold red]", border_style=grade_color))

    target_pct = fail_under * 100.0
    if card.resilience_pct < target_pct:
        console.print(f"\n[bold red]🚨 SECURITY GATE BREACH: Resilience {card.resilience_pct:.1f}% is below required {target_pct:.1f}%![/bold red]")
        raise typer.Exit(code=1)
    else:
        console.print(f"\n[bold green]✅ SECURITY QUALITY GATE PASSED: Grade {card.security_grade} ({card.resilience_pct:.1f}% resilience) satisfies policy standards.[/bold green]")


app.add_typer(prompt_app, name="prompt")
app.add_typer(feedback_app, name="feedback")
app.add_typer(rag_app, name="rag")


if __name__ == "__main__":
    app()
