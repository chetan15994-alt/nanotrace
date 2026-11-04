import os
import json
import tempfile
import pytest
import nanotrace
from nanotrace.core.healer import TraceHealer
from nanotrace.schema.otel import StatusCode, GenAIAttributes, SpanKind


def test_langchain_tree_flattening():
    healer = TraceHealer()
    langchain_payload = {
        "id": "run-root-123",
        "name": "ChatAgentExecutor",
        "run_type": "chain",
        "inputs": {"input": "Calculate 25 * 4"},
        "outputs": {"output": "100"},
        "child_runs": [
            {
                "id": "run-child-456",
                "name": "ChatOpenAI",
                "run_type": "llm",
                "extra": {"metadata": {"model_name": "gpt-4o"}},
                "inputs": {"messages": [{"role": "user", "content": "Calculate 25 * 4"}]},
                "outputs": {"generations": [{"text": "Action: calculator(25, 4)"}]},
                "usage_metadata": {"input_tokens": 85, "output_tokens": 20},
            },
            {
                "id": "run-child-789",
                "name": "calculator_tool",
                "run_type": "tool",
                "tool": "calculator",
                "inputs": {"expression": "25 * 4"},
                "outputs": "100",
            }
        ]
    }

    spans = healer.parse_and_heal(langchain_payload)
    assert len(spans) == 3

    root = spans[0]
    assert root.parent_span_id is None
    assert root.name == "ChatAgentExecutor"

    llm_span = spans[1]
    assert llm_span.parent_span_id == root.span_id
    assert llm_span.attributes[GenAIAttributes.REQUEST_MODEL] == "gpt-4o"
    assert llm_span.attributes[GenAIAttributes.USAGE_INPUT_TOKENS] == 85
    assert llm_span.attributes[GenAIAttributes.USAGE_OUTPUT_TOKENS] == 20

    tool_span = spans[2]
    assert tool_span.parent_span_id == root.span_id
    assert tool_span.attributes[GenAIAttributes.TOOL_NAME] == "calculator"


def test_crewai_task_dump():
    healer = TraceHealer()
    crew_payload = {
        "crew": "ResearchCrew",
        "inputs": "Analyze AI observability",
        "output": "Final research report ready.",
        "tasks_output": [
            {
                "agent": "DataCollector",
                "description": "Fetch articles on OpenTelemetry",
                "raw": "Found 12 articles",
            },
            {
                "agent": "Writer",
                "description": "Synthesize summary",
                "raw": "Summary complete",
            }
        ]
    }

    spans = healer.parse_and_heal(crew_payload)
    assert len(spans) == 3
    assert spans[0].name == "ResearchCrew"
    assert spans[1].parent_span_id == spans[0].span_id
    assert spans[2].parent_span_id == spans[0].span_id


def test_autogen_messages_list():
    healer = TraceHealer()
    autogen_payload = [
        {"role": "user", "content": "How do you trace agents?"},
        {"role": "assistant", "model": "gpt-4o-mini", "content": "Use NanoTrace for local-first tracing."},
        {"role": "user", "content": "Does it support DuckDB?"},
        {"role": "assistant", "model": "gpt-4o-mini", "content": "Yes, DuckDB is built-in."},
    ]

    spans = healer.parse_and_heal(autogen_payload)
    # 1 root conversation span + 4 turn spans
    assert len(spans) == 5
    assert spans[0].name == "AutoGen_Conversation"
    assert spans[0].parent_span_id is None
    for s in spans[1:]:
        assert s.parent_span_id == spans[0].span_id


def test_fuzzy_token_and_model_extraction():
    healer = TraceHealer()

    # Bedrock style payload
    bedrock = {
        "name": "bedrock_step",
        "model_id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "invocationMetrics": {
            "inputTokenCount": 350,
            "outputTokenCount": 120,
        },
        "response": "Generated answer",
    }
    s_bedrock = healer.parse_and_heal(bedrock)[0]
    assert s_bedrock.attributes[GenAIAttributes.USAGE_INPUT_TOKENS] == 350
    assert s_bedrock.attributes[GenAIAttributes.USAGE_OUTPUT_TOKENS] == 120
    assert s_bedrock.attributes[GenAIAttributes.SYSTEM] == "anthropic"

    # Gemini style payload
    gemini = {
        "name": "gemini_step",
        "model": "gemini-1.5-flash",
        "usage_metadata": {
            "prompt_token_count": 210,
            "candidates_token_count": 65,
        },
        "text": "Gemini response",
    }
    s_gemini = healer.parse_and_heal(gemini)[0]
    assert s_gemini.attributes[GenAIAttributes.USAGE_INPUT_TOKENS] == 210
    assert s_gemini.attributes[GenAIAttributes.USAGE_OUTPUT_TOKENS] == 65
    assert s_gemini.attributes[GenAIAttributes.SYSTEM] == "google"


def test_temporal_orphan_span_grafting():
    healer = TraceHealer()
    now = 1_700_000_000_000_000_000

    # Two spans where the child tool was emitted in a thread with parent_span_id = None
    root_dict = {
        "name": "ParentAgent",
        "span_id": "root_111",
        "start_time_ns": now,
        "end_time_ns": now + 100_000_000,  # 100ms
        "parent_span_id": None,
    }
    orphan_tool = {
        "name": "OrphanToolCall",
        "span_id": "child_222",
        "start_time_ns": now + 20_000_000,
        "end_time_ns": now + 50_000_000,
        "parent_span_id": None,  # Broken!
    }

    spans = healer.parse_and_heal([root_dict, orphan_tool])
    assert len(spans) == 2
    root = next(s for s in spans if s.span_id == "root_111")
    child = next(s for s in spans if s.span_id == "child_222")

    assert root.parent_span_id is None
    # Automatically healed & grafted onto enclosing parent!
    assert child.parent_span_id == root.span_id


def test_soft_error_detection():
    healer = TraceHealer()
    
    # Tool output containing an uncaught python traceback
    tool_traceback = {
        "name": "tool_database",
        "tool": "sql_query",
        "output": "Traceback (most recent call last):\n  File 'db.py', line 12\nOperationalError: Connection refused",
    }
    s1 = healer.parse_and_heal(tool_traceback)[0]
    assert s1.status == StatusCode.ERROR
    assert s1.attributes[GenAIAttributes.ERROR_TYPE] == "ToolSoftFailure"

    # Tool output containing HTTP 404
    tool_404 = {
        "name": "fetch_api",
        "output": "{\"status\": 404, \"message\": \"404 Not Found: Resource does not exist\"}",
    }
    s2 = healer.parse_and_heal(tool_404)[0]
    assert s2.status == StatusCode.ERROR


def test_nanotrace_ingest_e2e():
    tracer = nanotrace.init(storage_path=":memory:")

    haywire_dump = {
        "run_type": "chain",
        "name": "CustomMessyAgent",
        "inputs": {"question": "How to scale AI systems?"},
        "outputs": {"answer": "Use asynchronous batching and local caching."},
        "child_runs": [
            {
                "tool": "web_search",
                "inputs": {"q": "AI scaling"},
                "outputs": "Found 3 results",
            }
        ]
    }

    # Ingest directly
    healed_spans = nanotrace.ingest(haywire_dump)
    assert len(healed_spans) == 2

    tracer.flush()
    records = tracer.sink.query("SELECT * FROM spans")
    assert len(records) == 2

    # Verify DeepEval test case conversion works on healed traces
    dataset = nanotrace.load_traces(sql_filter="name = 'CustomMessyAgent'")
    # We can also test dataset from memory
    test_cases = nanotrace.eval.trace_records_to_deepeval(records)
    assert len(test_cases) == 1
    assert "How to scale AI systems?" in test_cases[0].input
    assert "asynchronous batching" in test_cases[0].actual_output

    tracer.shutdown()
