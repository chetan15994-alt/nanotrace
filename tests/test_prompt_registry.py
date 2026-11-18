"""Testing Round 1: Prompt Template Modeling, Compilation & Registry CRUD."""

import os
import pytest
import tempfile

from nanotrace.exceptions import PromptError
from nanotrace.prompts.models import PromptTemplate
from nanotrace.prompts.registry import PromptRegistry


def test_prompt_template_variable_extraction():
    """Verify that variables are automatically extracted from {{var_name}} placeholders."""
    p = PromptTemplate(
        name="financial_analyzer",
        template="Analyze company {{company_name}} for fiscal year {{year}}. Compare against {{benchmark_index}}.",
        version="v1.0.0",
    )
    assert p.variables == ["company_name", "year", "benchmark_index"]
    assert p.version == "v1.0.0"


def test_prompt_template_compilation_success_and_strict_error():
    """Verify variable interpolation and strict validation."""
    p = PromptTemplate(
        name="support_reply",
        template="Hello {{customer}}, your ticket #{{ticket_id}} is {{status}}.",
    )

    # 1. Successful compilation
    compiled = p.compile(customer="Sarah Connor", ticket_id="101", status="RESOLVED")
    assert compiled == "Hello Sarah Connor, your ticket #101 is RESOLVED."

    # 2. Non-strict compilation preserves unsupplied variables
    partial = p.compile(strict=False, customer="John")
    assert partial == "Hello John, your ticket #{{ticket_id}} is {{status}}."

    # 3. Strict compilation raises PromptError on missing variables
    with pytest.raises(PromptError, match="Missing required prompt variable"):
        p.compile(strict=True, customer="John")


def test_prompt_registry_crud_and_versioning(tmp_path):
    """Verify saving, retrieving, and versioning prompt templates in DuckDB."""
    db_file = str(tmp_path / "prompts_test.duckdb")
    reg = PromptRegistry(db_path=db_file)

    # 1. Save v1.0.0
    p1 = PromptTemplate(
        name="sales_outreach",
        version="v1.0.0",
        template="Hi {{name}}, would you like a demo of {{product}}?",
        tags=["dev"],
    )
    saved1 = reg.save(p1)
    assert saved1.prompt_id.startswith("pmt_")

    # 2. Save v1.1.0 with different wording and staging tag
    p2 = PromptTemplate(
        name="sales_outreach",
        version="v1.1.0",
        template="Greetings {{name}}! Experience {{product}} today for free.",
        tags=["staging"],
    )
    reg.save(p2)

    # 3. Retrieve latest version
    latest = reg.get("sales_outreach")
    assert latest.version == "v1.1.0"
    assert "Greetings" in latest.template

    # 4. Retrieve by specific version
    v1 = reg.get("sales_outreach", version="v1.0.0")
    assert v1.version == "v1.0.0"
    assert "demo" in v1.template

    # 5. Retrieve by tag
    staging = reg.get("sales_outreach", tag="staging")
    assert staging.version == "v1.1.0"

    # 6. List versions
    versions = reg.list_versions("sales_outreach")
    assert len(versions) == 2
    assert {v.version for v in versions} == {"v1.0.0", "v1.1.0"}


def test_prompt_registry_tag_promotion_and_uniqueness(tmp_path):
    """Verify that promoting a version to a tag (e.g. 'production') strips that tag from other versions."""
    db_file = str(tmp_path / "prompts_promo.duckdb")
    reg = PromptRegistry(db_path=db_file)

    # Create v1.0.0 as production
    reg.save(PromptTemplate(
        name="risk_scorer",
        version="v1.0.0",
        template="Score risk for {{entity}}.",
        tags=["production"],
    ))

    # Create v2.0.0 as staging
    reg.save(PromptTemplate(
        name="risk_scorer",
        version="v2.0.0",
        template="Comprehensive risk audit for {{entity}} with portfolio variance.",
        tags=["staging"],
    ))

    # Ensure v1.0.0 is production
    prod_v1 = reg.get("risk_scorer", tag="production")
    assert prod_v1.version == "v1.0.0"

    # Promote v2.0.0 to production
    promoted = reg.promote("risk_scorer", version="v2.0.0", tag="production")
    assert promoted.version == "v2.0.0"
    assert "production" in promoted.tags

    # Now get by tag 'production' must return v2.0.0
    prod_now = reg.get("risk_scorer", tag="production")
    assert prod_now.version == "v2.0.0"

    # And v1.0.0 must no longer have the 'production' tag
    v1_reloaded = reg.get("risk_scorer", version="v1.0.0")
    assert "production" not in v1_reloaded.tags


def test_prompt_registry_cache_speed_and_invalidation(tmp_path):
    """Verify in-memory caching provides microsecond lookups."""
    db_file = str(tmp_path / "prompts_cache.duckdb")
    reg = PromptRegistry(db_path=db_file)

    reg.save(PromptTemplate(
        name="fast_prompt",
        version="v1.0.0",
        template="Quick answer for {{query}}",
        tags=["production"],
    ))

    # First lookup populates cache
    p1 = reg.get("fast_prompt", tag="production")

    # Second lookup hits cache directly
    import time
    t0 = time.perf_counter_ns()
    p2 = reg.get("fast_prompt", tag="production")
    elapsed_us = (time.perf_counter_ns() - t0) / 1000.0

    assert p1.template == p2.template
    # Cache lookup should be under 15 µs
    assert elapsed_us < 20.0
