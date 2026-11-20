"""Unit tests for Team Collaborative Prompt Registry and Golden Dataset Hub."""

import json
import os
import tempfile
import pytest

from nanotrace.server.models import PromptTag, Workspace
from nanotrace.server.prompts import PromptRegistryEngine
from nanotrace.server.datasets import GoldenDatasetEngine
from nanotrace.server.storage import ServerMetadataStorage


@pytest.fixture
def temp_engines():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "metadata.db")
        storage = ServerMetadataStorage(db_path=db_path)
        ws = storage.create_workspace(
            Workspace(name="Prompt Test Org", slug="prompt-test", owner_email="team@prompt.com", plan="team")
        )
        prompt_engine = PromptRegistryEngine(storage=storage)
        dataset_engine = GoldenDatasetEngine(storage=storage)
        yield {
            "storage": storage,
            "ws": ws,
            "prompts": prompt_engine,
            "datasets": dataset_engine,
        }


def test_prompt_registry_lifecycle_and_diffing(temp_engines):
    prompts = temp_engines["prompts"]
    ws_id = temp_engines["ws"].workspace_id
    proj_id = "proj_support"

    # 1. Variable extraction
    template_v1 = "Hello {{user_name}}, your order status for order #{order_id} is: {{status}}."
    vars_found = prompts.extract_variables(template_v1)
    assert vars_found == ["user_name", "order_id", "status"]

    # 2. Create version 1
    p, v1 = prompts.create_or_update_prompt(
        workspace_id=ws_id,
        project_id=proj_id,
        name="order_status_prompt",
        template=template_v1,
        author_email="alice@company.com",
        commit_message="Initial customer status template",
        semver="1.0.0",
        tags=[PromptTag.STAGING],
    )
    assert p.latest_version == 1
    assert v1.version_number == 1
    assert v1.semver == "1.0.0"

    # 3. Create version 2 with modified template
    template_v2 = "Hi {{user_name}}, your order #{order_id} is currently {{status}}. Tracking: {{tracking_url}}"
    p2, v2 = prompts.create_or_update_prompt(
        workspace_id=ws_id,
        project_id=proj_id,
        name="order_status_prompt",
        template=template_v2,
        author_email="bob@company.com",
        commit_message="Added tracking url support",
        semver="1.1.0",
        tags=[PromptTag.PRODUCTION],
    )
    assert p2.latest_version == 2
    assert len(p2.versions) == 2

    # 4. Line-by-line diff
    diff_result = prompts.compute_diff(v1, v2)
    assert diff_result["from_version"] == 1
    assert diff_result["to_version"] == 2
    assert diff_result["additions"] > 0
    assert "unified_diff" in diff_result

    # 5. Template Rendering
    rendered = prompts.render_template(
        template_v2,
        {
            "user_name": "Samantha",
            "order_id": "9921",
            "status": "Shipped",
            "tracking_url": "https://track.pkg/9921",
        },
    )
    assert "Hi Samantha, your order #9921 is currently Shipped." in rendered
    assert "https://track.pkg/9921" in rendered

    # 6. Tag Promotion & Retrieval
    prod_version = prompts.get_prompt_by_tag(ws_id, proj_id, "order_status_prompt", PromptTag.PRODUCTION)
    assert prod_version is not None
    assert prod_version.version_number == 2


def test_golden_dataset_curation_and_promotion(temp_engines):
    datasets = temp_engines["datasets"]
    ws_id = temp_engines["ws"].workspace_id
    proj_id = "proj_evals"

    # 1. Create Golden Dataset
    ds = datasets.create_dataset(
        workspace_id=ws_id,
        project_id=proj_id,
        name="payment_support_golden_v1",
        description="Regression test suite for payment queries",
        version="1.0.0",
    )
    assert ds.name == "payment_support_golden_v1"

    # 2. Promote Production Trace to Gold
    span_data = {
        "span_id": "sp_prod_881",
        "trace_id": "tr_prod_881",
        "input": "Can I cancel my subscription and get a refund?",
        "output": "Yes, our refund policy permits full refunds within 14 days.",
        "duration_ms": 1200.0,
        "cost_usd": 0.003,
    }

    case = datasets.promote_trace_to_gold(
        dataset_id=ds.dataset_id,
        span_data=span_data,
        curated_by="lead_engineer",
        expected_output="Refund permitted within 14 days.",
        custom_assertions={"must_contain": ["refund", "14 days"]},
    )
    assert case.source_trace_id == "tr_prod_881"
    assert case.assertions["max_duration_ms"] == 1800.0  # 1.5x recorded duration

    # 3. Export to JSONL
    jsonl = datasets.export_dataset_jsonl(ds.dataset_id)
    assert "Can I cancel my subscription" in jsonl
    parsed = json.loads(jsonl.splitlines()[0])
    assert parsed["case_id"] == case.case_id

    # 4. Export to CSV
    csv_str = datasets.export_dataset_csv(ds.dataset_id)
    assert "input_prompt" in csv_str
    assert "Can I cancel my subscription" in csv_str
