"""Unit tests for Real-Time Multi-Channel Alert Engine."""

import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from nanotrace.server.alerts import AlertEngine
from nanotrace.server.models import (
    AlertChannelType,
    AlertRule,
    AlertTriggerCondition,
    Workspace,
)
from nanotrace.server.storage import ServerMetadataStorage


@pytest.fixture
def temp_alert_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "metadata.db")
        storage = ServerMetadataStorage(db_path=db_path)
        ws = storage.create_workspace(
            Workspace(name="Alert Org", slug="alert-org", owner_email="admin@alert.com", plan="team")
        )
        engine = AlertEngine(storage=storage)
        yield {"storage": storage, "ws": ws, "engine": engine}


def test_alert_rule_evaluation_and_killswitch_trigger(temp_alert_env):
    storage = temp_alert_env["storage"]
    engine = temp_alert_env["engine"]
    ws_id = temp_alert_env["ws"].workspace_id

    # Create Slack Alert Rule for Killswitches
    rule = AlertRule(
        workspace_id=ws_id,
        name="Emergency Killswitch Alert",
        condition=AlertTriggerCondition.KILLSWITCH_TRIGGERED,
        channel_type=AlertChannelType.SLACK,
        webhook_url="https://hooks.slack.com/services/MOCK/TEST/123",
        rate_limit_cooldown_s=10,
    )
    storage.create_alert_rule(rule)

    # Mock outbound HTTP post
    with patch.object(engine, "_post_json", return_value=(200, None)) as mock_post:
        incidents = engine.evaluate_and_dispatch(
            workspace_id=ws_id,
            project_id=None,
            condition=AlertTriggerCondition.KILLSWITCH_TRIGGERED,
            metric_value=1.0,
            trace_id="tr_runaway_999",
            context={"span_name": "NanoShieldLoopBreaker", "error": "Loop depth 15 exceeded"},
        )
        assert len(incidents) == 1
        assert incidents[0].dispatch_status == "success"
        assert incidents[0].severity == "critical"
        assert mock_post.called

        # Test rate-limiting cooldown (immediate duplicate should be skipped)
        incidents_dup = engine.evaluate_and_dispatch(
            workspace_id=ws_id,
            project_id=None,
            condition=AlertTriggerCondition.KILLSWITCH_TRIGGERED,
            metric_value=1.0,
            trace_id="tr_runaway_1000",
        )
        assert len(incidents_dup) == 0  # Blocked by cooldown!


def test_latency_threshold_alert(temp_alert_env):
    storage = temp_alert_env["storage"]
    engine = temp_alert_env["engine"]
    ws_id = temp_alert_env["ws"].workspace_id

    # Create rule: Latency > 2500 ms
    rule = AlertRule(
        workspace_id=ws_id,
        name="High Latency Breaker",
        condition=AlertTriggerCondition.LATENCY_THRESHOLD,
        threshold_value=2500.0,
        channel_type=AlertChannelType.DISCORD,
        webhook_url="https://discord.com/api/webhooks/mock",
        rate_limit_cooldown_s=5,
    )
    storage.create_alert_rule(rule)

    with patch.object(engine, "_post_json", return_value=(204, None)) as mock_post:
        # Below threshold (2100 ms) -> no alert
        inc_low = engine.evaluate_and_dispatch(
            workspace_id=ws_id,
            project_id=None,
            condition=AlertTriggerCondition.LATENCY_THRESHOLD,
            metric_value=2100.0,
            trace_id="tr_normal",
        )
        assert len(inc_low) == 0

        # Above threshold (3400 ms) -> fires alert
        inc_high = engine.evaluate_and_dispatch(
            workspace_id=ws_id,
            project_id=None,
            condition=AlertTriggerCondition.LATENCY_THRESHOLD,
            metric_value=3400.0,
            trace_id="tr_slow",
        )
        assert len(inc_high) == 1
        assert inc_high[0].dispatch_status == "success"
