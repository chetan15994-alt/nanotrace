"""NanoTrace Universal Trace Healer (UITH).

A fault-tolerant, self-healing normalization engine that transforms chaotic,
non-standard, or broken telemetry from any agent framework (LangGraph, CrewAI,
AutoGen, custom while-loops, raw JSON dumps, stdout logs) into canonical
CNCF OpenTelemetry GenAI traces.
"""

from __future__ import annotations

import re
import json
import time
import uuid
from typing import Dict, Any, List, Optional, Tuple, Union

from nanotrace.core.span import Span, generate_trace_id, generate_span_id
from nanotrace.schema.otel import GenAIAttributes, GenAIOperation, SpanKind, StatusCode

# Known model provider pricing (USD per 1M tokens)
MODEL_RATES = {
    "gpt-4o": {"in": 2.50, "out": 10.00, "provider": "openai"},
    "gpt-4o-mini": {"in": 0.15, "out": 0.60, "provider": "openai"},
    "gpt-4": {"in": 30.00, "out": 60.00, "provider": "openai"},
    "gpt-3.5": {"in": 0.50, "out": 1.50, "provider": "openai"},
    "claude-3-5-sonnet": {"in": 3.00, "out": 15.00, "provider": "anthropic"},
    "claude-3-opus": {"in": 15.00, "out": 75.00, "provider": "anthropic"},
    "claude-3-haiku": {"in": 0.25, "out": 1.25, "provider": "anthropic"},
    "gemini-1.5-pro": {"in": 1.25, "out": 5.00, "provider": "google"},
    "gemini-1.5-flash": {"in": 0.075, "out": 0.30, "provider": "google"},
    "gemini-2.0-flash": {"in": 0.10, "out": 0.40, "provider": "google"},
    "llama": {"in": 0.20, "out": 0.20, "provider": "meta"},
    "mistral": {"in": 2.00, "out": 6.00, "provider": "mistral"},
}

# Patterns indicating soft errors inside caught tool returns
ERROR_PATTERNS = [
    re.compile(r"traceback \(most recent call last\):", re.IGNORECASE),
    re.compile(r"(^|\s)(error|exception|ratelimiterror|timeout|connectionerror):", re.IGNORECASE),
    re.compile(r"(404 not found|500 internal server error|502 bad gateway|429 too many requests)", re.IGNORECASE),
    re.compile(r"(\"status\":\s*\"error\"|\"success\":\s*false)", re.IGNORECASE),
]


class TraceHealer:
    """Universal Telemetry Normalizer and Trace Healer."""

    def __init__(self):
        pass

    def parse_and_heal(
        self,
        raw_data: Any,
        default_trace_id: Optional[str] = None,
        default_session_id: Optional[str] = None,
    ) -> List[Span]:
        """Convert any chaotic input structure into healed, canonical OpenTelemetry Spans."""
        if raw_data is None or raw_data == "" or raw_data == {} or raw_data == []:
            return []

        trace_id = default_trace_id or generate_trace_id()

        # Step 1: Parse string inputs (JSON, JSONL, or stdout logs)
        parsed_payload = self._to_parsed_structure(raw_data)

        # Step 2: Extract raw candidate span dictionaries based on detected shape
        raw_spans = self._extract_raw_spans(parsed_payload)

        if not raw_spans:
            # Fallback: create a single root span wrapping the payload
            raw_spans = [{
                "name": "agent_execution",
                "kind": "INTERNAL",
                "payload": parsed_payload,
            }]

        # Step 3: Normalize individual span attributes into CNCF GenAI conventions
        normalized_spans: List[Span] = []
        for raw in raw_spans:
            span = self._normalize_single_span(raw, trace_id, default_session_id)
            if span:
                normalized_spans.append(span)

        # Step 4: Reconcile tree hierarchy (temporal grafting for orphan spans)
        healed_spans = self.heal_tree_hierarchy(normalized_spans, trace_id)

        return healed_spans

    def _to_parsed_structure(self, data: Any) -> Any:
        """Coerce strings, bytes, and JSON into structured Python representations."""
        if isinstance(data, (dict, list)):
            return data

        if isinstance(data, (bytes, bytearray)):
            try:
                data = data.decode("utf-8")
            except Exception:
                data = str(data)

        if isinstance(data, str):
            trimmed = data.strip()
            # Try single JSON object
            if (trimmed.startswith("{") and trimmed.endswith("}")) or (trimmed.startswith("[") and trimmed.endswith("]")):
                try:
                    return json.loads(trimmed)
                except Exception:
                    pass

            # Try JSONL (JSON lines)
            lines = [line.strip() for line in trimmed.split("\n") if line.strip()]
            if len(lines) > 1 and lines[0].startswith("{"):
                jsonl_items = []
                for line in lines:
                    try:
                        jsonl_items.append(json.loads(line))
                    except Exception:
                        pass
                if jsonl_items:
                    return jsonl_items

            # Try parsing ReAct or stdout text patterns
            react_steps = self._parse_react_stdout(trimmed)
            if react_steps:
                return react_steps

            return {"content": trimmed}

        return {"raw": str(data)}

    def _parse_react_stdout(self, text: str) -> Optional[List[Dict[str, Any]]]:
        """Parse text stdout logs with ReAct patterns (Thought/Action/Observation) robustly."""
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            return None

        # Check if text contains typical agent keywords
        has_keywords = any(l.startswith(("Thought:", "Action:", "Observation:")) for l in lines)
        if not has_keywords:
            return None

        parsed_blocks = []
        curr_block: Dict[str, Any] = {}

        for line in lines:
            if line.startswith("Thought:"):
                if "thought" in curr_block or "action" in curr_block:
                    parsed_blocks.append(curr_block)
                    curr_block = {}
                curr_block["thought"] = line[8:].strip()
            elif line.startswith("Action:"):
                curr_block["action"] = line[7:].strip()
            elif line.startswith("Action Input:"):
                curr_block["input"] = line[13:].strip()
            elif line.startswith("Observation:"):
                curr_block["observation"] = line[12:].strip()
            else:
                # Append continuation lines
                if "observation" in curr_block:
                    curr_block["observation"] += f"\n{line}"
                elif "input" in curr_block:
                    curr_block["input"] += f"\n{line}"
                elif "thought" in curr_block:
                    curr_block["thought"] += f"\n{line}"

        if curr_block:
            parsed_blocks.append(curr_block)

        if not parsed_blocks:
            return None

        steps = []
        for idx, block in enumerate(parsed_blocks):
            action_name = (block.get("action") or "").strip()
            thought = (block.get("thought") or "").strip()
            obs = (block.get("observation") or "").strip()
            inp = (block.get("input") or "").strip()

            if action_name:
                steps.append({
                    "name": f"tool: {action_name}",
                    "kind": "CLIENT",
                    "operation": GenAIOperation.EXECUTE_TOOL.value,
                    "tool_name": action_name,
                    "input": inp or thought,
                    "output": obs,
                })
            elif thought or obs:
                steps.append({
                    "name": f"reasoning_step_{idx+1}",
                    "kind": "INTERNAL",
                    "operation": GenAIOperation.AGENT_RUN.value,
                    "input": thought,
                    "output": obs,
                })

        return steps if steps else None

    def _extract_raw_spans(self, payload: Any) -> List[Dict[str, Any]]:
        """Identify framework shape and extract raw span representations."""
        if isinstance(payload, list):
            # Check if AutoGen conversational message list
            if payload and all(isinstance(x, dict) and ("role" in x or "content" in x) for x in payload):
                return self._extract_autogen_spans(payload)
            return [x for x in payload if isinstance(x, dict)]

        if isinstance(payload, dict):
            # Check LangChain / LangGraph Run tree
            if "child_runs" in payload or "run_type" in payload:
                return self._flatten_langchain_tree(payload)

            # Check CrewAI task dump
            if "tasks_output" in payload or ("task" in payload and "agent" in payload):
                return self._extract_crewai_spans(payload)

            # Check if payload embeds child spans or tool calls
            if "tool_calls" in payload and isinstance(payload["tool_calls"], list):
                spans = [payload]
                for tc in payload["tool_calls"]:
                    if isinstance(tc, dict):
                        tc_span = dict(tc)
                        tc_span["_is_child_of_parent"] = True
                        spans.append(tc_span)
                return spans

            return [payload]

        return []

    def _extract_autogen_spans(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deconstruct AutoGen conversation history into sequential agent steps."""
        spans = []
        root_span = {
            "name": "AutoGen_Conversation",
            "kind": "INTERNAL",
            "operation": GenAIOperation.AGENT_RUN.value,
            "input": messages[0].get("content", "") if messages else "",
            "output": messages[-1].get("content", "") if messages else "",
            "is_root": True,
        }
        spans.append(root_span)

        for idx, msg in enumerate(messages):
            role = msg.get("role") or msg.get("sender") or "agent"
            content = msg.get("content", "")
            spans.append({
                "name": f"{role}_turn_{idx+1}",
                "kind": "CLIENT" if role in ["assistant", "model"] else "INTERNAL",
                "operation": GenAIOperation.CHAT.value if role in ["assistant", "model"] else GenAIOperation.AGENT_RUN.value,
                "input": content,
                "output": content,
                "model": msg.get("model", ""),
                "_is_child_of_parent": True,
            })
        return spans

    def _flatten_langchain_tree(self, run: Dict[str, Any], parent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Recursively flatten LangChain / LangGraph hierarchical Run trees."""
        results = []
        current = dict(run)
        current_id = str(current.get("id") or current.get("span_id") or generate_span_id())
        current["id"] = current_id

        if parent_id and not current.get("parent_run_id") and not current.get("parent_span_id"):
            current["parent_run_id"] = parent_id

        results.append(current)

        child_runs = current.get("child_runs") or current.get("children") or []
        for child in child_runs:
            if isinstance(child, dict):
                results.extend(self._flatten_langchain_tree(child, parent_id=current_id))

        return results

    def _extract_crewai_spans(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract steps from CrewAI task and agent executions."""
        spans = []
        crew_name = payload.get("crew") or payload.get("agent") or payload.get("name") or "CrewAI_Workflow"
        root = {
            "name": crew_name,
            "agent_name": payload.get("agent") or crew_name,
            "kind": "INTERNAL",
            "operation": GenAIOperation.AGENT_RUN.value,
            "input": payload.get("inputs") or payload.get("task", ""),
            "output": payload.get("output") or payload.get("result", ""),
            "usage": payload.get("usage"),
            "is_root": True,
        }
        spans.append(root)

        tasks = payload.get("tasks_output") or payload.get("tasks") or []
        for idx, task in enumerate(tasks):
            if isinstance(task, dict):
                agent_name = task.get("agent") or f"Agent_{idx+1}"
                spans.append({
                    "name": f"{agent_name}: {task.get('description', f'Task_{idx+1}')}",
                    "kind": "INTERNAL",
                    "operation": GenAIOperation.AGENT_RUN.value,
                    "input": task.get("description", ""),
                    "output": task.get("raw") or task.get("output", ""),
                    "_is_child_of_parent": True,
                })

        return spans

    def _normalize_single_span(
        self,
        raw: Dict[str, Any],
        trace_id: str,
        session_id: Optional[str] = None,
    ) -> Optional[Span]:
        """Transform a messy span dictionary into a standardized OpenTelemetry Span."""
        name = str(
            raw.get("name")
            or raw.get("run_name")
            or raw.get("step")
            or raw.get("tool")
            or raw.get("agent")
            or raw.get("operation")
            or "unnamed_step"
        )

        span_id = str(raw.get("span_id") or raw.get("id") or generate_span_id())
        parent_id = raw.get("parent_span_id") or raw.get("parent_run_id")
        if parent_id:
            parent_id = str(parent_id)

        # Resolve SpanKind
        raw_kind = str(raw.get("kind") or raw.get("span_kind") or "").upper()
        if "CLIENT" in raw_kind or "TOOL" in raw_kind or "LLM" in raw_kind or "CHAT" in raw_kind:
            kind = SpanKind.CLIENT
        else:
            kind = SpanKind.INTERNAL

        # Resolve Timing
        now_ns = time.time_ns()
        start_ns = self._extract_timestamp(raw, ["start_time_ns", "start_time", "created_at", "start"], fallback=now_ns)
        end_ns = self._extract_timestamp(raw, ["end_time_ns", "end_time", "completed_at", "end"], fallback=None)

        if end_ns is None:
            duration_s = float(raw.get("duration") or raw.get("latency_sec") or raw.get("duration_s") or 0.0)
            if duration_s > 0:
                end_ns = start_ns + int(duration_s * 1_000_000_000)
            else:
                end_ns = start_ns + 10_000_000  # Default 10ms

        # Extract tokens with multi-vendor fuzzy fallback
        in_tokens, out_tokens, total_tokens = self._extract_fuzzy_tokens(raw)

        # Extract model, provider & calculate USD cost
        model, provider, cost_usd = self._extract_model_and_cost(raw, in_tokens, out_tokens)

        # Extract prompt input & completion output
        input_payload, output_payload = self._extract_payloads(raw)

        # Estimate tokens if completely missing
        if total_tokens == 0:
            est_in = max(1, len(str(input_payload).split())) if input_payload else 0
            est_out = max(1, len(str(output_payload).split())) if output_payload else 0
            in_tokens, out_tokens, total_tokens = est_in, est_out, (est_in + est_out)
            if cost_usd == 0.0 and model != "unknown":
                cost_usd = self._compute_cost(model, in_tokens, out_tokens)

        # Detect soft errors
        is_error, err_type, err_msg = self._detect_soft_errors(raw, output_payload)

        # Build CNCF GenAI attributes
        attrs: Dict[str, Any] = {
            GenAIAttributes.SYSTEM: provider,
            GenAIAttributes.PROVIDER_NAME: provider,
            GenAIAttributes.REQUEST_MODEL: model,
            GenAIAttributes.USAGE_INPUT_TOKENS: in_tokens,
            GenAIAttributes.USAGE_OUTPUT_TOKENS: out_tokens,
            GenAIAttributes.USAGE_TOTAL_TOKENS: total_tokens,
            GenAIAttributes.USAGE_COST_USD: cost_usd,
            GenAIAttributes.PROMPT: input_payload,
            GenAIAttributes.COMPLETION: output_payload,
        }

        # Resolve Operation
        operation = raw.get("operation") or raw.get("gen_ai_operation") or raw.get("run_type")
        if not operation:
            if "tool" in name.lower() or raw.get("tool_name") or raw.get("tool"):
                operation = GenAIOperation.EXECUTE_TOOL.value
            elif "chat" in name.lower() or model != "unknown":
                operation = GenAIOperation.CHAT.value
            else:
                operation = GenAIOperation.AGENT_RUN.value

        attrs[GenAIAttributes.OPERATION_NAME] = operation

        tool_name = raw.get("tool_name") or raw.get("tool")
        if tool_name:
            attrs[GenAIAttributes.TOOL_NAME] = str(tool_name)
            attrs[GenAIAttributes.TOOL_ARGUMENTS] = input_payload
            attrs[GenAIAttributes.TOOL_OUTPUT] = output_payload

        agent_name = raw.get("agent_name") or raw.get("agent")
        if agent_name:
            attrs[GenAIAttributes.AGENT_NAME] = str(agent_name)

        if session_id:
            attrs[GenAIAttributes.SESSION_ID] = session_id
            attrs[GenAIAttributes.CONVERSATION_ID] = session_id

        # Preserve custom metadata
        for k, v in raw.items():
            if k not in ["name", "span_id", "id", "parent_span_id", "parent_run_id"] and not k.startswith("_"):
                if isinstance(v, (str, int, float, bool)):
                    attrs[k] = v

        # Instantiate standard Span
        span = Span(
            name=name,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_id,
            kind=kind,
            start_time_ns=start_ns,
            end_time_ns=end_ns,
            attributes=attrs,
        )

        if is_error:
            span.set_status(StatusCode.ERROR, err_msg)
            span.set_attribute(GenAIAttributes.ERROR_TYPE, err_type or "HeuristicDetectedError")
            span.set_attribute(GenAIAttributes.ERROR_MESSAGE, err_msg or "Soft failure detected in execution payload")
        else:
            span.set_status(StatusCode.OK)

        # Flag for temporal grafting
        if raw.get("_is_child_of_parent"):
            span._is_child_hint = True  # type: ignore

        return span

    def heal_tree_hierarchy(self, spans: List[Span], trace_id: str) -> List[Span]:
        """Graft orphan spans and guarantee a connected, valid tree hierarchy."""
        if not spans:
            return []

        # Sort chronologically
        spans.sort(key=lambda s: s.start_time_ns)

        # Identify root spans (no parent_span_id)
        roots = [s for s in spans if not s.parent_span_id]

        if not roots:
            # If all spans had random broken parent IDs, pick the earliest as root
            spans[0].parent_span_id = None
            roots = [spans[0]]

        primary_root = roots[0]

        # Temporal grafting: if an orphan span has no parent, find an enclosing active span
        for span in spans:
            if span is not primary_root and not span.parent_span_id:
                # Look for an enclosing parent whose lifecycle spans this child
                parent_candidate = None
                for candidate in spans:
                    if candidate is not span and candidate.start_time_ns <= span.start_time_ns:
                        cand_end = candidate.end_time_ns or (candidate.start_time_ns + 10_000_000_000)
                        if (span.end_time_ns or span.start_time_ns) <= cand_end:
                            parent_candidate = candidate
                            break

                # If found, graft onto candidate; otherwise, graft onto primary root
                if parent_candidate:
                    span.parent_span_id = parent_candidate.span_id
                else:
                    span.parent_span_id = primary_root.span_id

            # Ensure all spans share the same root trace_id
            span.trace_id = trace_id

        return spans

    def _extract_fuzzy_tokens(self, raw: Dict[str, Any]) -> Tuple[int, int, int]:
        """Fuzzy token extraction across OpenAI, Anthropic, Bedrock, Gemini, and LangChain."""
        in_keys = ["input_tokens", "prompt_tokens", "prompt_token_count", "inputTokenCount", "num_prompt_tokens"]
        out_keys = ["output_tokens", "completion_tokens", "candidates_token_count", "outputTokenCount", "num_completion_tokens"]
        total_keys = ["total_tokens", "total_token_count", "totalTokenCount"]

        containers = [raw]
        for c_key in ["usage", "usage_metadata", "metrics", "token_usage", "invocationMetrics", "llm_output"]:
            if c_key in raw and isinstance(raw[c_key], dict):
                containers.append(raw[c_key])
                if "usage" in raw[c_key] and isinstance(raw[c_key]["usage"], dict):
                    containers.append(raw[c_key]["usage"])

        in_tokens = 0
        out_tokens = 0
        total_tokens = 0

        for c in containers:
            if not in_tokens:
                for k in in_keys:
                    if k in c and isinstance(c[k], (int, float)):
                        in_tokens = int(c[k])
                        break
            if not out_tokens:
                for k in out_keys:
                    if k in c and isinstance(c[k], (int, float)):
                        out_tokens = int(c[k])
                        break
            if not total_tokens:
                for k in total_keys:
                    if k in c and isinstance(c[k], (int, float)):
                        total_tokens = int(c[k])
                        break

        if not total_tokens and (in_tokens or out_tokens):
            total_tokens = in_tokens + out_tokens

        return in_tokens, out_tokens, total_tokens

    def _extract_model_and_cost(self, raw: Dict[str, Any], in_tokens: int, out_tokens: int) -> Tuple[str, str, float]:
        """Fuzzy model and provider extraction, plus cost computation."""
        model_keys = ["model", "model_name", "request_model", "engine", "deployment", "model_id"]
        model = "unknown"

        containers = [raw]
        if "extra" in raw and isinstance(raw["extra"], dict):
            containers.append(raw["extra"].get("metadata", {}))
        if "llm_output" in raw and isinstance(raw["llm_output"], dict):
            containers.append(raw["llm_output"])
        if "invocation_params" in raw and isinstance(raw["invocation_params"], dict):
            containers.append(raw["invocation_params"])

        for c in containers:
            for k in model_keys:
                if k in c and isinstance(c[k], str) and c[k].strip():
                    model = c[k].strip()
                    break
            if model != "unknown":
                break

        provider = "custom"
        cost = 0.0

        model_lower = model.lower()
        for key, info in MODEL_RATES.items():
            if key in model_lower:
                provider = info["provider"]
                cost = round(((in_tokens / 1_000_000) * info["in"]) + ((out_tokens / 1_000_000) * info["out"]), 6)
                break

        if provider == "custom":
            if "gpt" in model_lower or "o1" in model_lower or "davinci" in model_lower:
                provider = "openai"
            elif "claude" in model_lower:
                provider = "anthropic"
            elif "gemini" in model_lower or "palm" in model_lower:
                provider = "google"
            elif "llama" in model_lower:
                provider = "meta"
            elif "mistral" in model_lower:
                provider = "mistral"
            elif "ollama" in model_lower:
                provider = "ollama"

        return model, provider, cost

    def _compute_cost(self, model: str, in_tokens: int, out_tokens: int) -> float:
        for key, info in MODEL_RATES.items():
            if key in model.lower():
                return round(((in_tokens / 1_000_000) * info["in"]) + ((out_tokens / 1_000_000) * info["out"]), 6)
        return 0.0

    def _extract_payloads(self, raw: Dict[str, Any]) -> Tuple[Any, Any]:
        """Extract prompt input and completion output across varying representations."""
        input_keys = ["input", "inputs", "prompt", "messages", "query", "question", "task", "action_input", "args"]
        output_keys = ["output", "outputs", "completion", "result", "response", "text", "generations", "observation"]

        inp = None
        out = None

        for k in input_keys:
            if k in raw and raw[k] is not None:
                inp = raw[k]
                break

        for k in output_keys:
            if k in raw and raw[k] is not None:
                out = raw[k]
                break

        # Unwrap LangChain generations
        if isinstance(out, dict) and "generations" in out:
            gens = out["generations"]
            if isinstance(gens, list) and gens and isinstance(gens[0], dict):
                out = gens[0].get("text") or gens[0]

        return inp or "", out or ""

    def _detect_soft_errors(self, raw: Dict[str, Any], output_payload: Any) -> Tuple[bool, Optional[str], Optional[str]]:
        """Scan tool outputs and attributes for silent/caught failures."""
        if raw.get("status") in ["ERROR", "error", "failed", "FAILURE"] or raw.get("error"):
            return True, "ExecutionError", str(raw.get("error") or "Step explicitly flagged as error")

        # Scan text output
        out_str = str(output_payload)
        if len(out_str) > 0:
            for pattern in ERROR_PATTERNS:
                if pattern.search(out_str):
                    return True, "ToolSoftFailure", f"Soft failure pattern detected: {out_str[:120]}..."

        return False, None, None

    def _extract_timestamp(self, raw: Dict[str, Any], keys: List[str], fallback: Optional[int]) -> int:
        """Extract nanosecond timestamp safely across second, millisecond, and nanosecond formats."""
        for k in keys:
            if k in raw and raw[k] is not None:
                val = raw[k]
                try:
                    num = float(val)
                    if num > 1e16:  # Already nanoseconds
                        return int(num)
                    elif num > 1e11:  # Milliseconds
                        return int(num * 1_000_000)
                    elif num > 1e8:  # Seconds
                        return int(num * 1_000_000_000)
                except Exception:
                    pass
        return fallback or time.time_ns()
