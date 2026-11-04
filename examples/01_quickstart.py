"""01_quickstart.py

Basic demonstration of NanoTrace:
- Initialize local DuckDB trace engine
- Decorate tools and agent functions
- Inspect generated OpenTelemetry spans and metrics
"""

import time
import nanotrace

# 1. Initialize NanoTrace (creates ./.traces/nanotrace.duckdb)
tracer = nanotrace.init(storage_path="./.traces/nanotrace.duckdb")


# 2. Define tools with @nanotrace.trace_tool
@nanotrace.trace_tool(name="web_search")
def search_docs(query: str):
    time.sleep(0.02)  # Simulate API latency
    return {
        "query": query,
        "results": [
            "OpenTelemetry GenAI defines standardized telemetry for LLM applications.",
            "NanoTrace stores traces in embedded DuckDB for zero-latency observability."
        ]
    }


# 3. Define agent with @nanotrace.trace_agent
@nanotrace.trace_agent(name="ResearchAgent", agent_type="researcher")
def run_research(topic: str):
    # Step 1: Call tool
    docs = search_docs(topic)

    # Step 2: Trace LLM reasoning block
    with nanotrace.span("llm_generation", attributes={"gen_ai.request.model": "gpt-4o-mini"}) as sp:
        time.sleep(0.04)  # Simulate LLM generation
        sp.set_attribute("gen_ai.system", "openai")
        sp.set_attribute("gen_ai.usage.input_tokens", 185)
        sp.set_attribute("gen_ai.usage.output_tokens", 64)
        sp.set_attribute("gen_ai.usage.total_tokens", 249)
        sp.set_attribute("gen_ai.usage.cost_usd", 0.000066)
        response = f"Summary of {topic}: Found {len(docs['results'])} relevant documents."
        sp.set_attribute("gen_ai.completion", response)

    return response


if __name__ == "__main__":
    print("\n⚡️ Running ResearchAgent...")
    answer = run_research("AI Observability & Tracing")
    print(f"Result: {answer}\n")

    # Flush to ensure background daemon writes to DuckDB
    nanotrace.flush()

    # Display stats
    stats = tracer.stats()
    print("⚡️ [NanoTrace Stats]:")
    for k, v in stats.items():
        print(f"  • {k}: {v}")
    
    print("\nTip: Run 'nanotrace ui' to visualize this trace in your browser!")
