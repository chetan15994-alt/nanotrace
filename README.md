<div align="center">

# ⚡️ NanoTrace

### Ultra-Low Latency, Zero-Infra OpenTelemetry Tracing & Evaluation Engine for AI Agents
**The DuckDB of AI Observability.**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![OTel GenAI Compliant](https://img.shields.io/badge/OpenTelemetry-GenAI_v1.27-purple.svg)](https://opentelemetry.io)
[![Zero Infra](https://img.shields.io/badge/Infra-$0.00_Local_First-emerald.svg)](#why-nanotrace)

<p align="center">
  <b>Capture agent loops, tool executions, and LLM calls in microseconds.</b><br>
  Persist directly to embedded DuckDB / Parquet. Zero Docker containers. Zero SaaS bills.<br>
  Transform traces directly into <b>DeepEval</b> & <b>Ragas</b> evaluation datasets with 1 line of code.
</p>

---

</div>

## 💡 The Problem with Existing AI Observability

Modern agent tracing platforms (Langfuse, LangSmith, Arize SaaS, Datadog) are powerful, but they bring massive trade-offs:
1. **High Cost:** Ingestion fees per span or per token quickly explode to \$100s–\$1000s/month.
2. **Heavy Infrastructure:** Self-hosting requires spinning up Docker Compose clusters with PostgreSQL, Redis, ClickHouse, and MinIO—often demanding 4GB+ RAM just for local development.
3. **High Latency Overhead:** Synchronous HTTP tracing calls can add 20–100ms per agent step or LLM streaming chunk.
4. **The Trace-to-Eval Gap:** Bridging traces into evaluation suites like DeepEval or Ragas requires tedious custom parsing and glue scripts.

## 🚀 Why NanoTrace?

NanoTrace takes a radical **local-first, embedded approach** inspired by SQLite and DuckDB:

* **⚡️ Microsecond Latency (< 15 µs overhead):** Spans are pushed into an in-memory ring buffer. Main agent threads and token streams are never blocked.
* **💾 Zero Infrastructure ($0.00 Cost):** Runs inside your Python process. Persists directly to an embedded DuckDB database file (`.traces/nanotrace.duckdb`) or native Parquet. No Docker required.
* **🌐 CNCF OpenTelemetry GenAI Standard:** Implements the official `gen_ai.*` semantic conventions (Provider, Model, Tokens, Tools, Agent ID, Finish Reasons, W3C `traceparent`).
* **🤖 Universal & Framework-Agnostic:** Works with any agent framework (**CrewAI**, **LangGraph**, **AutoGen**, **LlamaIndex**, **DSPy**) or raw SDKs (**OpenAI**, **Anthropic**, **Gemini**, **Ollama**).
* **🎯 Native Trace-to-Eval Bridge:** Convert logged agent runs into **DeepEval `LLMTestCase`** or **Ragas `EvaluationDataset`** in 1 line of code.
* **🖥️ Standalone Interactive Web UI:** Built-in dark-mode trace waterfall dashboard (`nanotrace ui`) requiring **zero npm / webpack dependencies**.

---

## 📊 Performance Benchmark

| Tracing Architecture | Main Thread Latency | Background RAM | Infra Required | Cloud Ingest Cost |
| :--- | :--- | :--- | :--- | :--- |
| **NanoTrace (DuckDB Buffer)** | **~12 µs** | **~15 MB** | **None (`pip install`)** | **$0.00** |
| Remote SaaS (Langfuse / Datadog) | ~20,000–80,000 µs (20-80ms) | ~40 MB | Cloud Account | $50 – $500+/mo |
| Self-Hosted Collector Cluster | ~500–2,000 µs (0.5-2ms) | ~1,500–4,000 MB | Docker + Postgres + ClickHouse | Server hosting cost |

---

## 📦 Installation

```bash
pip install nanotrace
```

Or install with full UI and evaluation support:

```bash
pip install "nanotrace[all]"
```

---

## 📖 Engineering User Manual & Architecture Guide

For an in-depth visual walkthrough with Mermaid flowcharts, sequence diagrams, and tree architectures across 6 distinct agent design patterns and multi-agent systems, read the **[Complete User Manual](docs/USER_MANUAL.md)**.

---

## 🎪 Agent Showcase & Master Test Harness

NanoTrace includes an end-to-end showcase suite featuring **6 production-realistic agents**, a **multi-agent executive council**, and a **10-checkpoint validation harness**:

| Showcase Module | Tracing Pattern | Framework / Model | Highlights |
|---|---|---|---|
| [`agent_01_customer_support.py`](showcase/agent_01_customer_support.py) | Linear Multi-Stage Chain | GPT-4o-mini + GPT-4o | Ticket classification & empathetic customer resolution |
| [`agent_02_research_assistant.py`](showcase/agent_02_research_assistant.py) | ReAct Tool Loop | Claude 3.5 Sonnet | Dynamic reasoning depth & variable-depth tool calls |
| [`agent_03_code_review.py`](showcase/agent_03_code_review.py) | Embedding & Vector RAG | GPT-4o + text-embedding-3-small | OTel `gen_ai.retrieval.*` attributes & CWE security audits |
| [`agent_04_data_pipeline.py`](showcase/agent_04_data_pipeline.py) | Error Handling & SRE Triage | GPT-4o-mini | Transient timeouts, `StatusCode.ERROR`, & automated retries |
| [`agent_05_meeting_summarizer.py`](showcase/agent_05_meeting_summarizer.py) | Multi-Model Pipeline | Gemini 2.0 Flash + Claude 3.5 | Fast extraction paired with strategic executive synthesis |
| [`agent_06_pydanticai_agent.py`](showcase/agent_06_pydanticai_agent.py) | Framework Integration | PydanticAI 2.x (TestModel) | Validated Pydantic `BaseModel` outputs & supply chain logic |
| [`multi_agent_system.py`](showcase/multi_agent_system.py) | Supervisor / Router | 4 Specialists + Orchestrator | Hierarchical council (Market, Finance, Tech, Legal) under single TraceID |
| [`healer_showcase.py`](showcase/healer_showcase.py) | Telemetry Repair (UITH) | Multi-Framework | Reconciles LangGraph, CrewAI, AutoGen, and orphan spans |

Run the complete suite and validate all 10 checkpoints with a single command:
```bash
python showcase/run_all_and_validate.py
```

---

## ⚡️ Quickstart in 30 Seconds

### 1. Basic Agent Tracing

```python
import nanotrace
from openai import OpenAI

# 1. Initialize once (creates ./.traces/nanotrace.duckdb)
nanotrace.init()

client = OpenAI()

# 2. Decorate your agent functions & tools
@nanotrace.trace_tool(name="search_database")
def search_database(query: str):
    return {"results": ["OpenTelemetry GenAI is a vendor-neutral standard."]}

@nanotrace.trace_agent(name="ResearchAgent")
def run_agent(query: str):
    # Tool call (automatically linked as child span)
    docs = search_database(query)
    
    # LLM call within context
    with nanotrace.span("llm_reasoning", attributes={"gen_ai.request.model": "gpt-4o-mini"}):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a research assistant."},
                {"role": "user", "content": f"Context: {docs}\nQuery: {query}"}
            ]
        )
        return response.choices[0].message.content

# Run agent
output = run_agent("Explain OpenTelemetry GenAI")
print(output)
```

---

## 🩺 Universal Trace Healer: Ingest Chaotic Telemetry

Have an existing agent built with **LangGraph**, **CrewAI**, **AutoGen**, or custom spaghetti loops with non-standard logs? NanoTrace includes a built-in **Universal Trace Healer (UITH)**:

```python
import nanotrace

nanotrace.init()

# Ingest messy LangGraph trees, CrewAI task outputs, AutoGen message arrays, or raw JSON
nanotrace.ingest(haywire_payload)
```

Or ingest trace dumps directly via the CLI:
```bash
nanotrace ingest ./messy_traces.json
```

**NanoTrace automatically:**
* **Fuzzy-reconciles tokens & models:** Maps fragmented vendor keys across OpenAI (`usage.prompt_tokens`), Anthropic (`usage.input_tokens`), Google Gemini (`usage_metadata.prompt_token_count`), and Bedrock (`inputTokenCount`).
* **Heals broken trees (Temporal Grafting):** Automatically re-grafts orphaned child spans whose ContextVars were lost across async thread pools.
* **Catches silent tool errors:** Scans return payloads for unhandled tracebacks, SQL errors, and 404s, even if caught in `try...except`.
* **Estimates missing streaming tokens:** Ensures token counts and costs are never zero or null.

---

## 🎯 1-Line Trace-to-Eval Bridge

Convert production or test traces directly into evaluation test cases for **DeepEval** and **Ragas**:

### Evaluate with DeepEval

```python
import nanotrace
from deepeval.metrics import FaithfulnessMetric, AnswerRelevancyMetric
from deepeval import evaluate

# Load recent traces from DuckDB
dataset = nanotrace.load_traces(limit=20)

# Convert to DeepEval LLMTestCase objects
test_cases = dataset.to_deepeval()

# Run open-source evaluation (100% free)
evaluate(test_cases, [FaithfulnessMetric(), AnswerRelevancyMetric()])
```

### Evaluate with Ragas

```python
import nanotrace
from ragas.metrics import Faithfulness, AnswerRelevancy
from ragas import evaluate

dataset = nanotrace.load_traces(limit=20)

# Convert to Ragas EvaluationDataset
ragas_dataset = dataset.to_ragas()

# Run Ragas evaluation
results = evaluate(ragas_dataset, metrics=[Faithfulness(), AnswerRelevancy()])
print(results)
```

### Built-in Zero-Cost Local Heuristics

NanoTrace also comes with built-in heuristic evaluators that require **zero LLM API calls**:

```python
dataset = nanotrace.load_traces(limit=50)
results = dataset.run_heuristics()

for r in results:
    print(f"{r.metric_name}: {r.score * 100:.1f}% [{'PASS' if r.passed else 'FAIL'}]")
```

---

## 🖥️ Interactive Web UI Dashboard

Visualize trace trees, inspect prompts, tool inputs, streaming tokens, and latency waterfalls in a sleek dark-mode dashboard:

```bash
nanotrace ui --port 7777
```

Navigate to `http://localhost:7777` in your browser.

* Real-time trace waterfall visualization.
* Model breakdown, token counts, and cost calculator.
* Inspect full OpenTelemetry GenAI JSON payloads.
* 1-Click Heuristic Diagnostics.

---

## 🔍 Analytical SQL Queries via DuckDB

Because traces are stored in native columnar DuckDB format, you can run instant SQL analytics:

```bash
# Direct CLI SQL Query
nanotrace query "SELECT name, duration_ms, gen_ai_total_tokens, gen_ai_cost_usd FROM spans ORDER BY duration_ms DESC LIMIT 10"
```

Or query programmatically in Python:

```python
import duckdb

conn = duckdb.connect("./.traces/nanotrace.duckdb")
df = conn.execute("""
    SELECT 
        gen_ai_agent_name,
        COUNT(*) as total_steps,
        AVG(duration_ms) as avg_latency_ms,
        SUM(gen_ai_cost_usd) as total_spend
    FROM spans 
    GROUP BY gen_ai_agent_name
""").df()

print(df)
```

---

## 🛠️ CLI Reference

| Command | Description |
| :--- | :--- |
| `nanotrace stats` | Display aggregate metrics table (spans, tokens, latency, cost) |
| `nanotrace ui` | Launch local web dashboard |
| `nanotrace query "<SQL>"` | Execute SQL queries directly against the DuckDB spans table |
| `nanotrace export --output traces.parquet` | Export all traces to an optimized ZSTD-compressed Parquet file |
| `nanotrace eval` | Run local heuristic diagnostics on all traces |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 Your AI Agent Application                   │
│   (CrewAI / LangGraph / AutoGen / LlamaIndex / Custom)      │
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
│   Async Daemon Worker Thread (Batch flush every 250ms)      │
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

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

Distributed under the **Apache-2.0 License**. See [LICENSE](LICENSE) for more information.
