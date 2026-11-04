"""Multi-Agent Orchestrated System: AI Startup Executive Council

Architecture: Supervisor / Router Multi-Agent System
                      ┌────────────────────────────┐
                      │    SupervisorOrchestrator  │  (gpt-4o-mini)
                      └─────────────┬──────────────┘
                                    │
           ┌────────────────────────┼────────────────────────┬────────────────────────┐
           ▼                        ▼                        ▼                        ▼
 ┌───────────────────┐    ┌───────────────────┐    ┌───────────────────┐    ┌───────────────────┐
 │MarketResearchAgent│    │FinancialAdvisor   │    │TechArchitectAgent │    │LegalCompliance    │
 │(claude-3-5-sonnet)│    │(gpt-4o)           │    │(gpt-4o)           │    │(claude-3-haiku)   │
 └───────────────────┘    └───────────────────┘    └───────────────────┘    └───────────────────┘
   ├── tam_calculator       ├── runway_calc          ├── benchmark_db         ├── gdpr_audit_check
   └── competitor_search    └── unit_economics       └── infra_cost_estimator └── terms_generator

Demonstrates:
- Hierarchical multi-agent distributed tracing with W3C traceparent context inheritance
- Dynamic intent routing and sequential specialist handoffs under a single TraceID
- Single-specialist queries AND complex multi-agent collaborative handoffs
- Distributed error propagation and graceful mitigation (simulated regulatory DB rate limit)
"""

from __future__ import annotations

import time
from typing import Dict, Any, List, Optional

import nanotrace
from nanotrace.schema.otel import GenAIAttributes, GenAIOperation, SpanKind, StatusCode
from showcase._simulator import mock_llm_call, mock_tool_call

# ── Initialise NanoTrace ────────────────────────────────────────────────────
nanotrace.init(storage_path="./.traces/showcase.duckdb")

SUPERVISOR_ROUTER_PROMPT = (
    "You are the Startup Chief of Staff and Orchestrator. Analyze the founder's query "
    "and determine which specialist council members need to be convened: "
    "[MARKET, FINANCE, TECH, LEGAL]. If the question spans multiple domains, return "
    "all relevant specialists in execution order."
)


# ── Specialist 1: Market Research Agent ─────────────────────────────────────
@nanotrace.trace_agent(name="MarketResearchAgent", agent_type="specialist_market")
def run_market_research(topic: str, context: dict) -> dict:
    """Analyze TAM, competitive dynamics, and buyer personas."""
    # Tool 1: Competitor Matrix Search
    competitors = mock_tool_call(
        tool_name="competitor_matrix_search",
        arguments={"sector": topic, "top_n": 3},
        result=[
            {"name": "LangSmith", "pricing": "$39/seat/mo + trace volume", "market_share": "38%"},
            {"name": "Arize AI", "pricing": "Enterprise custom quotes ($50k+)", "market_share": "24%"},
            {"name": "Weights & Biases Weave", "pricing": "$50/user/mo", "market_share": "15%"},
        ],
        latency_ms=18.0,
    )

    # Tool 2: Total Addressable Market (TAM) Calculator
    tam_data = mock_tool_call(
        tool_name="tam_calculator",
        arguments={"vertical": "GenAI Observability", "cagr_percent": 34.5},
        result={"tam_2026_usd": "4.8B", "developer_count_est": "18.2M", "growth_rate": "34.5%"},
        latency_ms=12.0,
    )

    # LLM Synthesis
    synthesis = mock_llm_call(
        model="claude-3-5-sonnet",
        system_prompt="You are a seasoned VP of Market Strategy. Provide competitive positioning advice.",
        user_message=f"Evaluate market positioning for: {topic}\nCompetitors: {competitors}\nTAM: {tam_data}",
        response=context.get(
            "market_response",
            f"Market Analysis for {topic}: GenAI observability represents a $4.8B TAM growing at 34.5% CAGR. "
            "Incumbents (LangSmith, Arize) charge steep egress fees ($39-$50/seat plus per-span ingestion). "
            "A zero-cost, local-first DuckDB alternative captures developers seeking zero data-leakage and zero cloud bills."
        ),
        span_name="chat claude-3-5-sonnet (Market Analysis)",
        temperature=0.3,
    )

    return {"specialist": "MARKET", "analysis": synthesis, "tam": tam_data["tam_2026_usd"]}


# ── Specialist 2: Financial Advisor Agent ────────────────────────────────────
@nanotrace.trace_agent(name="FinancialAdvisorAgent", agent_type="specialist_finance")
def run_financial_advisory(query: str, context: dict) -> dict:
    """Model burn rate, runway, and SaaS unit economics."""
    # Tool 1: Runway & Burn Calculator
    runway = mock_tool_call(
        tool_name="runway_calculator",
        arguments={"cash_balance_usd": 500000, "monthly_burn_usd": 40000, "revenue_growth_pct": 5.0},
        result={"runway_months": 13.8, "cash_out_date": "2027-08-15", "zero_cash_risk": "MEDIUM"},
        latency_ms=14.0,
    )

    # Tool 2: Unit Economics Modeler
    unit_econ = mock_tool_call(
        tool_name="unit_economics_modeler",
        arguments={"cac_usd": 420, "arpu_usd": 120, "churn_rate_pct": 2.1},
        result={"ltv_usd": 5714, "ltv_cac_ratio": 13.6, "payback_months": 3.5},
        latency_ms=16.0,
    )

    # LLM Financial Guidance
    synthesis = mock_llm_call(
        model="gpt-4o",
        system_prompt="You are a startup CFO. Evaluate runway sustainability and capital allocation.",
        user_message=f"Financial query: {query}\nRunway telemetry: {runway}\nUnit metrics: {unit_econ}",
        response=context.get(
            "finance_response",
            f"Financial Guidance: At $40,000/mo net burn with $500,000 cash, current runway extends to 13.8 months. "
            "The unit economics are exceptionally healthy with an LTV/CAC ratio of 13.6x and a 3.5-month payback period. "
            "Recommendation: Begin Series A fundraising conversations at the 8-month runway mark (Month 6)."
        ),
        span_name="chat gpt-4o (Financial Modeling)",
        temperature=0.2,
    )

    return {"specialist": "FINANCE", "runway_months": runway["runway_months"], "guidance": synthesis}


# ── Specialist 3: Technical Architect Agent ──────────────────────────────────
@nanotrace.trace_agent(name="TechnicalArchitectAgent", agent_type="specialist_tech")
def run_technical_architecture(query: str, context: dict) -> dict:
    """Evaluate database engines, latency tradeoffs, and cloud hosting infrastructure."""
    # Tool 1: Database Benchmark Lookup
    benchmarks = mock_tool_call(
        tool_name="benchmark_latency_db",
        arguments={"engines": ["DuckDB", "PostgreSQL", "ClickHouse"], "dataset_size_rows": 10000000},
        result={
            "DuckDB_p50_ms": 1.2,
            "PostgreSQL_p50_ms": 142.8,
            "ClickHouse_p50_ms": 3.4,
            "DuckDB_ram_mb": 48,
        },
        latency_ms=22.0,
    )

    # Tool 2: Infrastructure Cost Estimator
    infra_costs = mock_tool_call(
        tool_name="infra_cost_estimator",
        arguments={"dau": 10000, "architecture": "local_first_embedded_duckdb"},
        result={"monthly_cloud_bill_usd": 0.0, "bandwidth_egress_usd": 0.0, "savings_vs_datadog_usd": 4200.0},
        latency_ms=15.0,
    )

    # LLM Architectural Recommendation
    synthesis = mock_llm_call(
        model="gpt-4o",
        system_prompt="You are a Principal Cloud Architect. Architect scalable, zero-cost AI systems.",
        user_message=f"Technical query: {query}\nDB Benchmarks: {benchmarks}\nInfra Cost: {infra_costs}",
        response=context.get(
            "tech_response",
            f"Technical Assessment: Embedded DuckDB delivers 1.2ms p50 analytical query latency—over 100x faster than "
            "remote PostgreSQL (142.8ms) while consuming only 48MB RAM. Because traces are saved locally and synced via ZSTD "
            "Parquet to S3 cold storage, monthly telemetry cloud bills remain $0.00."
        ),
        span_name="chat gpt-4o (Architecture Spec)",
        temperature=0.1,
    )

    return {"specialist": "TECH", "recommended_db": "DuckDB", "architecture": synthesis}


# ── Specialist 4: Legal & Compliance Agent ────────────────────────────────────
@nanotrace.trace_agent(name="LegalComplianceAgent", agent_type="specialist_legal")
def run_legal_compliance(query: str, context: dict) -> dict:
    """Audit GDPR, HIPAA, SOC2 Type II, and data retention mandates."""
    is_error_scenario = context.get("trigger_legal_rate_limit", False)

    # Tool 1: Regulatory Database Audit Check
    if is_error_scenario:
        # Simulate transient API rate limit on compliance DB
        mock_tool_call(
            tool_name="gdpr_audit_check",
            arguments={"jurisdiction": "EU/GDPR", "telemetry_egress": "external_saas"},
            result=None,
            latency_ms=20.0,
            error="RateLimitExceeded 429: Compliance Registry API quota exceeded. Retry after 2000ms.",
        )
        # Immediate fallback to cached local compliance regulatory rulebook
        mock_tool_call(
            tool_name="read_cached_compliance_manifest",
            arguments={"cached_spec": "EU_GDPR_ARTICLE_28"},
            result={"status": "CACHED_RECORD_VERIFIED", "article": "Art. 28 GDPR Data Processor Mandate"},
            latency_ms=10.0,
        )
    else:
        mock_tool_call(
            tool_name="gdpr_audit_check",
            arguments={"jurisdiction": "EU/GDPR", "telemetry_egress": "local_first"},
            result={"gdpr_compliant": True, "cross_border_transfer_risk": "ZERO", "encryption": "AES-256"},
            latency_ms=18.0,
        )

    # Tool 2: Terms & Data Processing Agreement Generator
    mock_tool_call(
        tool_name="terms_generator",
        arguments={"clauses": ["zero_prompt_retention", "local_storage_sovereignty"]},
        result={"dpa_generated": True, "clause_count": 8},
        latency_ms=14.0,
    )

    # LLM Legal Advisory
    synthesis = mock_llm_call(
        model="claude-3-haiku",
        system_prompt="You are a Technology Privacy Attorney. Provide crisp compliance guidance.",
        user_message=f"Legal query: {query}",
        response=context.get(
            "legal_response",
            "Legal Opinion: Under GDPR Chapter V and EU-US Data Privacy Framework, shipping raw LLM prompts to "
            "third-party SaaS observability vendors requires executing complex DPAs and verifying sub-processor lists. "
            "By retaining traces locally on-premises via NanoTrace, the platform achieves zero cross-border transfer exposure."
        ),
        span_name="chat claude-3-haiku (Compliance Audit)",
        temperature=0.1,
    )

    return {"specialist": "LEGAL", "compliance_status": "COMPLIANT", "advisory": synthesis}


# ── Central Supervisor / Orchestrator ────────────────────────────────────────
@nanotrace.trace_agent(name="StartupOrchestratorSupervisor", agent_type="supervisor_router")
def orchestrate_startup_assistant(scenario: dict) -> dict:
    """Supervise intent classification, route to specialists, and synthesize final executive response."""
    user_query = scenario["query"]
    session_id = scenario.get("session_id", "startup_session_01")

    # Step 1: Supervisor Intent Routing Call
    routing_decision = mock_llm_call(
        model="gpt-4o-mini",
        system_prompt=SUPERVISOR_ROUTER_PROMPT,
        user_message=f"Determine routing for query: {user_query}",
        response=scenario["routing_plan"],
        span_name="chat gpt-4o-mini (Supervisor Router)",
        temperature=0.0,
    )

    specialist_results = []
    specialists = scenario["specialists"]

    # Step 2: Route sequentially to designated council specialists
    for spec in specialists:
        if spec == "MARKET":
            res = run_market_research(user_query, scenario)
            specialist_results.append(res)
        elif spec == "FINANCE":
            res = run_financial_advisory(user_query, scenario)
            specialist_results.append(res)
        elif spec == "TECH":
            res = run_technical_architecture(user_query, scenario)
            specialist_results.append(res)
        elif spec == "LEGAL":
            res = run_legal_compliance(user_query, scenario)
            specialist_results.append(res)

    # Step 3: Final Consolidated Executive Summary (if multi-specialist)
    if len(specialists) > 1:
        consolidated = mock_llm_call(
            model="gpt-4o",
            system_prompt="You are the Executive Managing Director. Synthesize specialist inputs into unified strategy.",
            user_message=f"User Query: {user_query}\nSpecialist Inputs: {specialist_results}",
            response=scenario.get(
                "consolidated_response",
                f"Consolidated Strategy: Harmonized analysis across {len(specialists)} specialist domains confirmed viability."
            ),
            span_name="chat gpt-4o (Executive Consensus)",
            temperature=0.2,
        )
    else:
        consolidated = specialist_results[0].get("analysis") or specialist_results[0].get("guidance") or specialist_results[0].get("architecture") or specialist_results[0].get("advisory")

    return {
        "query": user_query,
        "routing": routing_decision,
        "specialists_engaged": specialists,
        "executive_resolution": consolidated,
    }


# ── 10 Comprehensive Real-World Scenarios ───────────────────────────────────
SCENARIOS = [
    {
        "id": 1,
        "query": "What is the total market size and competitive landscape for AI observability tools?",
        "routing_plan": "Route: [MARKET]",
        "specialists": ["MARKET"],
    },
    {
        "id": 2,
        "query": "How long will our runway last if we have $500K cash in bank and burn $40K per month?",
        "routing_plan": "Route: [FINANCE]",
        "specialists": ["FINANCE"],
    },
    {
        "id": 3,
        "query": "Should we use PostgreSQL or DuckDB for our embedded analytics and trace store backend?",
        "routing_plan": "Route: [TECH]",
        "specialists": ["TECH"],
    },
    {
        "id": 4,
        "query": "What GDPR and EU cross-border privacy mandates apply to our LLM observability stack?",
        "routing_plan": "Route: [LEGAL]",
        "specialists": ["LEGAL"],
    },
    {
        "id": 5,
        "query": "Compare our pricing strategy with incumbent platforms like LangSmith and Weights & Biases.",
        "routing_plan": "Route: [MARKET]",
        "specialists": ["MARKET"],
    },
    {
        "id": 6,
        "query": "Estimate our infrastructure costs and database throughput scaling to 10K daily active users.",
        "routing_plan": "Route: [TECH, FINANCE]",
        "specialists": ["TECH", "FINANCE"],
        "consolidated_response": (
            "Cross-Domain Architecture & Financial Review: Technical analysis confirms embedded DuckDB handles 10K DAU "
            "with zero cloud bill using 48MB RAM. Financial model projects this preserves $4,200/mo in OpEx compared to Datadog, "
            "extending overall runway by an additional 1.8 months."
        )
    },
    {
        "id": 7,
        "query": "What corporate legal structure and data processing agreement do we need for enterprise customer contracts?",
        "routing_plan": "Route: [LEGAL]",
        "specialists": ["LEGAL"],
    },
    {
        "id": 8,
        "query": "Analyze developer adoption trends and architect our high-throughput streaming ingestion pipeline.",
        "routing_plan": "Route: [MARKET, TECH]",
        "specialists": ["MARKET", "TECH"],
        "consolidated_response": (
            "Strategic Alignment: Market demand shows 68% of developers prioritize local privacy over hosted dashboards. "
            "Technical architecture accommodates this with zero-egress in-process ring buffers and sub-millisecond DuckDB writes."
        )
    },
    {
        "id": 9,
        "query": "What compliance certifications do we need before selling to regulated healthcare and financial institutions?",
        "routing_plan": "Route: [LEGAL]",
        "specialists": ["LEGAL"],
        "trigger_legal_rate_limit": True,  # Triggers tool error span + automated fallback
    },
    {
        "id": 10,
        "query": "Deliver an all-encompassing executive go-to-market plan: pricing model, unit economics, and data compliance.",
        "routing_plan": "Route: [MARKET, FINANCE, LEGAL]",
        "specialists": ["MARKET", "FINANCE", "LEGAL"],
        "consolidated_response": (
            "Executive Masterplan: Triple-council consensus establishes a frictionless developer-led GTM strategy. "
            "1) Market: Position as 'The DuckDB of AI Observability'. 2) Finance: 13.6x LTV/CAC ratio allows sustainable self-funding. "
            "3) Legal: Local-first architecture guarantees zero GDPR liability, shortening enterprise sales cycles from 90 days to 14 days."
        )
    }
]


# ── Runner ──────────────────────────────────────────────────────────────────
def run_all_scenarios() -> None:
    """Execute all 10 multi-agent scenarios and print a summary."""
    print("=" * 72)
    print("  Multi-Agent System — AI Startup Executive Council (Supervisor Router)")
    print("=" * 72)

    for i, item in enumerate(SCENARIOS, 1):
        res = orchestrate_startup_assistant(item)
        preview = res["executive_resolution"][:95].replace("\n", " ") + "…"
        print(f"\n  Query {i}: {res['query'][:60]}…")
        print(f"    Specialists Engaged: {res['specialists_engaged']}")
        print(f"    Executive Strategy : {preview}")

    nanotrace.flush()
    print("\n" + "-" * 72)
    print(f"  ✓ {len(SCENARIOS)} multi-agent traces written to ./.traces/showcase.duckdb")
    print("=" * 72)


if __name__ == "__main__":
    run_all_scenarios()
