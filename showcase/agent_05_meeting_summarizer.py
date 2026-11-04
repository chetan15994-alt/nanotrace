"""Agent 05 — Meeting Summarizer

Pattern: Multi-Model Pipeline (Gemini 2.0 Flash + Claude 3.5 Sonnet)
    MeetingSummarizerAgent (root, @trace_agent)
      ├── chat gemini-2.0-flash  (fast entity & action-item extraction across large transcript)
      ├── chat claude-3-5-sonnet (executive synthesis & strategic decision alignment)
      └── tool: dispatch_summary (deliver formatted digest to Slack / Email)

Demonstrates heterogeneous multi-model traces within a single execution:
pairing high-throughput low-cost models (Google Gemini 2.0 Flash) for entity extraction
with reasoning-dense models (Anthropic Claude 3.5 Sonnet) for executive decision synthesis.
"""

from __future__ import annotations

import nanotrace
from showcase._simulator import mock_llm_call, mock_tool_call

# ── Initialise NanoTrace ────────────────────────────────────────────────────
nanotrace.init(storage_path="./.traces/showcase.duckdb")

EXTRACTION_SYSTEM_PROMPT = (
    "You are a high-speed entity and action-item extractor. Process the raw meeting "
    "transcript. Identify all explicit owners, committed deadlines, unresolved blockers, "
    "and numerical metrics mentioned."
)

EXECUTIVE_SYNTHESIS_PROMPT = (
    "You are an executive chief-of-staff. Take the extracted action items and conversation "
    "flow to compose a crisp, high-impact executive summary for company leadership. "
    "Focus on strategic alignment, budget impact, and delivery risks."
)


@nanotrace.trace_agent(name="MeetingSummarizerAgent", agent_type="multi_model_pipeline")
def summarize_meeting(scenario: dict) -> dict:
    """Run dual-model meeting distillation workflow."""
    title = scenario["title"]
    transcript = scenario["transcript"]

    # Step 1: Extraction with Gemini 2.0 Flash (Fast, large context, ultra-cheap)
    extracted_actions = mock_llm_call(
        model="gemini-2.0-flash",
        system_prompt=EXTRACTION_SYSTEM_PROMPT,
        user_message=f"Meeting: {title}\nTranscript:\n{transcript}",
        response=scenario["extracted_data"],
        span_name="chat gemini-2.0-flash (Action Item Extraction)",
        temperature=0.1,
    )

    # Step 2: Synthesis with Claude 3.5 Sonnet (Nuanced reasoning & strategic tone)
    executive_digest = mock_llm_call(
        model="claude-3-5-sonnet",
        system_prompt=EXECUTIVE_SYNTHESIS_PROMPT,
        user_message=(
            f"Meeting: {title}\n"
            f"Extracted Commitments:\n{extracted_actions}"
        ),
        response=scenario["executive_digest"],
        span_name="chat claude-3-5-sonnet (Executive Synthesis)",
        temperature=0.3,
    )

    # Step 3: Tool delivery
    dispatch_res = mock_tool_call(
        tool_name="dispatch_digest_channel",
        arguments={"channel": "#executive-briefs", "subject": title},
        result={"status": "sent", "message_ts": "1714831200.001920"},
        latency_ms=16.0,
    )

    return {
        "title": title,
        "actions_found": scenario["actions_count"],
        "digest": executive_digest,
        "dispatched": dispatch_res["status"] == "sent",
    }


# ── 5 Realistic Transcripts Across Business Functions ───────────────────────
MEETINGS = [
    {
        "title": "Sprint 42 Planning & Database Migration",
        "actions_count": 4,
        "transcript": (
            "Alice (Eng Lead): Okay team, our primary sprint goal is migrating customer telemetry from Postgres to ClickHouse. "
            "Bob: I've benchmarked the new ingestion pipeline at 85k events/sec. However, we need schema sign-off by Wednesday. "
            "Charlie: I will finalize the Parquet schema mappings by Tuesday 5 PM. "
            "Alice: Perfect. Bob, you own deploying the Kafka sink connector by Friday. David, ensure staging alerts are muted."
        ),
        "extracted_data": (
            "Owners & Deadlines:\n"
            "- Charlie: Finalize Parquet schema mappings by Tuesday 5 PM.\n"
            "- Bob: Deploy Kafka sink connector by Friday.\n"
            "- David: Mute staging alerts during migration window.\n"
            "Key Metrics: 85k events/sec benchmark achieved."
        ),
        "executive_digest": (
            "Executive Summary: Sprint 42 focuses on scaling telemetry throughput 5x via ClickHouse migration. "
            "Critical path is Parquet schema sign-off on Tuesday, enabling Kafka connector rollout by Friday. "
            "Risk Profile: Low; staging alerting suppression planned to avoid alert fatigue."
        )
    },
    {
        "title": "Enterprise Design Review: Design Tokens & Dark Mode",
        "actions_count": 3,
        "transcript": (
            "Elena (Design): We conducted accessibility audits on the new high-contrast UI. WCAG 2.1 AAA compliance passed. "
            "Marcus (Frontend): The CSS variable token system is ready. We just need Figma exports for the secondary accent colors. "
            "Elena: I will export all token variables as JSON tokens by tomorrow noon. "
            "Marcus: Great, I'll merge the dark/light switcher into main by Thursday morning."
        ),
        "extracted_data": (
            "Compliance: WCAG 2.1 AAA passed.\n"
            "- Elena: Export Figma token JSON by Wednesday 12 PM.\n"
            "- Marcus: Merge dark/light theme toggle into main by Thursday 9 AM."
        ),
        "executive_digest": (
            "Executive Summary: Design System V2 meets strictest accessibility standards (WCAG 2.1 AAA). "
            "Full delivery into production scheduled for Thursday morning with zero blocking dependencies."
        )
    },
    {
        "title": "Q3 Board Governance & AI Observability Strategy",
        "actions_count": 3,
        "transcript": (
            "CEO: Investors are asking about our LLM expenditure and data governance compliance. "
            "CTO: We currently spend $32,000/month on hosted SaaS tracing platforms like Datadog and Arize. "
            "CEO: That is unsustainable. What is our alternative? "
            "CTO: Moving to local-first DuckDB tracing with NanoTrace reduces cloud ingestion bills to $0. "
            "CEO: Approved. Sarah, prepare the vendor termination notice for our enterprise SaaS by next Friday."
        ),
        "extracted_data": (
            "Financial Impact: Current SaaS tracing bill $32k/mo ($384k annualized).\n"
            "- CTO: Spearhead zero-cost DuckDB observability transition.\n"
            "- Sarah (Legal): Draft vendor termination notice by Friday 5 PM."
        ),
        "executive_digest": (
            "Strategic Brief: Board approved immediate migration to local-first AI observability (NanoTrace). "
            "Direct annualized OpEx reduction of $384,000 with complete data sovereignty under local DuckDB storage."
        )
    },
    {
        "title": "Enterprise Sales Discovery: FinTech Tier 1 Bank",
        "actions_count": 3,
        "transcript": (
            "Prospect (Chief Architect): We cannot send prompts or customer PII to US-hosted cloud observability platforms. "
            "AE: NanoTrace embeds directly in your local VPC with zero external telemetry egress. "
            "Prospect: If you can provide SOC2 Type II and on-premise Parquet lakehouse export, we will sign a 3-year contract. "
            "AE: Mark, prepare the technical security whitepaper by Monday."
        ),
        "extracted_data": (
            "Customer Requirements: Strict zero-egress data privacy, SOC2 Type II compliance.\n"
            "Contract Value: 3-year enterprise commitment.\n"
            "- Mark (Solutions): Deliver VPC telemetry architecture whitepaper by Monday."
        ),
        "executive_digest": (
            "Sales Pipeline Opportunity: Tier-1 FinTech customer confirmed zero-egress requirement as primary buying criterion. "
            "NanoTrace's local-first architecture eliminates SaaS compliance hurdles where competitors failed security audit."
        )
    },
    {
        "title": "Postmortem: Incident INC-9014 (Gateway Redis Saturation)",
        "actions_count": 4,
        "transcript": (
            "SRE Lead: On Sunday 03:15 UTC, connection pooling exhaustion caused a 4-minute API degradation. "
            "DevOps: Root cause was missing max_connections limit in the client pool config. "
            "SRE Lead: Action item 1: Cap connection pool at 200 per pod. Action item 2: Add health check probe alert at 80% saturation. "
            "DevOps: I will submit the Terraform PR by this afternoon."
        ),
        "extracted_data": (
            "Incident Duration: 4 minutes (03:15 UTC).\n"
            "Root Cause: Client-side connection pool unbounded exhaustion.\n"
            "- DevOps: Cap Redis connection pool at 200 and submit Terraform PR today.\n"
            "- SRE Lead: Deploy early-warning probe alert for 80% pool utilization."
        ),
        "executive_digest": (
            "Postmortem Review: Root cause remediated within 4 hours. No data loss occurred. "
            "Infrastructure hardening underway with strict resource caps and proactive saturation telemetry."
        )
    }
]


# ── Runner ──────────────────────────────────────────────────────────────────
def run_all_scenarios() -> None:
    """Execute all meeting summarizer scenarios and print a summary."""
    print("=" * 72)
    print("  Agent 05 — Meeting Summarizer (Multi-Model: Gemini 2.0 + Claude 3.5)")
    print("=" * 72)

    for i, item in enumerate(MEETINGS, 1):
        result = summarize_meeting(item)
        preview = result["digest"].split(".")[0]
        print(f"\n  Meeting {i}: {result['title']}")
        print(f"    Action Items: {result['actions_found']} captured by Gemini 2.0 Flash")
        print(f"    Executive   : {preview} (Claude 3.5 Sonnet).")

    nanotrace.flush()
    print("\n" + "-" * 72)
    print(f"  ✓ {len(MEETINGS)} multi-model traces written to ./.traces/showcase.duckdb")
    print("=" * 72)


if __name__ == "__main__":
    run_all_scenarios()
