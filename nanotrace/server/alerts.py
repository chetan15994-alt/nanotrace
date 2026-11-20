"""Real-Time Multi-Channel Alert Engine for NanoTrace Server.

Dispatches instant incident notifications to Slack, Discord, PagerDuty,
and Generic Signed Webhooks when NanoShield triggers or SLA thresholds are breached.
"""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

from nanotrace.server.auth import sign_webhook_payload
from nanotrace.server.models import (
    AlertChannelType,
    AlertIncident,
    AlertRule,
    AlertTriggerCondition,
)
from nanotrace.server.storage import ServerMetadataStorage


class AlertEngine:
    """Evaluates rules and dispatches multi-channel webhook notifications."""

    # In-memory cooldown tracking: rule_id -> last_dispatched_timestamp
    _last_dispatched: Dict[str, float] = {}

    def __init__(self, storage: ServerMetadataStorage):
        self.storage = storage

    def evaluate_and_dispatch(
        self,
        workspace_id: str,
        project_id: Optional[str],
        condition: AlertTriggerCondition,
        metric_value: float,
        trace_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[AlertIncident]:
        """Checks all active rules matching condition and dispatches notifications if breached."""
        rules = self.storage.list_alert_rules(workspace_id, project_id)
        matching_rules = [r for r in rules if r.condition == condition]
        incidents = []

        now = time.time()
        for rule in matching_rules:
            # Check threshold logic
            breached = False
            if condition == AlertTriggerCondition.KILLSWITCH_TRIGGERED:
                breached = True  # Any killswitch intercept fires the rule
            elif condition == AlertTriggerCondition.LATENCY_THRESHOLD and metric_value >= rule.threshold_value:
                breached = True
            elif condition == AlertTriggerCondition.COST_THRESHOLD and metric_value >= rule.threshold_value:
                breached = True
            elif condition == AlertTriggerCondition.ERROR_SPIKE and metric_value >= rule.threshold_value:
                breached = True
            elif condition == AlertTriggerCondition.RAG_HALLUCINATION and metric_value >= rule.threshold_value:
                breached = True

            if not breached:
                continue

            # Check rate limiting cooldown
            last_time = self._last_dispatched.get(rule.rule_id, 0.0)
            if (now - last_time) < rule.rate_limit_cooldown_s:
                continue  # Silently skip during cooldown

            incident = self.dispatch_alert(rule, metric_value, trace_id, context)
            self._last_dispatched[rule.rule_id] = now
            incidents.append(incident)

        return incidents

    def dispatch_alert(
        self,
        rule: AlertRule,
        metric_value: float,
        trace_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AlertIncident:
        """Dispatches an alert to the configured channel."""
        ctx = context or {}
        title = f"⚠️ [NanoTrace] Alert: {rule.name}"
        desc = (
            f"Rule '{rule.name}' triggered ({rule.condition.value}). "
            f"Value: {metric_value:.2f} (Threshold: {rule.threshold_value:.2f})."
        )
        if trace_id:
            desc += f" Trace ID: {trace_id}"

        severity = "critical" if rule.condition == AlertTriggerCondition.KILLSWITCH_TRIGGERED else "warning"

        incident = AlertIncident(
            rule_id=rule.rule_id,
            workspace_id=rule.workspace_id,
            project_id=rule.project_id,
            title=title,
            description=desc,
            severity=severity,
            trigger_condition=rule.condition,
            trace_id=trace_id,
            metrics={"value": metric_value, "threshold": rule.threshold_value, **ctx},
            dispatched_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            dispatch_status="pending",
        )

        try:
            if rule.channel_type == AlertChannelType.SLACK:
                status_code, err = self._send_slack(rule.webhook_url, incident)
            elif rule.channel_type == AlertChannelType.DISCORD:
                status_code, err = self._send_discord(rule.webhook_url, incident)
            elif rule.channel_type == AlertChannelType.PAGERDUTY:
                status_code, err = self._send_pagerduty(rule.webhook_url, incident)
            else:
                status_code, err = self._send_generic_webhook(rule.webhook_url, incident, rule.secret_token)

            incident.response_code = status_code
            incident.dispatch_status = "success" if (status_code and 200 <= status_code < 300) else "failed"
            incident.error_detail = err
        except Exception as e:
            incident.dispatch_status = "failed"
            incident.error_detail = str(e)

        return self.storage.record_incident(incident)

    def _send_slack(self, webhook_url: str, incident: AlertIncident) -> Tuple[int, Optional[str]]:
        """Sends rich Slack Block Kit payload."""
        color = "#ef4444" if incident.severity == "critical" else "#f59e0b"
        payload = {
            "attachments": [
                {
                    "color": color,
                    "title": incident.title,
                    "text": incident.description,
                    "fields": [
                        {"title": "Severity", "value": incident.severity.upper(), "short": True},
                        {"title": "Trigger", "value": incident.trigger_condition.value, "short": True},
                        {"title": "Trace ID", "value": incident.trace_id or "N/A", "short": True},
                        {"title": "Timestamp", "value": incident.dispatched_at, "short": True},
                    ],
                    "footer": "NanoTrace Cloud Control Plane",
                }
            ]
        }
        return self._post_json(webhook_url, payload)

    def _send_discord(self, webhook_url: str, incident: AlertIncident) -> Tuple[int, Optional[str]]:
        """Sends rich Discord embed card."""
        color_int = 15682628 if incident.severity == "critical" else 16098827  # Red or Amber
        payload = {
            "embeds": [
                {
                    "title": incident.title,
                    "description": incident.description,
                    "color": color_int,
                    "fields": [
                        {"name": "Severity", "value": incident.severity.upper(), "inline": True},
                        {"name": "Trigger", "value": incident.trigger_condition.value, "inline": True},
                        {"name": "Trace ID", "value": incident.trace_id or "N/A", "inline": True},
                    ],
                    "footer": {"text": "NanoTrace Fleet Sentinel"},
                    "timestamp": incident.dispatched_at,
                }
            ]
        }
        return self._post_json(webhook_url, payload)

    def _send_pagerduty(self, routing_url: str, incident: AlertIncident) -> Tuple[int, Optional[str]]:
        """Sends PagerDuty Events API v2 payload."""
        payload = {
            "event_action": "trigger",
            "dedup_key": f"nanotrace_{incident.rule_id}_{incident.trace_id or 'incident'}",
            "payload": {
                "summary": incident.title,
                "severity": incident.severity if incident.severity in ["critical", "warning", "info"] else "warning",
                "source": "NanoTrace Agent Observability",
                "custom_details": incident.metrics,
            },
        }
        return self._post_json(routing_url, payload)

    def _send_generic_webhook(
        self,
        webhook_url: str,
        incident: AlertIncident,
        secret: Optional[str] = None,
    ) -> Tuple[int, Optional[str]]:
        """Sends standard JSON payload with optional HMAC-SHA256 signature."""
        data = json.dumps(incident.model_dump()).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "NanoTrace-Sentinel/1.0"}
        if secret:
            sig = sign_webhook_payload(data, secret)
            headers["X-NanoTrace-Signature"] = f"sha256={sig}"

        req = urllib.request.Request(webhook_url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status, None
        except urllib.error.HTTPError as e:
            return e.code, e.reason
        except Exception as e:
            return 0, str(e)

    def _post_json(self, url: str, payload: Dict[str, Any]) -> Tuple[int, Optional[str]]:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "NanoTrace-AlertBot/1.0"}
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status, None
        except urllib.error.HTTPError as e:
            return e.code, e.reason
        except Exception as e:
            return 0, str(e)
