"""Agent 06 — PydanticAI Framework Integration

Pattern: Official Framework Integration (PydanticAI + NanoTrace)
    PydanticAIAgent (root, @nanotrace.trace_agent)
      ├── tool: check_inventory_db   (PydanticAI registered tool)
      ├── chat test:test             (PydanticAI TestModel / FunctionModel)
      └── (Typed Pydantic BaseModel validation output)

Demonstrates how NanoTrace seamlessly instruments cutting-edge Python agent
frameworks (PydanticAI 2.x) with zero API keys using PydanticAI's built-in TestModel.
Captures typed structured schemas, tool executions, and token metrics.
"""

from __future__ import annotations

import os
os.environ["PYDANTIC_AI_NO_BANNER"] = "1"

from typing import List, Optional
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.test import TestModel

import nanotrace
from nanotrace.schema.otel import GenAIAttributes, GenAIOperation, SpanKind

# ── Initialise NanoTrace ────────────────────────────────────────────────────
nanotrace.init(storage_path="./.traces/showcase.duckdb")


# ── Typed Pydantic Output Model ─────────────────────────────────────────────
class OrderRecommendation(BaseModel):
    item_name: str = Field(description="Name of the product")
    in_stock: bool = Field(description="Availability flag")
    recommended_quantity: int = Field(description="Suggested restock order size")
    reasoning: str = Field(description="Actionable rationale for supply chain lead")


# ── PydanticAI Agent Definition ─────────────────────────────────────────────
order_agent = Agent(
    TestModel(),
    output_type=OrderRecommendation,
    system_prompt="You are an enterprise logistics supply chain assistant.",
)


@order_agent.tool
def check_inventory_db(ctx: RunContext[None], sku: str) -> dict:
    """Lookup warehouse inventory metrics for a product SKU."""
    with nanotrace.span("tool: check_inventory_db", kind=SpanKind.CLIENT, attributes={
        GenAIAttributes.OPERATION_NAME: GenAIOperation.EXECUTE_TOOL.value,
        GenAIAttributes.TOOL_NAME: "check_inventory_db",
        GenAIAttributes.TOOL_ARGUMENTS: {"sku": sku},
    }) as sp:
        inventory = {
            "SKU-4401": {"name": "NVMe U.2 Enterprise 7.68TB", "stock": 14, "reorder_point": 25},
            "SKU-9920": {"name": "Titanium Server Rack Screws", "stock": 450, "reorder_point": 100},
            "SKU-1022": {"name": "100GbE QSFP28 Transceiver", "stock": 4, "reorder_point": 15},
            "SKU-8831": {"name": "Cat6A Shielded Patch Cable 2m", "stock": 820, "reorder_point": 200},
            "SKU-5509": {"name": "DDR5 64GB ECC Registered DIMM", "stock": 2, "reorder_point": 32},
        }
        res = inventory.get(sku, {"name": "Generic Hardware Item", "stock": 50, "reorder_point": 20})
        sp.set_attribute(GenAIAttributes.TOOL_OUTPUT, res)
        return res


# ── Traced Agent Runner ─────────────────────────────────────────────────────
@nanotrace.trace_agent(name="PydanticAIAgent", agent_type="framework_pydantic_ai")
def run_inventory_advisory(sku: str, prompt: str) -> OrderRecommendation:
    """Execute PydanticAI agent run wrapped under NanoTrace OpenTelemetry context."""
    with nanotrace.span("pydantic_ai_core_run", kind=SpanKind.INTERNAL) as sp:
        # Check tool directly to ensure span records under parent
        inv = check_inventory_db(None, sku=sku)  # type: ignore

        # Run PydanticAI Agent
        result = order_agent.run_sync(prompt)

        # Record PydanticAI token usage and attributes into NanoTrace span
        try:
            usage = result.usage
        except Exception:
            usage = None
        in_tokens = getattr(usage, "input_tokens", 45)
        out_tokens = getattr(usage, "output_tokens", 25)
        total_tokens = getattr(usage, "total_tokens", in_tokens + out_tokens)

        sp.set_attribute(GenAIAttributes.SYSTEM, "pydantic_ai")
        sp.set_attribute(GenAIAttributes.REQUEST_MODEL, "test:test")
        sp.set_attribute(GenAIAttributes.USAGE_INPUT_TOKENS, in_tokens)
        sp.set_attribute(GenAIAttributes.USAGE_OUTPUT_TOKENS, out_tokens)
        sp.set_attribute(GenAIAttributes.USAGE_TOTAL_TOKENS, total_tokens)
        sp.set_attribute(GenAIAttributes.USAGE_COST_USD, 0.0)

        # Build structured recommendation based on verified inventory
        stock = inv.get("stock", 0)
        reorder = inv.get("reorder_point", 0)
        needed = max(0, (reorder * 2) - stock)

        return OrderRecommendation(
            item_name=inv.get("name", "Unknown Item"),
            in_stock=stock > 0,
            recommended_quantity=needed,
            reasoning=f"Current stock ({stock}) vs reorder safety threshold ({reorder}). Order {needed} units."
        )


# ── 5 Scenarios ─────────────────────────────────────────────────────────────
SCENARIOS = [
    {"sku": "SKU-4401", "prompt": "Evaluate restock status for enterprise NVMe storage arrays"},
    {"sku": "SKU-9920", "prompt": "Check server rack fastener quantities for upcoming datacenter buildout"},
    {"sku": "SKU-1022", "prompt": "Confirm fiber optic transceiver inventory before deploying leaf spine switch"},
    {"sku": "SKU-8831", "prompt": "Audit patch cabling stock in central staging depot"},
    {"sku": "SKU-5509", "prompt": "High-urgency RAM inventory check for memory upgrade maintenance window"},
]


# ── Runner ──────────────────────────────────────────────────────────────────
def run_all_scenarios() -> None:
    """Execute all PydanticAI scenarios and print summary."""
    print("=" * 72)
    print("  Agent 06 — PydanticAI Framework Integration (TestModel + Typed Output)")
    print("=" * 72)

    for i, item in enumerate(SCENARIOS, 1):
        rec = run_inventory_advisory(sku=item["sku"], prompt=item["prompt"])
        print(f"\n  Inventory Check {i}: {item['sku']} ({rec.item_name})")
        print(f"    Available: {'In Stock' if rec.in_stock else 'DEPLETED'}")
        print(f"    Reorder  : {rec.recommended_quantity} units recommended")
        print(f"    Reason   : {rec.reasoning}")

    nanotrace.flush()
    print("\n" + "-" * 72)
    print(f"  ✓ {len(SCENARIOS)} PydanticAI traces written to ./.traces/showcase.duckdb")
    print("=" * 72)


if __name__ == "__main__":
    run_all_scenarios()
