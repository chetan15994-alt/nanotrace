import asyncio
import pytest
import nanotrace
from nanotrace.schema.otel import GenAIAttributes


def test_sync_agent_and_tool_decorators():
    tracer = nanotrace.init(storage_path=":memory:")

    @tracer.trace_tool(name="calculator")
    def add(a: int, b: int) -> int:
        return a + b

    @tracer.trace_agent(name="MathAgent")
    def solve(x: int, y: int) -> int:
        return add(x, y)

    res = solve(10, 20)
    assert res == 30

    tracer.flush()
    spans = tracer.sink.query("SELECT * FROM spans")
    assert len(spans) == 2

    agent_span = next(s for s in spans if s["gen_ai_agent_name"] == "MathAgent")
    tool_span = next(s for s in spans if s["gen_ai_tool_name"] == "calculator")

    assert agent_span["trace_id"] == tool_span["trace_id"]
    assert tool_span["parent_span_id"] == agent_span["span_id"]
    tracer.shutdown()


def test_async_agent_and_tool_decorators():
    async def _run_test():
        tracer = nanotrace.init(storage_path=":memory:")

        @tracer.trace_tool(name="async_fetch")
        async def fetch_data(key: str) -> str:
            await asyncio.sleep(0.01)
            return f"value_for_{key}"

        @tracer.trace_agent(name="AsyncAgent")
        async def run_async_agent(key: str) -> str:
            return await fetch_data(key)

        res = await run_async_agent("config")
        assert res == "value_for_config"

        tracer.flush()
        spans = tracer.sink.query("SELECT * FROM spans")
        assert len(spans) == 2
        tracer.shutdown()

    asyncio.run(_run_test())
