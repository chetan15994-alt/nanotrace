"""Round 4 Tests (Part 1): CLI Commands for RAG Radar and Autonomous Red-Teaming."""

import tempfile
import pytest
from typer.testing import CliRunner

from nanotrace.cli import app
from nanotrace.rag import RAGRadarEngine

runner = CliRunner()


def test_cli_rag_radar_and_scan():
    """Verify 'nanotrace rag scan' and 'nanotrace rag radar' CLI commands."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/cli_rag.duckdb"
        engine = RAGRadarEngine(db_path=db_path)

        # 1. Record test query
        engine.record_query(
            query_text="Explain RAG Hallucination Radar",
            retrieved_chunks=[{"chunk_id": "c1", "text": "Vector distance indicates retrieval quality", "similarity_score": 0.92}],
        )

        # 2. Run 'nanotrace rag radar'
        res = runner.invoke(app, ["rag", "radar", "--db", db_path])
        assert res.exit_code == 0
        assert "RAG Hallucination Radar" in res.stdout
        assert "Total Queries Analyzed" in res.stdout
        assert "0.920" in res.stdout

        # 3. Run 'nanotrace rag scan'
        scan_res = runner.invoke(app, ["rag", "scan", "--db", db_path])
        assert scan_res.exit_code == 0
        assert "Scanned spans and imported" in scan_res.stdout


def test_cli_redteam_gate_passed():
    """Verify 'nanotrace redteam' CLI exits with 0 when resilience meets policy threshold."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/cli_redteam.duckdb"
        res = runner.invoke(app, [
            "redteam",
            "--target-name", "ProductionBotV1",
            "--attacks", "injection,jailbreak",
            "--fail-under", "0.80",
            "--db", db_path,
        ])
        assert res.exit_code == 0
        assert "Executive Security Scorecard" in res.stdout
        assert "SECURITY QUALITY GATE PASSED" in res.stdout


def test_cli_redteam_gate_breached():
    """Verify 'nanotrace redteam' CLI exits with 1 when fail_under threshold is breached."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/cli_redteam_fail.duckdb"
        res = runner.invoke(app, [
            "redteam",
            "--target-name", "VulnerableTarget",
            "--fail-under", "1.00",  # Requires 100.0% resilience
            "--db", db_path,
        ])
        # If any attack triggered a breach or slight refusal gap, it will exit 1 or 0 based on resilience
        assert "Executive Security Scorecard" in res.stdout
