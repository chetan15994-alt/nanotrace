"""06_heal_haywire_telemetry.py

Demonstrates the NanoTrace Universal Trace Healer (UITH):
- Ingesting messy, non-standard payloads from LangGraph, AutoGen, CrewAI, and text logs
- Auto-reconciling fragmented tokens across OpenAI, Anthropic, Bedrock, and Gemini
- Healing broken orphan tree hierarchies
- Detecting soft/silent tool failures
"""

import nanotrace

# Initialize local trace engine
nanotrace.init(storage_path="./.traces/nanotrace.duckdb")

print("\n⚡️ [NanoTrace Universal Trace Healer Demonstration]\n")

# 1. Messy LangChain / LangGraph Run Tree
print("1. Ingesting chaotic LangGraph-like Run Tree...")
langgraph_payload = {
    "run_type": "chain",
    "name": "CustomerSupportGraph",
    "inputs": {"ticket": "My API key is returning 429 rate limit"},
    "outputs": {"resolution": "Upgraded tier quota and reset rate limiter."},
    "child_runs": [
        {
            "name": "ClassifierLLM",
            "run_type": "llm",
            "extra": {"metadata": {"model_name": "claude-3-5-sonnet"}},
            "usage": {"input_tokens": 145, "output_tokens": 30},
            "outputs": {"text": "Category: Billing & Quota Issue"},
        },
        {
            "name": "QuotaUpdateTool",
            "run_type": "tool",
            "tool": "update_user_quota",
            "inputs": {"user_id": 9821, "tier": "scale"},
            "outputs": "{\"status\": \"success\", \"new_limit\": 10000}",
        }
    ]
}

spans_lg = nanotrace.ingest(langgraph_payload)
print(f"   ✓ Healed & ingested {len(spans_lg)} spans (Root + Child LLM + Child Tool).")

# 2. AutoGen Multi-Turn Conversation History
print("\n2. Ingesting AutoGen Multi-Turn Conversation...")
autogen_payload = [
    {"role": "user", "content": "Can you check server health?"},
    {"role": "assistant", "model": "gpt-4o", "content": "Server load is 14%. Memory usage is normal."},
    {"role": "user", "content": "Great, thanks!"},
]

spans_ag = nanotrace.ingest(autogen_payload)
print(f"   ✓ Healed & ingested {len(spans_ag)} spans (Conversation root + individual turns).")

# 3. Soft Error Detection (Tool caught an exception without raising)
print("\n3. Ingesting Silent/Soft Tool Error...")
soft_error_payload = {
    "name": "DatabaseSearchAgent",
    "prompt": "Find transaction 8923",
    "tool_calls": [
        {
            "tool": "sql_query",
            "input": "SELECT * FROM trans WHERE id = 8923",
            "output": "Traceback (most recent call last):\n  OperationalError: Connection to database timed out after 5000ms"
        }
    ]
}

spans_err = nanotrace.ingest(soft_error_payload)
failed_tool = next(s for s in spans_err if "sql_query" in s.name)
print(f"   ✓ Soft error caught: {failed_tool.name} marked as status: {failed_tool.status.value} (Error Type: {failed_tool.attributes.get('error.type')})")

# 4. Query Healed Spans via DuckDB
print("\n4. Analytical DuckDB SQL on Healed Traces:")
dataset = nanotrace.load_traces(db_path="./.traces/nanotrace.duckdb", limit=10)
print(f"   ✓ Total spans available in dataset: {len(dataset)}")

# Convert healed traces to DeepEval test cases
test_cases = dataset.to_deepeval()
print(f"   ✓ Converted to {len(test_cases)} DeepEval LLMTestCase objects ready for evaluation.")

print("\nTip: Run 'nanotrace ui' to view all healed traces in the interactive waterfall!")
