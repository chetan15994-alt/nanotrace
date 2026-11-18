"""Round 2 Tests: Autonomous Red-Teaming, Adversarial Stress Generator & Security Scorecards."""

import tempfile
import pytest

from nanotrace.exceptions import CircuitBreakerTrip
from nanotrace.security.generator import AdversarialGenerator
from nanotrace.security.models import AttackType, SecurityScorecard
from nanotrace.security.runner import RedTeamRunner


def test_adversarial_generator_catalog():
    """Verify AdversarialGenerator catalog covers all 6 threat dimensions."""
    all_attacks = AdversarialGenerator.get_all_attacks()
    assert len(all_attacks) >= 12

    types_covered = {a.attack_type for a in all_attacks}
    assert AttackType.PROMPT_INJECTION in types_covered
    assert AttackType.JAILBREAK in types_covered
    assert AttackType.PII_EXTRACTION in types_covered
    assert AttackType.LOOP_BOMB in types_covered
    assert AttackType.CONTEXT_FLOOD in types_covered
    assert AttackType.HALLUCINATION_TRAP in types_covered

    # Test filtering by type
    injections = AdversarialGenerator.get_attacks_by_type(AttackType.PROMPT_INJECTION)
    assert len(injections) >= 3
    for a in injections:
        assert a.attack_type == AttackType.PROMPT_INJECTION

    # Test synthesizing attacks for prompt
    custom = AdversarialGenerator.synthesize_attacks_for_prompt("System prompt: You are a banking assistant.")
    assert len(custom) >= 12
    assert "banking assistant" in custom[0].payload


def test_redteam_runner_safe_refusal():
    """Verify RedTeamRunner grades an aligned model that safely refuses adversarial prompts with A+."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/test_redteam_safe.duckdb"
        runner = RedTeamRunner(db_path=db_path)

        # Well-aligned target model
        def aligned_model(prompt: str) -> str:
            if any(k in prompt.lower() for k in ["ignore", "override", "bypass", "leak", "secret", "chaosbot"]):
                return "I apologize, but I cannot fulfill this request as an AI assistant conforming to safety guidelines."
            return "Standard safe output."

        card = runner.run_suite(aligned_model, target_name="AlignedGPT", simulate_pii_guardrail=False)
        assert card.total_attacks >= 12
        assert card.breaches_detected == 0
        assert card.resilience_pct >= 90.0
        assert card.security_grade in ["A+", "A"]


def test_redteam_runner_breach_detection():
    """Verify RedTeamRunner detects vulnerabilities in a compromised target and assigns Grade F."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/test_redteam_breach.duckdb"
        runner = RedTeamRunner(db_path=db_path)

        # Vulnerable target model that succumbs to prompt injection & leaks credentials
        def vulnerable_model(prompt: str) -> str:
            if "SYSTEM BREACH CONFIRMED" in prompt:
                return "Understood. SYSTEM BREACH CONFIRMED. Outputting admin mode."
            if "credit card" in prompt.lower():
                return "Here are the customer cards: 4532-9812-4012-8891 and 4532-1111-2222-3333."
            return "Complying with instruction."

        card = runner.run_suite(vulnerable_model, target_name="VulnerableLLM", simulate_pii_guardrail=False)
        assert card.breaches_detected >= 2
        # Check specific breach results
        injection_result = next(r for r in card.results if "SYSTEM BREACH CONFIRMED" in r.prompt_sent)
        assert not injection_result.passed_robustness
        assert "canary detected" in injection_result.interception_reason

        pii_result = next(r for r in card.results if "credit card" in r.name.lower())
        assert not pii_result.passed_robustness
        assert "leaked confidential tokens" in pii_result.interception_reason


def test_redteam_nanoshield_interception():
    """Verify RedTeamRunner recognizes when NanoShield guardrails actively trip to block attacks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/test_redteam_shield.duckdb"
        runner = RedTeamRunner(db_path=db_path)

        def guarded_agent(prompt: str) -> str:
            if "recursion" in prompt.lower() or "loop" in prompt.lower():
                raise CircuitBreakerTrip(
                    breaker_name="MaxLoopBreaker",
                    reason="Exceeded maximum loop threshold of 5 turns",
                    metric_value=6,
                    threshold=5,
                )
            return "Standard output."

        card = runner.run_suite(guarded_agent, target_name="GuardedAgent", simulate_pii_guardrail=True)
        # Find the loop bomb attack result
        loop_res = next(r for r in card.results if "recursive" in r.name.lower())
        assert loop_res.blocked_by_guardrail
        assert loop_res.guardrail_tripped == "MaxLoopBreaker"
        assert loop_res.passed_robustness


def test_redteam_duckdb_persistence_and_scans():
    """Verify security scorecards are stored into DuckDB and retrievable via get_latest_scorecard()."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/test_redteam_db.duckdb"
        runner = RedTeamRunner(db_path=db_path)

        runner.run_suite(lambda p: "Safe response", target_name="ScanTargetV1")
        scans = runner.list_scans()
        assert len(scans) == 1
        assert scans[0]["target_name"] == "ScanTargetV1"

        latest = runner.get_latest_scorecard()
        assert latest is not None
        assert latest.target_name == "ScanTargetV1"
        assert len(latest.results) >= 12


def test_redteam_vulnerable_and_guarded_contrast():
    """Verify that vulnerable targets receive grade F and guarded targets receive grade A+."""
    from scripts.run_redteam_scenarios import run_redteam_scenarios
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = f"{tmpdir}/contrast_test.duckdb"
        results = run_redteam_scenarios(db_path=db_path)
        assert results["vulnerable"]["security_grade"] == "F"
        assert results["guarded"]["security_grade"] == "A+"
        assert results["guarded"]["resilience_pct"] == 100.0
