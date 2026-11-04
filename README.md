<div align="center">

# NanoTrace

### High-Performance OpenTelemetry Tracing and Evaluation Engine for AI Agents

**The DuckDB of AI Observability**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python Version](https://img.shields.io/badge/Python-3.9%20--%203.14-blue.svg)](https://www.python.org/downloads/)
[![Standard](https://img.shields.io/badge/OpenTelemetry-GenAI_v1.27-purple.svg)](https://opentelemetry.io)
[![Architecture](https://img.shields.io/badge/Architecture-In--Process_Embedded-emerald.svg)](#architecture)
[![Storage](https://img.shields.io/badge/Storage-DuckDB_%2B_Parquet-orange.svg)](https://duckdb.org)

<p align="center">
  Record agent loops, tool executions, and LLM calls in microseconds.<br>
  Persist directly to embedded DuckDB and Parquet. Zero Docker containers. Zero SaaS bills.<br>
  Transform execution traces directly into DeepEval and Ragas evaluation datasets in one line of code.
</p>

---

</div>

## Executive Summary

### What is NanoTrace?
NanoTrace is an embedded, zero-cost OpenTelemetry tracing and evaluation engine designed specifically for AI agents, multi-agent swarms, and LLM applications. It provides enterprise-grade observability by running entirely inside your Python application process, persisting traces to an embedded DuckDB columnar file (`./.traces/nanotrace.duckdb`) and native ZSTD-compressed Parquet.

### The Analogy
Consider how database architectures evolved: traditional enterprise database platforms (Oracle, Snowflake) required remote server clusters, cloud credentials, network hops, and expensive subscriptions. SQLite and DuckDB revolutionized this paradigm by embedding powerful relational and analytical database engines directly into application processes.

**NanoTrace applies this exact principle to AI observability:**
Instead of routing your application's prompts, tool arguments, and customer data over the public internet to costly third-party hosted SaaS collectors (such as Datadog, LangSmith, or Arize), NanoTrace captures telemetry in-process with under 15 microseconds of overhead. You gain instant OpenTelemetry compliance, an interactive timeline dashboard, and evaluation datasets with zero network lag, zero cloud infrastructure, and zero monthly bills.

### The Gaps NanoTrace Solves
1. **The Telemetry Cloud Bill Gap**: Hosted AI observability platforms charge per span and per token, frequently scaling to \$500 to \$3,000+ per month for production workloads. NanoTrace costs \$0.00.
2. **The Data Privacy and PII Egress Gap**: Shipping raw prompts containing customer emails, financial transactions, or healthcare records to external SaaS vendors violates GDPR (Article 28), HIPAA, and enterprise zero-data-retention mandates. NanoTrace guarantees 100% data sovereignty by keeping telemetry strictly on-premises.
3. **The Event Loop Latency Gap**: Remote HTTP telemetry exporters block agent event loops, adding 30 to 120 milliseconds of latency to every tool call and streaming token chunk. NanoTrace utilizes a non-blocking in-memory ring buffer that records spans in under 15 microseconds (< 0.015ms).
4. **The Trace-to-Evaluation Gap**: Bridging production logs into evaluation frameworks (like DeepEval and Ragas) traditionally requires custom data scraping, formatting scripts, and glue code. NanoTrace exports directly to evaluation-ready datasets via a native 1-line Python API.
5. **The Infrastructure Sprawl Gap**: Self-hosting traditional OpenTelemetry collectors requires maintaining Docker Compose clusters with PostgreSQL, Redis, ClickHouse, and Jaeger daemons. NanoTrace requires zero daemons and installs via a single `pip install nanotrace` command.

### Target Personas
* **AI Startups and Independent Builders**: Allocate engineering budgets toward model compute rather than monitoring infrastructure, while gaining immediate debugging visibility.
* **Regulated Enterprise Engineering Teams (FinTech, Healthcare, Defense)**: Gain full AI governance and auditability without exposing confidential data or PII to third-party cloud services.
* **AI Benchmark Researchers**: Execute hundreds of thousands of benchmark agent loops (e.g., SWE-bench, GAIA) without hitting SaaS ingestion quotas or incurring per-event fees.
* **Local-First Developers**: Build, test, and debug agents completely offline without internet connectivity or external API dependencies.

---

## Performance Benchmark

| Tracing Architecture | Main Thread Latency | Background RAM | Required Infrastructure | Monthly Cloud Ingestion Cost |
| :--- | :--- | :--- | :--- | :--- |
| **NanoTrace (Embedded DuckDB)** | **~12 µs (< 0.015 ms)** | **~15 MB** | **None (`pip install`)** | **$0.00** |
| Remote SaaS (Langfuse / Datadog) | ~20,000–80,000 µs (20–80 ms) | ~40 MB | External Cloud Account | $50 – $500+/month |
| Self-Hosted Collector Cluster | ~500–2,000 µs (0.5–2 ms) | ~1,500–4,000 MB | Docker + Postgres + ClickHouse | Server hosting expenses |

---

## Installation

```bash
# Standard installation
pip install nanotrace

# Installation with interactive dashboard and evaluation bridges
pip install "nanotrace[all]"
```

---

## Quickstart

### 1. Instrumenting Agents and Tools

```python
import nanotrace
from openai import OpenAI

# Initialize the embedded trace engine (creates ./.traces/nanotrace.duckdb)
nanotrace.init()

client = OpenAI()

# Decorate tool execution
@nanotrace.trace_tool(name="search_database")
def search_database(query: str):
    return {"results": ["OpenTelemetry GenAI is a vendor-neutral CNCF standard."]}

# Decorate agent workflow
@nanotrace.trace_agent(name="ResearchAgent", agent_type="researcher")
def run_agent(query: str):
    # Tool call (automatically recorded as a child span)
    docs = search_database(query)
    
    # LLM reasoning step with GenAI attributes
    with nanotrace.span("chat gpt-4o-mini", attributes={"gen_ai.request.model": "gpt-4o-mini"}):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an analytical research assistant."},
                {"role": "user", "content": f"Context: {docs}\nQuery: {query}"}
            ]
        )
        return response.choices[0].message.content

# Execute workflow
output = run_agent("Explain OpenTelemetry GenAI semantic conventions")
print(output)

# Force flush remaining spans to storage
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

## Local Web Dashboard

Launch the zero-dependency interactive dashboard:

```bash
nanotrace ui --port 7777
```

Navigate to `http://127.0.0.1:7777` in your browser.

* **Waterfall Timeline Ruler**: Millisecond-accurate span visualization.
* **Dynamic Database Switcher**: Toggle between `.traces/nanotrace.duckdb` and `.traces/showcase.duckdb` directly from the navigation bar.
* **Span Inspection Drawer**: View full prompt payloads, completion outputs, token usage, and exact USD costs.
* **Light and Dark Themes**: High-contrast, accessibility-tested interface.
* **1-Click Heuristic Diagnostics**: Run evaluation checks directly from the UI.

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
| `nanotrace demo` | Run the complete 6-agent showcase suite and 10-checkpoint validation harness |
| `nanotrace demo --ui` | Run the showcase suite and immediately launch the interactive dashboard |
| `nanotrace ui` | Start the local web dashboard on `http://127.0.0.1:7777` |
| `nanotrace stats` | Display aggregate execution metrics (traces, spans, tokens, latency, cost) |
| `nanotrace query "<SQL>"` | Execute analytical SQL queries directly against the DuckDB spans table |
| `nanotrace export --output traces.parquet` | Export all traces to an optimized ZSTD-compressed Parquet dataset |
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
