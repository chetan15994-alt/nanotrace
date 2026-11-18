"""Testing Round 4: CLI Commands for Prompt Studio and Feedback Collector."""

import pytest
from typer.testing import CliRunner

from nanotrace.cli import app
from nanotrace.prompts import PromptRegistry, PromptTemplate
from nanotrace.feedback import FeedbackCollector

runner = CliRunner()


@pytest.fixture
def cli_phase4_env(tmp_path):
    db_file = str(tmp_path / "cli_p4.duckdb")
    # Seed prompt
    reg = PromptRegistry(db_path=db_file)
    reg.save(PromptTemplate(
        name="contract_summarizer",
        version="v1.0.0",
        template="Summarize contract clauses for {{client}}.",
        tags=["staging"],
    ))

    # Seed feedback
    collector = FeedbackCollector(db_path=db_file)
    collector.record(trace_id="tr_sample_01", score=1.0, comment="Very helpful summary!")

    return db_file


def test_cli_prompt_list_and_get(cli_phase4_env):
    db_file = cli_phase4_env

    # 1. List prompts
    res = runner.invoke(app, ["prompt", "list", "--db", db_file])
    assert res.exit_code == 0
    assert "contract_summarizer" in res.stdout
    assert "v1.0.0" in res.stdout

    # 2. Get prompt
    res2 = runner.invoke(app, ["prompt", "get", "contract_summarizer", "--db", db_file])
    assert res2.exit_code == 0
    assert "Summarize contract clauses" in res2.stdout


def test_cli_prompt_set_and_promote(cli_phase4_env):
    db_file = cli_phase4_env

    # 1. Set v2.0.0
    res = runner.invoke(app, [
        "prompt", "set", "contract_summarizer",
        "--template", "Strict legal summary for {{client}} and {{counterparty}}.",
        "--version", "v2.0.0",
        "--db", db_file,
    ])
    assert res.exit_code == 0
    assert "Saved prompt contract_summarizer (v2.0.0)" in res.stdout

    # 2. Promote v2.0.0 to production
    res2 = runner.invoke(app, [
        "prompt", "promote", "contract_summarizer", "v2.0.0",
        "--tag", "production",
        "--db", db_file,
    ])
    assert res2.exit_code == 0
    assert "Successfully promoted contract_summarizer (v2.0.0) to production" in res2.stdout


def test_cli_feedback_record_and_list(cli_phase4_env):
    db_file = cli_phase4_env

    # 1. Record feedback
    res = runner.invoke(app, [
        "feedback", "record", "tr_sample_02",
        "--score", "-1.0",
        "--comment", "High latency on tool call",
        "--db", db_file,
    ])
    assert res.exit_code == 0
    assert "Recorded 👎 feedback" in res.stdout

    # 2. List feedback
    res2 = runner.invoke(app, ["feedback", "list", "--db", db_file])
    assert res2.exit_code == 0
    assert "tr_sample_01" in res2.stdout
    assert "tr_sample_02" in res2.stdout

    # 3. Stats
    res3 = runner.invoke(app, ["feedback", "stats", "--db", db_file])
    assert res3.exit_code == 0
    assert "Feedback Sentiment Analytics" in res3.stdout
    assert "Total Feedback" in res3.stdout
