# NanoTrace User Manual: Architecture, Workflows & Infographics

The DuckDB of AI Observability — An in-process, zero-overhead OpenTelemetry tracing and evaluation engine for AI agents and LLMs.

---

## 1. System Architecture & End-to-End Dataflow

NanoTrace eliminates external telemetry infrastructure by embedding directly inside your Python application process. Traces are enqueued into an in-memory ring buffer in microseconds, flushed asynchronously by a daemon thread, and stored in an embedded DuckDB columnar file or native Parquet.

```mermaid
flowchart TD
    subgraph ExecutionPlane["Execution Plane (User Agent Process)"]
        UserAgent["Agent Orchestrator\n(@trace_agent)"]
        SubAgent["Specialist Sub-Agent\n(@trace_agent)"]
        Tools["Tool Invocations\n(@trace_tool)"]
        LLMCalls["LLM API Calls\n(OpenAI, Anthropic, Gemini, Bedrock)"]
        
        UserAgent --> SubAgent
        SubAgent --> Tools
        SubAgent --> LLMCalls
    end

    subgraph TelemetryPlane["Telemetry Plane (NanoTrace In-Process)"]
        Context["ContextVars Stack\n(Maintains parent_span_id & trace_id)"]
        RingBuffer["Lock-Free Ring Buffer\n(Latency: <15 µs | Zero main-thread blocking)"]
        DaemonWorker["Micro-Batch Daemon Thread\n(Vectorized flush every 250ms)"]
        
        UserAgent -.-> Context
        SubAgent -.-> Context
        Tools -.-> Context
        LLMCalls -.-> Context
        Context --> RingBuffer
        RingBuffer --> DaemonWorker
    end

    subgraph StoragePlane["Storage Plane (Local-First Lakehouse)"]
        DuckDBFile[("DuckDB Columnar Store\n./.traces/nanotrace.duckdb")]
        ParquetFile["ZSTD Compressed Parquet\n./traces.parquet"]
        
        DaemonWorker --> DuckDBFile
        DuckDBFile -.->|COPY TO PARQUET| ParquetFile
    end

    subgraph AnalyticsPlane["Analytics & Consumption Plane"]
        WebUI["Local Dashboard\n(nanotrace ui :7777)"]
        EvalBridge["Trace-to-Eval Bridge\n(DeepEval & Ragas)"]
        DirectSQL["Analytical SQL\n(p50/p95 latency, token spend)"]
        
        DuckDBFile --> WebUI
        DuckDBFile --> EvalBridge
        DuckDBFile --> DirectSQL
    end

    style ExecutionPlane fill:#f8fafc,stroke:#94a3b8,stroke-width:1px
    style TelemetryPlane fill:#eff6ff,stroke:#60a5fa,stroke-width:1px
    style StoragePlane fill:#f0fdf4,stroke:#4ade80,stroke-width:1px
    style AnalyticsPlane fill:#faf5ff,stroke:#c084fc,stroke-width:1px
```

---

## 2. Decision Matrix: Choosing the Right Tracing API

```mermaid
flowchart TD
    Start{"What are you instrumenting?"}
    
    Start -->|Top-level Agent function or class| AgentChoice["Use @nanotrace.trace_agent\nRecords inputs, outputs, agent type & lifecycle"]
    Start -->|Tool, API integration or database lookup| ToolChoice["Use @nanotrace.trace_tool\nRecords arguments, status, and outputs"]
    Start -->|Raw block of code or inline LLM call| SpanChoice["Use with nanotrace.span(...)\nFine-grained custom span attributes"]
    Start -->|Pre-existing JSON logs or external framework| IngestChoice["Use nanotrace.ingest(data)\nUniversal Trace Healer (UITH)"]
    
    AgentChoice --> Enqueue["Auto-propagates W3C traceparent via Python ContextVars"]
    ToolChoice --> Enqueue
    SpanChoice --> Enqueue
    IngestChoice --> Enqueue
```

---

## 3. Span Lifecycle: From Creation to Columnar Storage

The following sequence diagram traces the complete lifecycle of a single span—demonstrating how main-thread execution overhead is isolated to under 15 microseconds:

```mermaid
sequenceDiagram
    autonumber
    participant App as User Agent Thread
    participant Ctx as ContextVars Stack
    participant Buffer as In-Memory Ring Buffer
    participant Worker as Background Daemon
    participant DuckDB as DuckDB Storage

    App->>Ctx: 1. Enter @trace_agent or span()
    Note over Ctx: Capture start_time_ns<br/>Attach parent_span_id from active context
    App->>App: 2. Execute business logic & tool calls
    App->>Ctx: 3. Exit block / return result
    Note over Ctx: Capture end_time_ns & duration<br/>Attach completion payload & token usage
    App->>Buffer: 4. push(span) [< 15 µs lock-free enqueue]
    Note over App: Main agent thread immediately resumes!
    
    loop Every 250ms Background Flush
        Worker->>Buffer: 5. drain(batch_size=500)
        Buffer-->>Worker: List[Span]
        Worker->>DuckDB: 6. executemany(INSERT INTO spans, rows)
        Note over DuckDB: Vectorized columnar write
    end
```

---

## 4. Multi-Agent Orchestration & Trace Hierarchy

In a multi-agent system, multiple specialized agents execute sequentially or in parallel. NanoTrace automatically nests child spans under their calling agent's span using Python `contextvars`, guaranteeing that all spans share a single root `trace_id`.

```mermaid
graph TD
    Root["StartupOrchestratorSupervisor [Root Span]\nTraceID: 48d5b6c... | Model: gpt-4o-mini"]
    
    Root --> Router["chat gpt-4o-mini (Intent Routing)\nParent: Root | in: 48 tok, out: 12 tok"]
    Root --> Spec1["TechnicalArchitectAgent [Sub-Agent Span]\nParent: Root | Agent Type: specialist_tech"]
    Root --> Spec2["FinancialAdvisorAgent [Sub-Agent Span]\nParent: Root | Agent Type: specialist_finance"]
    Root --> Consensus["chat gpt-4o (Executive Consensus)\nParent: Root | Synthesis of domain inputs"]
    
    Spec1 --> Tool1["tool: benchmark_latency_db\nParent: Tech Specialist | Duration: 22ms"]
    Spec1 --> Tool2["tool: infra_cost_estimator\nParent: Tech Specialist | Duration: 15ms"]
    Spec1 --> LLM1["chat gpt-4o (Architecture Spec)\nParent: Tech Specialist | Duration: 48ms"]
    
    Spec2 --> Tool3["tool: runway_calculator\nParent: Finance Specialist | Duration: 14ms"]
    Spec2 --> Tool4["tool: unit_economics_modeler\nParent: Finance Specialist | Duration: 16ms"]
    Spec2 --> LLM2["chat gpt-4o (Financial Modeling)\nParent: Finance Specialist | Duration: 52ms"]

    style Root fill:#dbeafe,stroke:#3b82f6,stroke-width:2px
    style Spec1 fill:#e0e7ff,stroke:#6366f1,stroke-width:1px
    style Spec2 fill:#fce7f3,stroke:#ec4899,stroke-width:1px
    style Consensus fill:#dcfce7,stroke:#22c55e,stroke-width:1px
```

---

## 5. Universal Trace Healer: Ingesting Non-Standard Telemetry

When working with external frameworks (LangGraph, CrewAI, AutoGen) or unstructured logs, telemetry often arrives with missing parent links, fragmented token keys, or unhandled exceptions. The Universal Trace Healer (UITH) automatically repairs these logs:

```mermaid
flowchart LR
    subgraph DirtyLogs["Chaotic Ingestion Payloads"]
        LangGraph["LangGraph Run Tree\n(nested child_runs)"]
        CrewAI["CrewAI Task Dump\n(tasks_output array)"]
        AutoGen["AutoGen Message Array\n(role/content turns)"]
        ReAct["ReAct Stdout Log\n(Thought/Action text)"]
        Orphans["Disconnected Spans\n(Lost parent_span_id)"]
    end

    subgraph HealerPipeline["TraceHealer Normalization Stages"]
        P1["1. Parser & Deconstructor\nState machine & JSON unwrapper"]
        P2["2. Fuzzy Token Normalizer\nMap OpenAI, Anthropic, Gemini, Bedrock"]
        P3["3. Temporal Interval Grafter\nMatch orphan timestamps to enclosing parent"]
        P4["4. Soft Error Detector\nScan return values for tracebacks & 429s"]
    end

    subgraph Canonical["Standardized Sink"]
        OTelSpans["CNCF OpenTelemetry GenAI v1.27 Spans"]
        DuckDBLakehouse[("DuckDB Storage")]
    end

    DirtyLogs --> P1
    P1 --> P2
    P2 --> P3
    P3 --> P4
    P4 --> OTelSpans
    OTelSpans --> DuckDBLakehouse
```

### Key Healer Capabilities:
1. **Temporal Interval Grafting**: If a child span loses its `parent_span_id` (e.g. across `ThreadPoolExecutor` threads), NanoTrace identifies the parent span active during the child's `[start_time_ns, end_time_ns]` window and grafts it automatically.
2. **Fuzzy Token Normalization**: Resolves vendor-specific token structures (`prompt_tokens`, `input_tokens`, `prompt_token_count`, `inputTokenCount`) into canonical `gen_ai.usage.input_tokens`.
3. **Soft Error Detection**: Inspects tool return strings for exceptions and HTTP errors (`404 Not Found`, `429 Rate Limit`, `Traceback`), marking the span with `StatusCode.ERROR` even if caught in user code.

---

## 6. Trace-to-Eval Pipeline Dataflow

Observability data in NanoTrace feeds directly into offline and real-time evaluation frameworks:

```mermaid
flowchart TD
    DuckDBStore[("DuckDB Spans Table")] --> Load["nanotrace.load_traces(limit=100)"]
    Load --> Dataset["TraceDataset (In-Memory Vectorized Collection)"]
    
    Dataset --> Path1["dataset.to_deepeval()"]
    Dataset --> Path2["dataset.to_ragas()"]
    Dataset --> Path3["dataset.run_heuristics()"]
    
    Path1 --> DeepEvalOut["DeepEval LLMTestCase Objects\n• input: prompt_payload\n• actual_output: completion_payload\n• retrieval_context: documents\n• latency: duration_ms"]
    Path2 --> RagasOut["Ragas EvaluationDataset\n• user_input: prompt\n• response: completion\n• retrieved_contexts: chunks"]
    Path3 --> HeuristicsOut["Local Heuristic Diagnostic Results\n• Token Cost Anomalies\n• Latency Outlier Breaches\n• Error Status Assertions"]

    style DuckDBStore fill:#fef3c7,stroke:#f59e0b,stroke-width:1px
    style Dataset fill:#e0f2fe,stroke:#0284c7,stroke-width:1px
```

---

## 7. Interactive Dashboard: Component Architecture

The local web dashboard (`nanotrace ui`) provides zero-dependency visual debugging:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ NanoTrace v0.1.0  [ 🦆 showcase.duckdb (262 spans) ▾ ]  [☀️/🌙]  [Refresh]   │
├─────────────────┬──────────────────┬──────────────────┬─────────────────────┤
│ Total Traces: 51│ Total Spans: 262 │ Tokens: 16,462   │ Est. Spend: $0.0625 │
├─────────────────┴──────────────────┴──────────────────┴─────────────────────┤
│ TRACES EXPLORER │ WATERFALL TIMELINE RULER & SPAN INSPECTION                │
│ ┌─────────────┐ │ 0ms               25ms               50ms            75ms │
│ │Search: [   ]│ │ ├───────────────────┼──────────────────┼────────────────┤ │
│ ├─────────────┤ │ ▼ StartupOrchestratorSupervisor                 (78.2 ms) │
│ │StartupSuper │ │   ├── chat gpt-4o-mini (Router)                 (12.4 ms) │
│ │Duration:78ms│ │   ▼ TechnicalArchitectAgent                     (42.1 ms) │
│ │Spans: 7     │ │     ├── tool: benchmark_latency_db              (22.0 ms) │
│ │Status: OK   │ │     └── chat gpt-4o (Architecture Spec)         (18.5 ms) │
│ ├─────────────┤ │                                                           │
│ │CodeReview   │ │ SPAN DETAIL DRAWER: tool: benchmark_latency_db            │
│ │Duration:56ms│ │ • Provider: custom  • Model: DuckDB  • Status: OK         │
│ │Status: OK   │ │ • Arguments: {"engines": ["DuckDB", "Postgres"]}          │
│ └─────────────┘ │ • Output: {"DuckDB_p50_ms": 1.2, "PostgreSQL_p50_ms": 142}│
└─────────────────┴───────────────────────────────────────────────────────────┘
```

---

## 8. Command-Line Reference

| Command | Action | Key Options |
|---|---|---|
| `nanotrace ui` | Start the local interactive dashboard | `--port 7777`, `--host 127.0.0.1`, `--db <path>` |
| `nanotrace demo` | Run all 6 showcase agents + validator | `--ui` (auto-launch browser), `--port 7777` |
| `nanotrace stats` | Print aggregate metrics table | `--db <path>` |
| `nanotrace query` | Execute analytical SQL on spans | `--db <path>`, `<SQL string>` |
| `nanotrace export` | Export traces to compressed Parquet | `--output traces.parquet`, `--db <path>` |
| `nanotrace ingest` | Self-heal and ingest external JSON logs | `<file_path>`, `--db <path>` |
| `nanotrace eval` | Run zero-cost heuristic diagnostics | `--db <path>` |

---

## 9. Quick Verification Test

To verify your installation and generate a complete sample database of traces across all 6 agent patterns:

```bash
# 1. Run the showcase suite and automated validator
python showcase/run_all_and_validate.py

# 2. Launch the interactive dashboard
nanotrace ui --port 7777
```

Navigate to `http://127.0.0.1:7777` to inspect live waterfalls, switch between databases, and review token metrics.
