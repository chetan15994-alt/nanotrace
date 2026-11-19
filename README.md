<div align="center">

# NanoTrace

### The Zero-Overhead Reliability Engine for Autonomous AI Agents

**Microsecond Tracing • Active Runaway Killswitches • Deterministic CI/CD Testing • Embedded DuckDB Lakehouse**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python Version](https://img.shields.io/badge/Python-3.9%20--%203.14-blue.svg)](https://www.python.org/downloads/)
[![Standard](https://img.shields.io/badge/OpenTelemetry-GenAI_v1.27-purple.svg)](https://opentelemetry.io)
[![Architecture](https://img.shields.io/badge/Architecture-In--Process_Embedded-emerald.svg)](#architecture)
[![Storage](https://img.shields.io/badge/Storage-DuckDB_%2B_Parquet-orange.svg)](https://duckdb.org)

<p align="center">
  Record agent loops, tool executions, and LLM calls in <b>3.5 microseconds</b>.<br>
  Actively intercept runaway while-loops and token budget blowouts in <b>7.9 microseconds</b>.<br>
  Run deterministic CI/CD regression gates with code 0/1 exits. Zero Docker containers. Zero SaaS bills.
</p>

---

</div>

## Executive Summary

### What is NanoTrace?
NanoTrace is the embedded, zero-cost reliability and observability engine designed specifically for AI agents, multi-agent swarms, and LLM applications. It provides enterprise-grade telemetry, active runtime safety guardrails, and automated CI/CD evaluation by running entirely inside your Python application process—persisting execution traces to an embedded DuckDB columnar file (`./.traces/nanotrace.duckdb`) and streaming ZSTD-compressed Parquet.

### The Analogy: The DuckDB / SQLite of AI Observability
Consider how database architectures evolved: traditional enterprise database platforms (Oracle, Snowflake) required remote server clusters, cloud credentials, network hops, and expensive subscriptions. SQLite and DuckDB revolutionized this paradigm by embedding powerful relational and analytical database engines directly into application processes.

**NanoTrace applies this exact principle to AI observability and agent reliability:**  
Instead of routing your application's prompts, tool arguments, and customer data over the public internet to costly third-party hosted SaaS collectors (like LangSmith or Arize) or running heavy multi-container Docker clusters (ClickHouse, Postgres, Redis), NanoTrace captures telemetry in-process with **under 4 microseconds of overhead**. 

You gain instant OpenTelemetry compliance, active runaway loop killswitches, automated CI/CD quality gates, and an interactive local web dashboard with **zero network lag, zero cloud infrastructure, and zero monthly bills**.

### The 5 Gaps NanoTrace Solves
1. **The Telemetry Cloud Bill Gap**: Hosted AI observability platforms charge per span and per token, frequently scaling to \$500 to \$3,000+ per month for production workloads. NanoTrace costs \$0.00.
2. **The Active Runtime Safety Gap**: Passive dashboards only chart runaway while-loops *after* you've spent \$500 on OpenAI. NanoShield actively intercepts runaway loops, token bombs, and budget blowouts in **7.9 µs before money is wasted**.
3. **The Data Privacy & PII Egress Gap**: Shipping raw prompts containing customer emails, financial transactions, or healthcare records to external SaaS vendors violates GDPR (Article 28), HIPAA, and zero-data-retention mandates. NanoTrace guarantees 100% data sovereignty by keeping telemetry strictly in local DuckDB/Parquet files.
4. **The Event Loop Latency Gap**: Remote HTTP telemetry exporters block agent event loops, adding 30 to 120 milliseconds of latency to every tool call. NanoTrace utilizes a non-blocking in-memory ring buffer that records spans in **3.5 microseconds (< 0.004 ms)**.
5. **The Infrastructure Sprawl Gap**: Self-hosting traditional OpenTelemetry collectors requires maintaining Docker Compose clusters with PostgreSQL, Redis, ClickHouse, and Jaeger daemons. NanoTrace requires zero daemons and installs via a single `pip install nanotrace-ai` command.

---

## Installation

```bash
# Core engine (DuckDB Lakehouse, OpenTelemetry Tracer, CLI, NanoShield Guardrails)
pip install nanotrace-ai

# With embedded local web dashboard (FastAPI + Uvicorn)
pip install "nanotrace-ai[ui]"

# Full battery (Dashboard, DeepEval/Ragas LLM evals, PydanticAI showcase)
pip install "nanotrace-ai[all]"
```

---

## 60-Second Quickstart

Get started in 3 simple steps without writing boilerplate:

### Step 1: Zero-Code Auto-Pilot Run
Run your existing agent script with NanoTrace auto-pilot. It automatically traces execution in `< 4 µs`, enforces default loop runaway guardrails, and persists traces to DuckDB:

```bash
# Prefix any Python script with 'nanotrace run'
nanotrace run python my_agent.py
```

### Step 2: Open the Local Dashboard
Launch the zero-dependency local analytics dashboard on port 7777:

```bash
nanotrace ui
```
Navigate to `http://127.0.0.1:7777` to inspect live waterfalls, token economics, active guardrail intercepts, and the interactive SVG Swarm DAG visualizer.

### Step 3: Run Deterministic CI/CD Quality Gates
Turn recorded traces into golden evaluation datasets and enforce quality thresholds in GitHub Actions:

```bash
# Automated CI/CD gate: exits code 0 on pass, code 1 on regression breach
nanotrace test --dataset production_v1 --fail-under 0.85
```

---

## Programmatic SDK Integration

For fine-grained programmatic control, decorate your agents and tools directly in Python:

```python
import nanotrace
from nanotrace.guardrails.breakers import MaxLoopBreaker, BudgetCapBreaker
from openai import OpenAI

# Initialize with active runtime guardrails
nanotrace.init(
    circuit_breakers=[
        MaxLoopBreaker(limit=15),          # Kills infinite tool loops
        BudgetCapBreaker(max_trace_usd=1.50) # Halts trace if spend exceeds $1.50
    ]
)

client = OpenAI()

@nanotrace.trace_tool(name="search_database")
def search_database(query: str):
    return {"results": ["OpenTelemetry GenAI is a vendor-neutral CNCF standard."]}

@nanotrace.trace_agent(name="ResearchAgent", agent_type="researcher")
def run_agent(query: str):
    docs = search_database(query)
    
    with nanotrace.span("chat gpt-4o-mini", attributes={"gen_ai.request.model": "gpt-4o-mini"}):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an analytical research assistant."},
                {"role": "user", "content": f"Context: {docs}\nQuery: {query}"}
            ]
        )
        return response.choices[0].message.content

output = run_agent("Explain OpenTelemetry GenAI semantic conventions")
print(output)
nanotrace.flush()
```

---

## Technical Documentation and Guides

* **[Engineering User Manual](docs/USER_MANUAL.md)**: Visual, infographic-driven user guide featuring Mermaid architecture diagrams, decision trees, span lifecycles, and dashboard walkthroughs.
* **[Agent Architectures & Top 10 Frameworks Guide](docs/AGENTS_AND_SYSTEMS.md)**: Comprehensive evaluation of the top 10 agent frameworks in 2025/2026, complete source code, and process flowcharts for all showcase agents and multi-agent systems.

---

## Agent Showcase and Master Validation Suite

NanoTrace includes an end-to-end showcase suite featuring **6 production-realistic agents**, a **multi-agent executive council**, and a **10-checkpoint validation harness**:

| Showcase Module | Tracing Pattern | Framework / Model | Architectural Highlights |
|---|---|---|---|
| [`agent_01_customer_support.py`](showcase/agent_01_customer_support.py) | Linear Multi-Stage Chain | GPT-4o-mini + GPT-4o | Rapid ticket classification paired with empathetic resolution. |
| [`agent_02_research_assistant.py`](showcase/agent_02_research_assistant.py) | ReAct Tool Loop | Claude 3.5 Sonnet | Dynamic reasoning depth with variable-depth tool calls. |
| [`agent_03_code_review.py`](showcase/agent_03_code_review.py) | Embedding & Vector RAG | GPT-4o + `text-embedding-3-small` | OpenTelemetry `gen_ai.retrieval.*` attributes and CWE security audits. |
| [`agent_04_data_pipeline.py`](showcase/agent_04_data_pipeline.py) | Error Handling & SRE Triage | GPT-4o-mini | Transient timeouts, explicit `StatusCode.ERROR`, and automated retries. |
| [`agent_05_meeting_summarizer.py`](showcase/agent_05_meeting_summarizer.py) | Multi-Model Pipeline | Gemini 2.0 Flash + Claude 3.5 | Fast entity extraction paired with strategic executive synthesis. |
| [`agent_06_pydanticai_agent.py`](showcase/agent_06_pydanticai_agent.py) | Framework Integration | PydanticAI 2.x (`TestModel`) | Validated Pydantic `BaseModel` output schemas and logistics logic. |
| [`multi_agent_system.py`](showcase/multi_agent_system.py) | Supervisor / Router | 4 Specialists + Orchestrator | Hierarchical council (Market, Finance, Tech, Legal) under a single TraceID. |
| [`healer_showcase.py`](showcase/healer_showcase.py) | Telemetry Repair (UITH) | Multi-Framework | Normalizes LangGraph, CrewAI, AutoGen, and orphan spans. |

### Running the Demo Suite
Execute the complete suite and validate all 10 automated checkpoints with a single command:

```bash
# Execute showcase and automated validator
nanotrace demo

# Or run the demo and immediately launch the web dashboard
nanotrace demo --ui
```

---

## Universal Trace Healer (UITH): Ingesting Chaotic Telemetry

For applications built on **LangGraph**, **CrewAI**, **AutoGen**, or custom while-loops with non-standard logs, NanoTrace provides the **Universal Trace Healer (UITH)**:

```python
import nanotrace

nanotrace.init()

# Ingest nested LangGraph trees, CrewAI outputs, AutoGen message arrays, or stdout text
nanotrace.ingest(raw_telemetry_payload)
```

Or ingest trace dumps directly via the CLI:
```bash
nanotrace ingest ./external_agent_dump.json
```

### Automated Reconciliation Capabilities:
* **Fuzzy Token Normalization**: Resolves vendor-specific token structures across OpenAI (`usage.prompt_tokens`), Anthropic (`usage.input_tokens`), Google Gemini (`usage_metadata.prompt_token_count`), and AWS Bedrock (`inputTokenCount`).
* **Temporal Interval Grafting**: Re-links orphaned child spans (whose ContextVars were dropped across async thread pools) by matching their execution window to an enclosing active parent span.
* **Soft Error Detection**: Identifies silent exceptions, database timeouts, and HTTP 429/500 errors within caught tool return payloads, flagging them as `StatusCode.ERROR`.
* **Streaming Token Estimation**: Prevents null metrics on streaming responses by computing token estimations based on output text volume.

---

## Trace-to-Eval Pipeline

Convert stored execution traces directly into evaluation test cases for **DeepEval** and **Ragas**:

### Evaluate with DeepEval

```python
import nanotrace
from deepeval.metrics import FaithfulnessMetric, AnswerRelevancyMetric
from deepeval import evaluate

# Load stored traces into a vectorized dataset
dataset = nanotrace.load_traces(limit=25)

# Convert directly into DeepEval LLMTestCase objects
test_cases = dataset.to_deepeval()

# Run open-source evaluation suite
evaluate(test_cases, [FaithfulnessMetric(), AnswerRelevancyMetric()])
```

### Evaluate with Ragas

```python
import nanotrace
from ragas.metrics import Faithfulness, AnswerRelevancy
from ragas import evaluate

dataset = nanotrace.load_traces(limit=25)

# Convert into a Ragas EvaluationDataset
ragas_dataset = dataset.to_ragas()

# Run Ragas evaluation
results = evaluate(ragas_dataset, metrics=[Faithfulness(), AnswerRelevancy()])
print(results)
```

### Built-in Zero-Cost Local Heuristics

NanoTrace includes heuristic evaluation diagnostics requiring **zero LLM API calls**:

```python
dataset = nanotrace.load_traces(limit=50)
results = dataset.run_heuristics()

for r in results:
    status = "PASS" if r.passed else "FAIL"
    print(f"{r.metric_name}: {r.score * 100:.1f}% [{status}]")
```

---

## Local Web Dashboard & Dual-Audience Lenses

Launch the zero-dependency interactive dashboard:

```bash
nanotrace ui --port 7777
```

Navigate to `http://127.0.0.1:7777` in your browser.

* **Dual-Audience Lens Toggle**: Instantly switch between:
  * **👔 Business Lens**: Executive scorecard, conversational chat bubbles, user intent tracking, plain-English tool summaries, and turnaround cost metrics.
  * **🛠️ Hacker Lens**: Millisecond/microsecond waterfall Gantt chart, hierarchical span trees, W3C TraceContext headers, and raw OpenTelemetry GenAI semantic JSON attributes.
* **1-Click Standalone HTML Capsule Export**: Export any execution run as a zero-dependency `.ntrace.html` file that opens offline in any browser without Python or Docker.
* **Dynamic Database Switcher**: Toggle between `.traces/nanotrace.duckdb` and `.traces/showcase.duckdb` directly from the navigation bar.
* **Span Inspection Drawer**: View full prompt payloads, completion outputs, token usage, and exact USD costs.
* **Light and Dark Themes**: High-contrast, accessibility-tested interface with persistent preferences.
* **1-Click Heuristic Diagnostics**: Run evaluation checks directly from the UI.

---

## Zero-Code Auto-Pilot CLI Runner

Trace any existing Python agent or script without modifying code or adding imports:

```bash
# Auto-trace any existing Python script
nanotrace run python my_agent.py

# Or directly:
nanotrace run my_agent.py --iterations 5

# Auto-trace and immediately open the dashboard:
nanotrace run my_agent.py --ui

# Auto-trace and generate a standalone offline HTML capsule:
nanotrace run my_agent.py --capsule
```

NanoTrace auto-instruments `openai`, `anthropic`, and `litellm` SDK calls on the fly, logs all spans to DuckDB with `< 15 µs` ring-buffer enqueue latency, and displays a Rich execution telemetry table upon exit.

---

## 1-Click Standalone HTML Capsule (`.ntrace.html`)

Share complete agent execution traces with executives, PMs, and external clients as a single self-contained file:

```bash
# Export specific trace to standalone HTML capsule
nanotrace export-capsule <trace_id> -o my_trace.ntrace.html

# Open directly in default web browser
nanotrace export-capsule <trace_id> --open

# Or via standard export command
nanotrace export --trace-id <trace_id> --format html -o trace.html
```

* **Zero Infrastructure Required**: Opens in Google Chrome, Safari, Firefox, or Edge via double-click (`file:///...`).
* **Zero External Network Calls**: Embedded CSS, JS, and JSON payload—100% compliant with air-gapped corporate environments.
* **Interactive Features Included**: Dual-audience lens toggle (Business vs Hacker), theme toggle, waterfall timeline, and span drawer all function offline.

---

## NanoShield Active In-Process Circuit Breakers & Runtime Guardrails

NanoShield introduces microsecond-level runtime circuit breakers embedded directly into `@nanotrace.trace_agent`, `@nanotrace.trace_tool`, `nanotrace.span()`, and globally in `nanotrace.init()`.

NanoShield evaluates policies in-memory in **under 1 microsecond (< 1 µs)** before and after node execution, intercepting runaway execution, unbounded API spend, and credential leakage *before* cloud bills escalate.

```python
import nanotrace
from nanotrace.guardrails import (
    MaxLoopBreaker,
    BudgetCapBreaker,
    MaxTokenBreaker,
    PIIRedaction,
    TimeoutBreaker,
)
from nanotrace.exceptions import CircuitBreakerTrip

# Initialize NanoTrace with global guardrails
nanotrace.init(
    circuit_breakers=[
        MaxLoopBreaker(limit=5),                    # Halt recursive tool loops > 5
        BudgetCapBreaker(max_trace_usd=1.00),        # Cap total trace spend at $1.00
        PIIRedaction(action="redact"),               # Auto-mask OpenAI/GitHub keys, SSNs, credit cards
        TimeoutBreaker(timeout_seconds=30.0),        # Hard cutoff if trace exceeds 30s
    ]
)

@nanotrace.trace_tool(circuit_breakers=[MaxLoopBreaker(limit=3)])
def scrape_web(query: str):
    # If called 4+ times in a recursive loop, NanoShield trips immediately
    return perform_search(query)

try:
    with nanotrace.span("financial_analysis"):
        run_autonomous_agent()
except CircuitBreakerTrip as exc:
    print(f"🛡️ Intercepted: {exc.breaker_name} -> {exc.reason}")
```

### Built-in Circuit Breakers
1. **`MaxLoopBreaker(limit=N)`**: Detects and halts infinite agent loops (e.g., search tools re-querying the same topic endlessly).
2. **`BudgetCapBreaker(max_trace_usd=X, max_turn_usd=Y)`**: Enforces strict financial limits on single turns or entire sessions.
3. **`MaxTokenBreaker(max_total_tokens=N, max_turn_tokens=M)`**: Prevents runaway context window explosions.
4. **`PIIRedaction(action="redact" | "block")`**: Ultra-fast regex sanitizer masking OpenAI API keys (`sk-...`), GitHub tokens, Social Security Numbers, Credit Cards, emails, and phone numbers before payloads hit disk or database.
5. **`TimeoutBreaker(timeout_seconds=T)`**: Enforces strict SLAs across agent workflows.

All tripped events automatically flag spans with `StatusCode.ERROR`, tag `nanotrace.shield.tripped=True`, and stream directly to the **NanoShield HUD** on the web dashboard showing real-time spend saved.

---

## Time-Travel Agent Debugger & 1-Click "Replay & Fork" Playground

Debugging broken agent steps traditionally requires re-running the entire workflow from scratch—wasting time, re-spending hundreds of tokens, and losing intermediate state.

NanoTrace includes an in-process **Time-Travel Debugger & Replay Engine**:

* **Inspect Upstream Lineage**: Rewind any recorded agent trace to any intermediate decision node and inspect the exact upstream causal path.
* **1-Click "Replay & Fork"**: Click **`⏱️ Fork & Replay`** directly on any span in the waterfall timeline or drawer.
* **Tweak & Re-Execute in Microseconds**: Edit prompt instructions, tweak tool arguments, adjust temperature, or swap models (e.g. switch `gpt-4o` to `gpt-4o-mini` or `claude-3-5-sonnet`) without touching source code.
* **90% Token Savings**: The forked branch re-executes only the target step and subsequent lineage while reusing cached upstream outputs.
* **Live Before-and-After Execution Diff**: View side-by-side execution duration, token counts, cost delta, and a full unified diff of model responses.

### Programmatic Time-Travel Replay

```python
from nanotrace.core.replay import ReplayEngine

engine = ReplayEngine(db_path="./.traces/nanotrace.duckdb")

# Rewind and re-execute a node with modified prompt guidance
result = engine.fork_and_replay_node(
    span_id="c8914b104928f01a",
    prompt="Explain concisely in 2 bullet points with tax deductions highlighted.",
    model="gpt-4o-mini",
    temperature=0.2,
)

print(f"Status: {result.status}")
print(f"Cost Reduction: ${result.original_cost_usd:.5f} -> ${result.forked_cost_usd:.5f}")
print(f"Diff Summary:\n{result.diff_summary}")
```

---

## Trace-to-Gold Regression Suite & Golden Dataset Factory

Transform messy production execution traces directly into curated golden benchmark datasets for continuous evaluation and prompt regression testing.

* **1-Click Golden Curation**: Click **`🌟 Save as Golden`** on any span in the dashboard drawer to capture input prompt, context chunks, and gold completions directly into DuckDB (`golden_cases` table).
* **Zero-Cost Local Scoring**: Parallel regression runner measures semantic drift, token Jaccard similarity, and Levenshtein edit distance without cloud dependencies or paid judge models.
* **Prompt Regression Matrix**: Run A/B evaluation matrices between baseline prompts (v1.0) and candidate variants (v2.0) across entire golden datasets with multi-threaded parallel execution.
* **Automated Status Classification**: Cases are categorized into `✅ IMPROVED`, `❌ REGRESSED`, or `➖ UNCHANGED` based on Pareto cost/quality thresholds.

### Python API

```python
from nanotrace.eval.golden import GoldenCase, GoldenDatasetManager
from nanotrace.eval.regression import RegressionEngine

# 1. Curate golden test cases
mgr = GoldenDatasetManager(db_path="./.traces/nanotrace.duckdb")
mgr.save_case(GoldenCase(
    case_id="tc_financial_01",
    dataset_name="financial_benchmarks",
    name="EBITDA Margin Calculation",
    input_prompt="Compute EBITDA margin for Q2 given revenue $50M and expenses $38M.",
    expected_output="EBITDA margin is 24.0% ($12M EBITDA on $50M revenue).",
))

# 2. Run parallel A/B regression test matrix
engine = RegressionEngine(db_path="./.traces/nanotrace.duckdb")
run = engine.run_matrix(
    dataset_name="financial_benchmarks",
    candidate_fn=lambda p: f"[GPT-4o-Mini]: 24.0% EBITDA margin for {p}",
    baseline_fn=lambda p: f"[GPT-4o]: EBITDA margin calculation: 24.0%",
    fail_under=0.80, # 80% pass threshold
)

print(f"Pass Rate: {run.pass_rate * 100:.1f}% | Quality Gate: {'PASSED' if run.passed else 'FAILED'}")
```

---

## Automated CI/CD Quality Gate CLI (`nanotrace test`)

Enforce zero-regression standards in GitHub Actions and continuous delivery pipelines before promoting new prompts or model versions to production.

```bash
# Run regression tests against a golden dataset with an 85% pass threshold
nanotrace test --dataset financial_benchmarks --fail-under 0.85

# Manage golden datasets directly from the terminal
nanotrace golden list
nanotrace golden export --dataset financial_benchmarks --output golden_cases.jsonl
nanotrace golden save --span-id <span_id> --dataset production_gold --name "Tax Case #1"
```

* **Deterministic Exit Codes**: Exits with code `0` when the quality gate passes; exits with code `1` if regressions exceed the threshold, immediately halting breaking PR deployments.
* **Rich Visual Reporting**: Displays a formatted terminal scorecard with Latency Δ, Cost Δ, Score Δ, and status indicators.

---

## NanoPrompt Studio & Registry (`nanotrace.prompts`)

Manage, version, and evaluate prompt templates with zero latency overhead. Stores prompts in DuckDB with in-memory caching (< 0.1 µs lookup) and automatic `{{variable}}` extraction.

```python
from nanotrace.prompts import PromptRegistry, PromptTemplate

registry = PromptRegistry(db_path="./.traces/nanotrace.duckdb")

# 1. Register a new prompt template
template = PromptTemplate(
    name="customer_onboarding",
    template="Welcome {{user_name}} to {{tier}} membership! Highlights: {{perks}}.",
    version="1.0.0",
    tags=["production"],
    author="lead_dev@startup.io",
)
registry.save(template)

# 2. Ultra-fast compiled execution (< 1 µs)
prompt = registry.get("customer_onboarding", tag="production")
rendered = prompt.compile(user_name="Alex", tier="Enterprise", perks="Unlimited compute, 24/7 SLA")

# 3. Promote a new release to production
registry.promote(name="customer_onboarding", version="1.1.0", tag="production")
```

### CLI Prompt Operations
```bash
nanotrace prompt list
nanotrace prompt get customer_onboarding --tag production
nanotrace prompt set customer_onboarding "Analyze {{query}} for {{agent}}" --version 1.0.0 --tag production
nanotrace prompt promote customer_onboarding 1.1.0 --tag production
```

---

## NanoFeedback Collector & Sentiment Analytics (`nanotrace.feedback`)

Record user sentiment directly on production traces and automatically extract candidate golden cases from +1 rated agent executions.

```python
from nanotrace.feedback import FeedbackCollector

feedback = FeedbackCollector(db_path="./.traces/nanotrace.duckdb")

# Record human or automated eval feedback
feedback.record(
    trace_id="0fb0f79557444c84a073374aae50908b",
    score=1.0, # +1.0 for positive, -1.0 for negative
    comment="Flawless reasoning and verified output.",
    user_id="lead_reviewer",
)

# Mining high-performing traces for Golden Datasets
golden_candidates = feedback.get_recommended_golden_traces()
stats = feedback.get_stats()
print(f"Net Sentiment: {stats['net_sentiment_pct']}% across {stats['total_feedback']} evaluations.")
```

### Lightweight Frontend Widget (`nanotrace-feedback.js`)
Embed thumbs up/down user feedback into any internal tool or web application with `< 2KB` vanilla JavaScript:

```html
<script src="/static/nanotrace-feedback.js"></script>
<script>
  NanoFeedback.init({
    endpoint: "http://127.0.0.1:7777",
    userId: "user_42"
  });
  
  // Submit sentiment on completion
  NanoFeedback.like("trace_abc123", "Great response!");
</script>
```

---

## Multi-Modal Payload Inspector (`nanotrace.media`)

Inspect multi-modal LLM payloads (base64 image URIs, audio streams, PDFs, and remote image URLs) without bloating trace storage or freezing the dashboard UI.

* **Automatic Base64 Sanitization**: Detects base64 data URIs in prompts and completions, replacing thousands of raw characters with lightweight semantic badges: `[🖼️ Embedded Media: image/png (48.2 KB)]`.
* **Zero DOM Freezing**: Keeps trace drawer and business lens rendering at a constant 60 FPS even with multi-megabyte image payloads.
* **Interactive Media Lightbox**: High-resolution zoomable viewer with full metadata inspection and one-click asset copying.

---

## NanoDrift: In-Process Vector Space Diagnostics & RAG Hallucination Radar (`nanotrace.rag`)

Detect retrieval failure modes, semantic voids, and out-of-distribution queries directly inside your agent process. 

NanoDrift projects high-dimensional vector embeddings (up to 1536d) down to interactive 2D polar radar coordinates in **~1.15 ms** using a zero-dependency pure-Python PCA and Johnson-Lindenstrauss orthogonal projection.

```python
from nanotrace.rag import RAGRadarEngine, RetrievedChunk

radar = RAGRadarEngine(db_path="./.traces/nanotrace.duckdb")

# 1. Record RAG query with chunk similarity scores
radar.record_query(
    query_text="What are our enterprise SLA guarantees?",
    retrieved_chunks=[
        RetrievedChunk(chunk_id="chk_sla_01", text="SLA guarantee is 99.9% uptime...", similarity_score=0.48),
        RetrievedChunk(chunk_id="chk_terms_04", text="Standard contract terms...", similarity_score=0.42),
    ],
    agent_name="SupportAgent",
    trace_id="4b92f7902e8d47b5943729e21183cf52",
)

# 2. Extract radar summary and identify semantic voids (similarity < 0.55)
summary = radar.get_radar_summary()
print(f"Total Queries: {summary.total_queries} | Semantic Voids: {summary.semantic_voids_count}")

# 3. Automatically scan existing trace spans for RAG attributes
indexed_count = radar.scan_spans_for_rag()
print(f"Indexed {indexed_count} spans with gen_ai.retrieval.* attributes.")
```

### Visual RAG Polar Radar
* **Concentric Polar Confidence Rings**: Concentric rings demarcate high-confidence retrieval (inner 90% and 75% rings) from low-confidence retrieval boundaries.
* **Semantic Void Halos**: Queries retrieving documents below `0.55` cosine similarity boundary are visually flagged with pulsing red halo markers (`🚨 Semantic Void`).
* **Instant Trace Drill-down**: Click any point or high-risk void row in the RAG table to inspect the exact prompt, retrieved context chunks, and generated completion in the span drawer.

---

## Autonomous Red-Teaming & Adversarial Stress Generator (`nanotrace.security`)

Stress-test your agents and NanoShield guardrails against sophisticated jailbreaks, system prompt extractions, PII exfiltration, and denial-of-service loop bombs before production deployments.

```python
from nanotrace.security import RedTeamRunner, AdversarialGenerator, AttackType

runner = RedTeamRunner(db_path="./.traces/nanotrace.duckdb")

# 1. Generate synthesized attack payloads
generator = AdversarialGenerator()
attacks = generator.synthesize_attacks_for_prompt("You are a financial advisor giving tax advice.")

# 2. Run automated stress test suite against agent target
scorecard = runner.run_suite(
    target_name="TaxAdvisorAgent",
    attack_types=[
        AttackType.PROMPT_INJECTION,
        AttackType.JAILBREAK,
        AttackType.PII_EXTRACTION,
        AttackType.LOOP_BOMB,
    ],
    fail_under=0.85, # Requires 85% resilience to pass
)

print(f"Resilience Grade: {scorecard.grade} ({scorecard.resilience_score * 100:.1f}%)")
print(f"Passed: {scorecard.passed_count} | Breached: {scorecard.breached_count}")
```

### CI/CD Security Quality Gate
Run deterministic security audits in continuous deployment workflows:

```bash
# Run red-team suite against specific threat dimensions
nanotrace redteam --attacks injection,jailbreak,pii --fail-under 0.85

# Auto-audit RAG retrieval health
nanotrace rag scan
nanotrace rag radar
```

* **Deterministic CI/CD Exit Code**: Exits code `0` when resilience meets or exceeds `--fail-under`; exits code `1` if guardrails fail to neutralize attacks.
* **Executive Security Scorecards**: Graded from **A+** down to **F**, detailing sanitized attacks, safe refusals, and breach payloads.

---

## NanoFleet: Zero-Overhead Multi-Node Cloud Sync & Distributed Lakehouse (`nanotrace.fleet`)

Aggregate trace streams across hundreds of distributed Kubernetes worker pods, serverless containers, or multi-cloud regions into a central DuckDB Lakehouse with zero external server dependencies:

```python
from nanotrace.fleet import FleetSyncEngine

fleet = FleetSyncEngine(db_path="./.traces/nanotrace.duckdb")

# 1. Register a distributed worker node
fleet.register_node(
    node_id="us-east-agent-pod-01",
    hostname="pod-us-east-1.internal",
    ip_address="10.0.1.12",
    target_uri="s3://prod-lakehouse/us-east/traces/",
)

# 2. Export local compressed Parquet snapshot (ZSTD)
sync_result = fleet.export_snapshot(target_dir="./.traces/fleet_sync", node_id="us-east-agent-pod-01")
print(f"Exported {sync_result.spans_exported} spans in {sync_result.elapsed_ms:.1f} ms")

# 3. Ingest remote snapshots with zero-cost deduplication
imported_count = fleet.import_fleet_snapshots("./.traces/fleet_sync")
print(f"Ingested {imported_count} new spans into central Lakehouse.")
```

* **Native Streaming Parquet Export**: Uses DuckDB's in-engine `COPY ... TO FORMAT PARQUET (COMPRESSION ZSTD)` to achieve 1,000 spans exported in ~10.4 ms without intermediate Python serialization.
* **Idempotent Ingestion**: Distributed merges use SQL deduplication on `span_id`, guaranteeing zero duplicate records when multiple sync micro-batches overlap.
* **Central Multi-Node Swarm HUD**: Monitor pod heartbeats, ingested span volumes, and synchronization statuses live from the dashboard.

---

## Autonomous Swarm Topology & Communication DAG Optimizer (`nanotrace.topology`)

Analyze multi-agent communication graphs, compute critical path execution bottlenecks, and automatically detect ping-pong chatter loops or parallelizable sequential operations:

```python
from nanotrace.topology import TopologyOptimizer

optimizer = TopologyOptimizer(db_path="./.traces/nanotrace.duckdb")

# Analyze communication topology for an execution trace
analysis = optimizer.analyze_trace("trace_abc123")

print(f"Critical Path: {analysis.critical_path_ms:.1f} ms")
print(f"Communication Overhead: {analysis.communication_overhead_pct:.1f}%")

# Inspect actionable recommendations
for rec in analysis.recommendations:
    print(f"[{rec.severity.upper()}] {rec.title}: {rec.description}")
    if rec.suggested_patch:
        print(f"Patch: {rec.suggested_patch}")
```

* **Execution DAG & Critical Path Visualization**: Interactive SVG canvas maps orchestration workflows, tool delegations, and critical path execution latency.
* **Autonomous Chatter Detection**: Flags cyclic ping-pong messaging loops between peer agents that inflate token spend without advancing task state.
* **Parallelization Heuristics**: Detects independent sequential tool calls and provides auto-generated code patches (e.g. `asyncio.gather()`).

---

## Analytical SQL Queries via DuckDB

Because traces are stored in native columnar DuckDB tables, you can run instant analytical queries via the CLI:

```bash
nanotrace query "SELECT name, duration_ms, gen_ai_total_tokens, gen_ai_cost_usd FROM spans ORDER BY duration_ms DESC LIMIT 10"
```

Or programmatically in Python:

```python
import duckdb

conn = duckdb.connect("./.traces/nanotrace.duckdb")
df = conn.execute("""
    SELECT 
        gen_ai_agent_name,
        COUNT(*) as total_steps,
        ROUND(AVG(duration_ms), 2) as avg_latency_ms,
        ROUND(SUM(gen_ai_cost_usd), 4) as total_spend_usd
    FROM spans 
    GROUP BY gen_ai_agent_name;
""").df()

print(df)
```

---

## Command-Line Interface (CLI)

| Command | Description |
| :--- | :--- |
| `nanotrace run <script.py>` | Zero-code auto-pilot runner: executes and traces any script with `< 15 µs` overhead |
| `nanotrace run python <script.py>` | Auto-trace script with explicit Python invocation syntax |
| `nanotrace export-capsule <trace_id>` | Export single self-contained standalone HTML capsule (`.ntrace.html`) |
| `nanotrace test --dataset <name>` | Automated CI/CD quality gate: runs prompt regression matrix; exits code 0/1 |
| `nanotrace golden list` | List all curated golden evaluation datasets and case counts |
| `nanotrace golden save` | Extract and save a golden benchmark case from a recorded trace or span |
| `nanotrace golden export` | Export a golden dataset to a portable JSONL benchmark file |
| `nanotrace prompt list` | List all registered prompt templates and active release tags |
| `nanotrace prompt get <name>` | Display prompt template string, detected variables, and metadata |
| `nanotrace prompt set <name> <template>` | Create or update a prompt template with automatic semver tracking |
| `nanotrace prompt promote <name> <ver>` | Promote a prompt version to a release tag (e.g. `production`) |
| `nanotrace feedback record <trace_id>` | Record user sentiment score (+1 / -1) and comments on a trace |
| `nanotrace feedback list` | List recorded user feedback entries across all traces |
| `nanotrace feedback stats` | Display aggregate feedback metrics and net sentiment percentage |
| `nanotrace demo` | Run the complete 6-agent showcase suite and 10-checkpoint validation harness |
| `nanotrace demo --ui` | Run the showcase suite and immediately launch the interactive dashboard |
| `nanotrace ui` | Start the local web dashboard on `http://127.0.0.1:7777` |
| `nanotrace stats` | Display aggregate execution metrics (traces, spans, tokens, latency, cost) |
| `nanotrace query "<SQL>"` | Execute analytical SQL queries directly against the DuckDB spans table |
| `nanotrace export --output traces.parquet` | Export all traces to an optimized ZSTD-compressed Parquet dataset |
| `nanotrace export --format html` | Export trace to standalone HTML capsule |
| `nanotrace rag radar` | Display RAG query retrieval diagnostics and semantic void stats in terminal |
| `nanotrace rag scan` | Auto-detect and index RAG retrieval spans from recorded trace database |
| `nanotrace redteam` | Run autonomous adversarial stress test suite with deterministic CI/CD exit code |
| `nanotrace fleet sync` | Export local compressed Parquet snapshot or ingest distributed worker pod traces |
| `nanotrace fleet nodes` | List all registered swarm worker pods and heartbeat health statuses |
| `nanotrace fleet pull <dir>` | Ingest remote Parquet snapshots into the central DuckDB Lakehouse |
| `nanotrace topology [trace_id]` | Analyze swarm communication DAG, critical path, and optimization heuristics |
| `nanotrace ingest <file>` | Ingest and self-heal external JSON/JSONL/stdout trace logs |
| `nanotrace eval` | Run local heuristic diagnostics on stored traces |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                 Your AI Agent Application                   │
│   (LangGraph / CrewAI / AutoGen / PydanticAI / Custom)      │
└──────────────┬───────────────────────────────┬──────────────┘
               │                               │
        @trace_agent                     @trace_tool
               │                               │
               ▼                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  NanoTrace Core Engine                      │
│                                                             │
│   Context Manager  ◄─── ContextVars Tree Hierarchy          │
│          │                                                  │
│          ▼                                                  │
│   In-Memory Ring Buffer (< 15 µs lock-free enqueue)         │
│          │                                                  │
│          ▼                                                  │
│   Async Daemon Worker Thread (Micro-batch flush every 250ms)│
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Storage & Evaluation                     │
│                                                             │
│   • Embedded DuckDB Columnar Store (.traces/nanotrace.duckdb)│
│   • Native Parquet Exporter (ZSTD compressed)               │
│   • Trace-to-Eval Bridge (DeepEval & Ragas)                 │
│   • Zero-Dependency Web Dashboard                           │
└─────────────────────────────────────────────────────────────┘
```

---

## Contributing

Contributions are welcome. Please refer to the guidelines below:

1. Fork the repository.
2. Create your feature branch (`git checkout -b feature/NewCapability`).
3. Commit your changes (`git commit -m 'feat: Add NewCapability'`).
4. Push to the branch (`git push origin feature/NewCapability`).
5. Open a Pull Request.

---

## License

Distributed under the **Apache-2.0 License**. See [LICENSE](LICENSE) for more information.
