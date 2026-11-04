"""Agent 04 — Data Pipeline Monitor

Pattern: Error Handling, Retries & Soft Failure Recovery
    PipelineMonitorAgent (root, @trace_agent)
      ├── tool: check_node_health     (cluster metrics probe)
      ├── tool: check_node_health     (retry on transient network drop)
      ├── chat gpt-4o-mini            (triage incident severity & root cause)
      └── tool: trigger_alert / heal  (escalate to PagerDuty or issue restart)

Demonstrates how NanoTrace surfaces error status codes (`StatusCode.ERROR`),
exception stacktraces, retry loops, and automated incident triage
without throwing unhandled exceptions in the user's host application.
"""

from __future__ import annotations

import nanotrace
from showcase._simulator import mock_llm_call, mock_tool_call

# ── Initialise NanoTrace ────────────────────────────────────────────────────
nanotrace.init(storage_path="./.traces/showcase.duckdb")

TRIAGE_SYSTEM_PROMPT = (
    "You are an automated site reliability engineer (SRE). Review the probe telemetry, "
    "failure logs, and retry attempts for the cluster. Classify root cause, assess blast radius, "
    "and prescribe mitigation."
)


@nanotrace.trace_agent(name="PipelineMonitorAgent", agent_type="sre_supervisor")
def monitor_pipeline_node(scenario: dict) -> dict:
    """Execute node monitoring probe with automatic retry and incident triage."""
    node_id = scenario["node_id"]
    attempts = scenario["probe_attempts"]

    last_probe_result = None
    successful = False

    # Execute probe loop (demonstrating tool retries and error spans)
    for attempt_no, attempt in enumerate(attempts, 1):
        err = attempt.get("error")
        res = attempt.get("result")

        probe_output = mock_tool_call(
            tool_name="probe_cluster_health",
            arguments={"node_id": node_id, "attempt": attempt_no, "timeout_ms": 3000},
            result=res,
            latency_ms=15.0,
            error=err,
        )

        if err is None:
            last_probe_result = probe_output
            successful = True
            break
        else:
            last_probe_result = err

    # LLM Incident Triage Step
    triage_report = mock_llm_call(
        model="gpt-4o-mini",
        system_prompt=TRIAGE_SYSTEM_PROMPT,
        user_message=(
            f"Node: {node_id}\n"
            f"Probes Executed: {len(attempts)}\n"
            f"Final State: {'HEALTHY' if successful else 'DEGRADED/FAILED'}\n"
            f"Telemetry: {last_probe_result}"
        ),
        response=scenario["triage_decision"],
        span_name="chat gpt-4o-mini (Incident Triage)",
        temperature=0.1,
    )

    # Resolution Tool Call
    action_tool = scenario["action_tool"]
    action_result = mock_tool_call(
        tool_name=action_tool["name"],
        arguments=action_tool["args"],
        result=action_tool["response"],
        latency_ms=25.0,
        error=action_tool.get("error"),
    )

    return {
        "node_id": node_id,
        "status": "RESOLVED" if successful else "ESCALATED",
        "triage": triage_report,
        "action": action_result,
    }


# ── 5 Scenarios Covering Healthy, Retries, and Failures ──────────────────────
SCENARIOS = [
    {
        "node_id": "kafka-broker-prod-01",
        "probe_attempts": [
            {
                "result": {"status": "UP", "cpu_percent": 34.2, "disk_used_percent": 58.1, "lag_ms": 12},
                "error": None
            }
        ],
        "triage_decision": "Node operating well within SLA limits. CPU at 34%, disk healthy at 58%. Zero partition lag.",
        "action_tool": {
            "name": "record_health_heartbeat",
            "args": {"node_id": "kafka-broker-prod-01", "status": "GREEN"},
            "response": {"acknowledged": True, "timestamp": 1714829100}
        }
    },
    {
        "node_id": "redis-shard-secondary-03",
        "probe_attempts": [
            {
                "result": None,
                "error": "ConnectionTimeoutError: TCP socket connection to redis-shard-03:6379 timed out after 3000ms"
            },
            {
                "result": {"status": "UP", "memory_used_mb": 4120, "connected_clients": 890, "repl_offset": 992812},
                "error": None
            }
        ],
        "triage_decision": "Transient network hiccup on attempt 1 resolved on immediate retry. Replica offset is synchronized; no failover needed.",
        "action_tool": {
            "name": "log_transient_jitter_event",
            "args": {"node_id": "redis-shard-secondary-03", "jitter_ms": 3120},
            "response": {"logged": True, "suppress_pager": True}
        }
    },
    {
        "node_id": "postgres-read-replica-us-east",
        "probe_attempts": [
            {
                "result": None,
                "error": "ReplicationLagCritical: WalReceiver lagged behind primary by 1840MB (exceeds 500MB safety threshold)"
            },
            {
                "result": None,
                "error": "ReplicationLagCritical: Lag widened to 1910MB. I/O thread blocked on disk flush"
            }
        ],
        "triage_decision": "CRITICAL REPLICATION DEGRADATION: Replica has drifted by nearly 2GB. Queries routing here risk serving stale transactions.",
        "action_tool": {
            "name": "drain_traffic_and_page_oncall",
            "args": {"node_id": "postgres-read-replica-us-east", "severity": "P1", "drain": True},
            "response": {"traffic_drained": True, "pagerduty_incident": "INC-88219"}
        }
    },
    {
        "node_id": "clickhouse-analytics-ingest-02",
        "probe_attempts": [
            {
                "result": None,
                "error": "DiskQuotaExceeded: File system /var/lib/clickhouse reached 99.4% capacity (120MB remaining)"
            }
        ],
        "triage_decision": "FATAL DISK SATURATION: Ingestion pipeline halted to prevent storage corruption. Immediate partition drop required.",
        "action_tool": {
            "name": "emergency_archive_cold_partitions",
            "args": {"node_id": "clickhouse-analytics-ingest-02", "older_than_days": 90},
            "response": {"freed_gb": 420.5, "status": "STORAGE_RESTORED"}
        }
    },
    {
        "node_id": "external-llm-gateway-proxy",
        "probe_attempts": [
            {
                "result": None,
                "error": "RateLimitError 429: Too Many Requests from OpenAI API gateway. Tokens-per-minute quota exceeded."
            },
            {
                "result": {"status": "DEGRADED", "tpm_available": 150000, "fallback_provider": "anthropic_claude"},
                "error": None
            }
        ],
        "triage_decision": "Upstream 429 detected on primary OpenAI route. Automatically dynamic-routed overflow traffic to Claude 3.5 fallback.",
        "action_tool": {
            "name": "activate_circuit_breaker_reroute",
            "args": {"primary": "openai", "fallback": "anthropic", "duration_sec": 300},
            "response": {"circuit_open": True, "reroute_pct": 100}
        }
    }
]


# ── Runner ──────────────────────────────────────────────────────────────────
def run_all_scenarios() -> None:
    """Execute all pipeline monitoring scenarios and print a summary."""
    print("=" * 72)
    print("  Agent 04 — Data Pipeline Monitor (Error Handling & SRE Triage)")
    print("=" * 72)

    for i, item in enumerate(SCENARIOS, 1):
        result = monitor_pipeline_node(item)
        preview = result["triage"].split(".")[0]
        print(f"\n  Pipeline Check {i}: {result['node_id']}")
        print(f"    Outcome : {result['status']}")
        print(f"    Triage  : {preview}.")

    nanotrace.flush()
    print("\n" + "-" * 72)
    print(f"  ✓ {len(SCENARIOS)} pipeline monitor traces written to ./.traces/showcase.duckdb")
    print("=" * 72)


if __name__ == "__main__":
    run_all_scenarios()
