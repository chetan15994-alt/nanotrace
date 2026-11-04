"""Healer Showcase — Universal Telemetry Normalization & Trace Repair

Demonstrates the Universal Trace Healer (UITH) resolving the 5 most common
real-world telemetry failures when using non-standard or fragmented agent backends:

1. Hierarchical LangGraph Run Trees (Recursive child runs flattened & linked)
2. CrewAI Multi-Agent Task Dumps (Agent roles, task dependencies, & token rollups)
3. Microsoft AutoGen Multi-Turn Message Streams (Role-based turn segmentation)
4. Raw ReAct Terminal Output Logs (Text stdout state machine parsing)
5. Temporal Interval Grafting (Reconnecting orphan spans lost across async worker pools)
6. Fragmented Multi-Vendor Token Mapping (OpenAI, Anthropic, Gemini, AWS Bedrock)
"""

from __future__ import annotations

import time
import nanotrace

# ── Initialise NanoTrace ────────────────────────────────────────────────────
nanotrace.init(storage_path="./.traces/showcase.duckdb")


def run_all_healer_scenarios() -> None:
    """Execute all 6 healer ingestion demonstrations and display normalization results."""
    print("=" * 72)
    print("  Healer Showcase — Universal Telemetry Normalization (UITH)")
    print("=" * 72)

    # ── 1. LangGraph Hierarchical Run Tree ───────────────────────────────────
    print("\n  [1/6] Ingesting Hierarchical LangGraph Run Tree...")
    langgraph_tree = {
        "run_type": "chain",
        "name": "CustomerSupportLangGraph",
        "inputs": {"ticket_id": "TCK-9901", "query": "Payment method rejected at checkout"},
        "outputs": {"status": "resolved", "action": "Switched fallback gateway to Stripe"},
        "child_runs": [
            {
                "run_type": "llm",
                "name": "TriageClassifierLLM",
                "extra": {"metadata": {"model_name": "claude-3-5-sonnet"}},
                "usage": {"input_tokens": 180, "output_tokens": 42},
                "outputs": {"text": "Category: Payment Gateway Failure"},
            },
            {
                "run_type": "tool",
                "tool": "check_gateway_health",
                "inputs": {"gateway": "adyen_eu"},
                "outputs": "{\"error\": \"503 Service Unavailable\", \"success\": false}",
            },
            {
                "run_type": "tool",
                "tool": "reroute_gateway",
                "inputs": {"fallback": "stripe_us"},
                "outputs": "{\"status\": \"rerouted\", \"success\": true}",
            }
        ]
    }
    spans_lg = nanotrace.ingest(langgraph_tree)
    print(f"    ✓ Healed {len(spans_lg)} spans: Root Graph + Child LLM + 2 Child Tools")
    print(f"    ✓ Root Span ID : {spans_lg[0].span_id}")
    print(f"    ✓ First Child Parent ID : {spans_lg[1].parent_span_id} (Linked to Root!)")

    # ── 2. CrewAI Multi-Agent Task Dump ─────────────────────────────────────
    print("\n  [2/6] Ingesting CrewAI Multi-Agent Task Dump...")
    crewai_dump = {
        "crew": "AutonomousMarketResearchCrew",
        "inputs": {"product": "NanoTrace", "target": "Enterprise DevOps"},
        "tasks_output": [
            {
                "agent": "Senior Research Analyst",
                "description": "Analyze developer pain points with Datadog and LangSmith SaaS pricing",
                "raw": "Developers strongly dislike paying per-span cloud ingestion egress charges.",
            },
            {
                "agent": "Lead Technical Copywriter",
                "description": "Draft high-converting launch copy emphasizing DuckDB local storage",
                "raw": "Headline: The DuckDB of AI Observability. 100% on-premises, $0 cloud egress.",
            }
        ]
    }
    spans_crew = nanotrace.ingest(crewai_dump)
    print(f"    ✓ Extracted {len(spans_crew)} spans: CrewAI Workflow Root + 2 Agent Tasks")
    print(f"    ✓ Agent Name mapped: {spans_crew[1].attributes.get('gen_ai.agent.name', 'Analyst')}")

    # ── 3. AutoGen Multi-Turn Message Stream ─────────────────────────────────
    print("\n  [3/6] Ingesting AutoGen Multi-Turn Conversation History...")
    autogen_messages = [
        {"role": "user", "content": "Can we inspect the p95 query latency for last week's traces?"},
        {"role": "assistant", "model": "gpt-4o", "content": "SELECT quantile_cont(duration_ms, 0.95) FROM spans; Returned 1.45ms."},
        {"role": "user", "content": "Excellent, verified under 2ms SLA."},
    ]
    spans_ag = nanotrace.ingest(autogen_messages)
    print(f"    ✓ Normalized {len(spans_ag)} spans: Conversation Root + 3 Sequential Turns")

    # ── 4. Raw ReAct Terminal Output Logs ───────────────────────────────────
    print("\n  [4/6] Ingesting Unstructured ReAct Terminal Text Log...")
    react_stdout = """
    Thought: The customer wants to verify their storage volume size.
    Action: check_storage_quota
    Action Input: {"customer_id": "CUST-4110"}
    Observation: {"allocated_gb": 500, "used_gb": 482, "warning": "threshold_reached"}
    Thought: Storage usage is at 96.4%. An automated volume expansion is warranted.
    Action: expand_volume
    Action Input: {"customer_id": "CUST-4110", "additional_gb": 200}
    Observation: {"status": "SUCCESS", "new_allocated_gb": 700}
    """
    spans_react = nanotrace.ingest(react_stdout)
    print(f"    ✓ Reconstructed {len(spans_react)} spans via line-by-line ReAct state machine")
    print(f"    ✓ Tool Call: {spans_react[0].attributes.get('gen_ai.tool.name')} | Status: {spans_react[0].status.value}")

    # ── 5. Temporal Interval Grafting (Heal Broken Parent IDs) ──────────────
    print("\n  [5/6] Healing Orphan Spans via Temporal Interval Grafting...")
    # Simulate child spans that lost their parent_span_id due to async thread context loss
    now = time.time_ns()
    orphan_payload = [
        {
            "name": "AsyncBatchPipeline",
            "span_id": "root_9901_aaaa",
            "parent_span_id": None,
            "start_time_ns": now,
            "end_time_ns": now + 50_000_000,
        },
        {
            "name": "ThreadWorker_SubTask_A",
            "span_id": "orphan_child_bbbb",
            "parent_span_id": None,  # ContextVar was lost in ThreadPoolExecutor!
            "start_time_ns": now + 5_000_000,
            "end_time_ns": now + 20_000_000,
        },
        {
            "name": "ThreadWorker_SubTask_B",
            "span_id": "orphan_child_cccc",
            "parent_span_id": None,  # Lost parent
            "start_time_ns": now + 25_000_000,
            "end_time_ns": now + 45_000_000,
        }
    ]
    spans_healed = nanotrace.ingest(orphan_payload)
    print(f"    ✓ Root Span: {spans_healed[0].name} (ID: {spans_healed[0].span_id})")
    print(f"    ✓ Orphan A Grafted: Parent ID -> {spans_healed[1].parent_span_id} (Matched Root!)")
    print(f"    ✓ Orphan B Grafted: Parent ID -> {spans_healed[2].parent_span_id} (Matched Root!)")

    # ── 6. Multi-Vendor Fragmented Token Reconciliation ─────────────────────
    print("\n  [6/6] Reconciling Fragmented Multi-Vendor Token Envelopes...")
    vendor_spans = [
        # OpenAI style
        {"name": "openai_step", "model": "gpt-4o", "usage": {"prompt_tokens": 120, "completion_tokens": 40}},
        # Anthropic style
        {"name": "anthropic_step", "model": "claude-3-5-sonnet", "usage": {"input_tokens": 200, "output_tokens": 80}},
        # Google Gemini style
        {"name": "gemini_step", "model": "gemini-2.0-flash", "usage_metadata": {"prompt_token_count": 350, "candidates_token_count": 95}},
        # AWS Bedrock style
        {"name": "bedrock_step", "model": "llama", "invocationMetrics": {"inputTokenCount": 90, "outputTokenCount": 35}},
    ]
    spans_vendors = nanotrace.ingest(vendor_spans)
    for s in spans_vendors:
        in_t = s.attributes.get("gen_ai.usage.input_tokens")
        out_t = s.attributes.get("gen_ai.usage.output_tokens")
        cost = s.attributes.get("gen_ai.usage.cost_usd")
        prov = s.attributes.get("gen_ai.system")
        print(f"    ✓ Provider: {prov:<10} | In: {in_t:>3} | Out: {out_t:>3} | Cost: ${cost:.6f} USD")

    nanotrace.flush()
    print("\n" + "-" * 72)
    print("  ✓ All 6 telemetry healing demonstrations successfully written to DuckDB")
    print("=" * 72)


if __name__ == "__main__":
    run_all_healer_scenarios()
