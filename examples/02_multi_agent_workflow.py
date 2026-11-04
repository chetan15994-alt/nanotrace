"""02_multi_agent_workflow.py

Demonstrates hierarchical multi-agent tracing with sub-agents, tools,
and distributed trace context propagation.
"""

import time
import nanotrace

nanotrace.init(storage_path="./.traces/nanotrace.duckdb")


@nanotrace.trace_tool(name="vector_search")
def vector_search(query: str):
    time.sleep(0.015)
    return ["Doc A: Agent architectures", "Doc B: OpenTelemetry tracing"]


@nanotrace.trace_agent(name="WorkerAgent_Retrieval")
def retrieval_subagent(topic: str):
    return vector_search(topic)


@nanotrace.trace_agent(name="WorkerAgent_Synthesizer")
def synthesis_subagent(docs: list):
    with nanotrace.span("llm_synthesis", attributes={"gen_ai.request.model": "claude-3-5-sonnet"}) as sp:
        time.sleep(0.03)
        sp.set_attribute("gen_ai.system", "anthropic")
        sp.set_attribute("gen_ai.usage.input_tokens", 320)
        sp.set_attribute("gen_ai.usage.output_tokens", 110)
        sp.set_attribute("gen_ai.usage.total_tokens", 430)
        sp.set_attribute("gen_ai.usage.cost_usd", 0.00261)
        return "Synthesized multi-agent report from documents."


@nanotrace.trace_agent(name="CoordinatorAgent")
def run_coordinator(user_goal: str):
    docs = retrieval_subagent(user_goal)
    report = synthesis_subagent(docs)
    return report


if __name__ == "__main__":
    print("\n⚡️ Running Multi-Agent Coordinator...")
    final_output = run_coordinator("Design robust AI governance")
    print(f"Output: {final_output}\n")

    nanotrace.flush()
    print("✓ Successfully recorded multi-agent trace tree to DuckDB.")
    print("Run 'nanotrace ui' to view the parent-child waterfall.")
