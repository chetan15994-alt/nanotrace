"""03_trace_to_deepeval.py

Demonstrates how NanoTrace bridges recorded agent traces into DeepEval test cases
with zero platform charges.
"""

import nanotrace
from nanotrace.eval.bridge import load_traces

# 1. Initialize tracer
tracer = nanotrace.init(storage_path="./.traces/nanotrace.duckdb")


@nanotrace.trace_tool(name="kb_search")
def kb_search(q: str):
    return "NanoTrace uses DuckDB for microsecond local trace storage."


@nanotrace.trace_agent(name="CustomerSupportAgent")
def support_agent(user_question: str):
    doc = kb_search(user_question)
    with nanotrace.span("llm_answer", attributes={"gen_ai.request.model": "gpt-4o"}) as sp:
        sp.set_attribute("gen_ai.prompt", user_question)
        answer = f"According to our knowledge base: {doc}"
        sp.set_attribute("gen_ai.completion", answer)
        sp.set_attribute("gen_ai.usage.total_tokens", 140)
        return answer


if __name__ == "__main__":
    print("\n1. Simulating agent conversations...")
    support_agent("How does NanoTrace achieve low latency?")
    support_agent("What database does NanoTrace use?")
    nanotrace.flush()

    print("\n2. Loading traces into TraceDataset...")
    dataset = load_traces(db_path="./.traces/nanotrace.duckdb", limit=5)
    print(f"Loaded {len(dataset)} trace records from DuckDB.")

    print("\n3. Converting to DeepEval LLMTestCase objects...")
    test_cases = dataset.to_deepeval()
    for idx, tc in enumerate(test_cases, 1):
        print(f"\n[DeepEval TestCase #{idx}]")
        print(f"  • Input:          {tc.input}")
        print(f"  • Actual Output:  {tc.actual_output}")
        print(f"  • Tools Called:   {tc.tools_called}")

    print("\n4. Running local zero-cost heuristic evaluators...")
    heuristics = dataset.run_heuristics()
    for h in heuristics:
        print(f"  • {h.metric_name}: {h.score * 100:.1f}% [{'PASS' if h.passed else 'FAIL'}]")

    print("\n✓ Ready to run 'deepeval test run ...' with 0 SaaS fees!")
