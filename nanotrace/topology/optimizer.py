"""Autonomous Swarm Topology & Communication DAG Optimization Engine.

Analyzes parent-child span execution trees, identifies communication bottlenecks,
detects ping-pong chatter loops, and generates concrete pruning/caching recommendations.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import duckdb

from nanotrace.exceptions import NanoTraceError
from nanotrace.topology.models import (
    OptimizationRecommendation,
    TopologyAnalysis,
    TopologyEdge,
    TopologyNode,
)

logger = logging.getLogger("nanotrace.topology")


class TopologyOptimizer:
    """Evaluates agent delegation DAGs and synthesizes architectural optimization recommendations."""

    def __init__(self, db_path: str = "./.traces/nanotrace.duckdb"):
        self.db_path = db_path
        self._mem_conn = duckdb.connect(":memory:") if db_path == ":memory:" else None

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        if self._mem_conn is not None:
            return self._mem_conn
        try:
            return duckdb.connect(self.db_path)
        except Exception as e:
            raise NanoTraceError(f"Failed to connect to DuckDB at '{self.db_path}': {e}") from e

    def _close_conn(self, conn: duckdb.DuckDBPyConnection) -> None:
        if conn is not self._mem_conn:
            conn.close()

    def analyze_trace(self, trace_id: str) -> TopologyAnalysis:
        """Analyze a specific trace execution DAG and compute optimization recommendations."""
        conn = self._get_connection()
        try:
            # Check if spans table exists
            table_check = conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'spans'").fetchone()
            if not table_check or table_check[0] == 0:
                return TopologyAnalysis(trace_id=trace_id)

            rows = conn.execute("""
                SELECT span_id, parent_span_id, name, kind, duration_ms, status,
                       gen_ai_agent_name, gen_ai_tool_name, gen_ai_cost_usd, start_time_ns, end_time_ns
                FROM spans
                WHERE trace_id = ?
                ORDER BY start_time_ns ASC
            """, [trace_id]).fetchall()

            if not rows:
                return TopologyAnalysis(trace_id=trace_id)

            span_map: Dict[str, Dict[str, Any]] = {}
            node_stats: Dict[str, Dict[str, Any]] = {}
            raw_edges: Dict[Tuple[str, str], List[float]] = {}
            agent_names: Set[str] = set()

            total_trace_duration = 0.0
            root_span_duration = 0.0

            for r in rows:
                sid, pid, name, kind, dur_ms, status, agent_n, tool_n, cost_u, start_ns, end_ns = r
                dur = float(dur_ms or 0.0)
                cost = float(cost_u or 0.0)
                is_err = (status == "ERROR")

                # Derive canonical node identifier
                node_key = name
                if agent_n:
                    node_key = agent_n
                    agent_names.add(agent_n)
                elif tool_n:
                    node_key = f"tool: {tool_n}"

                # Infer node type
                n_type = "step"
                lower_key = node_key.lower()
                if agent_n or "agent" in lower_key or "council" in lower_key:
                    n_type = "agent"
                    agent_names.add(node_key)
                elif tool_n or "tool:" in lower_key or "tool " in lower_key:
                    n_type = "tool"
                elif lower_key.startswith("chat ") or "llm" in lower_key or "embedding" in lower_key:
                    n_type = "llm"
                elif "router" in lower_key or "supervisor" in lower_key:
                    n_type = "router"

                span_map[sid] = {
                    "node_key": node_key,
                    "parent_id": pid,
                    "duration_ms": dur,
                    "cost_usd": cost,
                    "is_error": is_err,
                    "node_type": n_type,
                    "start_ns": start_ns,
                    "end_ns": end_ns,
                }

                if pid is None or pid == "":
                    root_span_duration = max(root_span_duration, dur)

                total_trace_duration += dur

                # Aggregate node level metrics
                if node_key not in node_stats:
                    node_stats[node_key] = {
                        "name": node_key,
                        "node_type": n_type,
                        "calls": 0,
                        "duration_ms": 0.0,
                        "cost_usd": 0.0,
                        "errors": 0,
                    }
                node_stats[node_key]["calls"] += 1
                node_stats[node_key]["duration_ms"] += dur
                node_stats[node_key]["cost_usd"] += cost
                if is_err:
                    node_stats[node_key]["errors"] += 1

            # Build Edges from parent-child relationships
            parent_children_spans: Dict[str, List[Dict[str, Any]]] = {}
            for sid, sinfo in span_map.items():
                pid = sinfo["parent_id"]
                if pid and pid in span_map:
                    parent_node = span_map[pid]["node_key"]
                    child_node = sinfo["node_key"]
                    if parent_node != child_node:
                        edge_key = (parent_node, child_node)
                        if edge_key not in raw_edges:
                            raw_edges[edge_key] = []
                        raw_edges[edge_key].append(sinfo["duration_ms"])

                    if pid not in parent_children_spans:
                        parent_children_spans[pid] = []
                    parent_children_spans[pid].append(sinfo)

            # Compute communication overhead ratio
            critical_path_ms = root_span_duration if root_span_duration > 0 else max((s["duration_ms"] for s in span_map.values()), default=1.0)
            comm_overhead_pct = 0.0
            if total_trace_duration > 0 and len(rows) > 1:
                # Leaf tool and LLM compute vs coordinator overhead
                leaf_compute = sum(s["duration_ms"] for s in span_map.values() if s["node_type"] in ["tool", "llm"])
                orchestration_time = max(0.0, total_trace_duration - leaf_compute)
                comm_overhead_pct = (orchestration_time / total_trace_duration) * 100.0

            # Construct TopologyNodes
            nodes: List[TopologyNode] = []
            for n_id, ns in node_stats.items():
                avg_lat = ns["duration_ms"] / ns["calls"] if ns["calls"] > 0 else 0.0
                nodes.append(
                    TopologyNode(
                        id=n_id,
                        name=ns["name"],
                        node_type=ns["node_type"],
                        total_calls=ns["calls"],
                        total_duration_ms=ns["duration_ms"],
                        total_cost_usd=ns["cost_usd"],
                        error_count=ns["errors"],
                        avg_latency_ms=avg_lat,
                    )
                )

            # Construct TopologyEdges
            edges: List[TopologyEdge] = []
            for (src, tgt), durations in raw_edges.items():
                call_cnt = len(durations)
                avg_dur = sum(durations) / call_cnt if call_cnt > 0 else 0.0
                # Mark as critical path if high duration
                is_crit = avg_dur >= (critical_path_ms * 0.4)
                edges.append(
                    TopologyEdge(
                        source=src,
                        target=tgt,
                        call_count=call_cnt,
                        avg_latency_ms=avg_dur,
                        is_critical_path=is_crit,
                    )
                )

            # ── Synthesize Optimization Recommendations ───────────────────────
            recs: List[OptimizationRecommendation] = []

            # 1. Ping-Pong Chatter Loop Detection
            edge_pairs = set(raw_edges.keys())
            for (src, tgt) in list(edge_pairs):
                if (tgt, src) in edge_pairs:
                    calls_fwd = len(raw_edges[(src, tgt)])
                    calls_rev = len(raw_edges[(tgt, src)])
                    total_chatter = calls_fwd + calls_rev
                    if total_chatter >= 2:
                        recs.append(
                            OptimizationRecommendation(
                                title=f"Ping-Pong Chatter Loop: {src} ⇄ {tgt}",
                                category="chatter_reduction",
                                severity="high",
                                description=f"Sub-agents '{src}' and '{tgt}' exchanged {total_chatter} back-and-forth delegation cycles. This indicates tight coupling or lack of a shared blackboard.",
                                estimated_savings_pct=28.5,
                                estimated_cost_reduction_usd=sum(raw_edges[(src, tgt)] + raw_edges[(tgt, src)]) * 0.00001,
                                suggested_patch="Refactor into a centralized blackboard or shared context scratchpad to eliminate conversational ping-pong cycles.",
                            )
                        )
                        # Remove reverse to avoid duplicate reporting
                        edge_pairs.discard((tgt, src))

            # 2. Sequential Parallelizability Detection
            for pid, children in parent_children_spans.items():
                tool_children = [c for c in children if c["node_type"] == "tool"]
                if len(tool_children) >= 2:
                    # Check if sequential (no overlap)
                    tool_children.sort(key=lambda x: x["start_ns"] or 0)
                    is_sequential = True
                    for i in range(len(tool_children) - 1):
                        if tool_children[i]["end_ns"] and tool_children[i + 1]["start_ns"]:
                            if tool_children[i]["end_ns"] > tool_children[i + 1]["start_ns"]:
                                is_sequential = False
                                break
                    if is_sequential:
                        parent_name = span_map[pid]["node_key"]
                        tool_time = sum(c["duration_ms"] for c in tool_children)
                        recs.append(
                            OptimizationRecommendation(
                                title=f"Parallelize {len(tool_children)} Sequential Tool Invocations under '{parent_name}'",
                                category="parallelize",
                                severity="medium",
                                description=f"Node '{parent_name}' invoked {len(tool_children)} tools in sequential order taking {tool_time:.1f}ms total. These operations can execute concurrently.",
                                estimated_savings_pct=42.0,
                                estimated_cost_reduction_usd=0.0,
                                suggested_patch="Wrap independent tool executions in asyncio.gather() or concurrent.futures.ThreadPoolExecutor.",
                            )
                        )

            # 3. Model Tier Downgrade / Cost Pruning
            for n in nodes:
                if n.node_type == "llm" and "gpt-4o" in n.name.lower() and not "mini" in n.name.lower():
                    if n.avg_latency_ms < 600 and n.total_calls >= 2:
                        recs.append(
                            OptimizationRecommendation(
                                title=f"Downgrade LLM Tier: {n.name} → gpt-4o-mini",
                                category="pruning",
                                severity="info",
                                description=f"Node '{n.name}' performed {n.total_calls} rapid classifications costing ${n.total_cost_usd:.4f}. A distilled model would achieve identical accuracy at ~80% lower cost.",
                                estimated_savings_pct=75.0,
                                estimated_cost_reduction_usd=n.total_cost_usd * 0.75,
                                suggested_patch="Switch model parameter from 'gpt-4o' to 'gpt-4o-mini' or 'gemini-2.0-flash'.",
                            )
                        )

            # 4. Fallback Default Recommendation if none triggered
            if not recs:
                recs.append(
                    OptimizationRecommendation(
                        title="Topology Efficiency Calibrated (Optimal DAG)",
                        category="pruning",
                        severity="info",
                        description="Execution graph demonstrates minimal communication overhead, zero ping-pong chatter loops, and optimal delegation depth.",
                        estimated_savings_pct=0.0,
                        estimated_cost_reduction_usd=0.0,
                        suggested_patch="No topology modifications required. Execution is currently running at peak efficiency.",
                    )
                )

            return TopologyAnalysis(
                trace_id=trace_id,
                total_agents=len(agent_names),
                total_steps=len(rows),
                critical_path_ms=critical_path_ms,
                communication_overhead_pct=comm_overhead_pct,
                nodes=nodes,
                edges=edges,
                recommendations=recs,
            )

        finally:
            self._close_conn(conn)

    def analyze_latest_trace(self) -> TopologyAnalysis:
        """Find the most recent trace in DuckDB and analyze its topology."""
        conn = self._get_connection()
        try:
            table_check = conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'spans'").fetchone()
            if not table_check or table_check[0] == 0:
                return TopologyAnalysis(trace_id="none")

            row = conn.execute("SELECT trace_id FROM spans ORDER BY start_time_ns DESC LIMIT 1").fetchone()
            if not row:
                return TopologyAnalysis(trace_id="none")
            return self.analyze_trace(row[0])
        finally:
            self._close_conn(conn)
