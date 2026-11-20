"""NanoTrace Client: High-throughput, non-blocking asynchronous cloud exporter.

Preserves the < 4 µs agent execution SLA by queueing spans in-memory and
flushing micro-batches to the remote NanoTrace Server via background daemon thread.
"""

from __future__ import annotations

import json
import os
import queue
import socket
import threading
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional


class RemoteSpanExporter:
    """Asynchronous, non-blocking span exporter for distributed agent fleets."""

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        api_key: Optional[str] = None,
        workspace_id: Optional[str] = None,
        project_id: Optional[str] = None,
        batch_size: int = 100,
        flush_interval_s: float = 1.0,
        max_queue_size: int = 10000,
    ):
        self.endpoint_url = (endpoint_url or os.environ.get("NANOTRACE_ENDPOINT") or "").rstrip("/")
        self.api_key = api_key or os.environ.get("NANOTRACE_API_KEY")
        self.workspace_id = workspace_id or os.environ.get("NANOTRACE_WORKSPACE_ID")
        self.project_id = project_id or os.environ.get("NANOTRACE_PROJECT_ID")
        self.batch_size = batch_size
        self.flush_interval_s = flush_interval_s

        self.queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self.hostname = socket.gethostname()
        self.node_id = f"node_{self.hostname}"
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self.spans_sent = 0
        self.spans_dropped = 0
        self.last_flush_status: Optional[str] = None

        if self.is_configured:
            self._start_worker()

    @property
    def is_configured(self) -> bool:
        """Returns True if remote endpoint and API key are configured."""
        return bool(self.endpoint_url and self.api_key)

    def _start_worker(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="nanotrace-remote-exporter",
        )
        self._worker_thread.start()

    def enqueue_span(self, span_or_dict: Any) -> bool:
        """Enqueues a span dictionary or Span object for background upload in < 1 µs."""
        if not self.is_configured:
            return False
        try:
            payload = self._span_to_payload_dict(span_or_dict)
            self.queue.put_nowait(payload)
            return True
        except queue.Full:
            self.spans_dropped += 1
            return False

    @staticmethod
    def _span_to_payload_dict(span_or_dict: Any) -> Dict[str, Any]:
        if isinstance(span_or_dict, dict):
            return span_or_dict
        attrs = getattr(span_or_dict, "attributes", {})
        from nanotrace.schema.otel import GenAIAttributes
        return {
            "span_id": str(span_or_dict.span_id),
            "trace_id": str(span_or_dict.trace_id),
            "parent_span_id": str(span_or_dict.parent_span_id) if span_or_dict.parent_span_id else None,
            "name": str(span_or_dict.name),
            "span_type": span_or_dict.kind.value if hasattr(span_or_dict.kind, "value") else str(span_or_dict.kind),
            "status": span_or_dict.status.value if hasattr(span_or_dict.status, "value") else str(span_or_dict.status),
            "start_time_ns": int(span_or_dict.start_time_ns),
            "end_time_ns": int(span_or_dict.end_time_ns or span_or_dict.start_time_ns),
            "duration_ms": float(span_or_dict.duration_ms),
            "model": str(attrs.get(GenAIAttributes.REQUEST_MODEL) or attrs.get(GenAIAttributes.RESPONSE_MODEL) or ""),
            "tokens_in": int(attrs.get(GenAIAttributes.USAGE_INPUT_TOKENS, 0) or attrs.get("gen_ai.usage.prompt_tokens", 0) or 0),
            "tokens_out": int(attrs.get(GenAIAttributes.USAGE_OUTPUT_TOKENS, 0) or attrs.get("gen_ai.usage.completion_tokens", 0) or 0),
            "cost_usd": float(attrs.get(GenAIAttributes.USAGE_COST_USD, 0.0) or 0.0),
            "input": str(attrs.get(GenAIAttributes.PROMPT) or attrs.get(GenAIAttributes.TOOL_ARGUMENTS) or attrs.get("input") or ""),
            "output": str(attrs.get(GenAIAttributes.COMPLETION) or attrs.get(GenAIAttributes.TOOL_OUTPUT) or attrs.get("output") or ""),
            "error_message": getattr(span_or_dict, "status_message", None),
            "attributes": attrs,
        }

    def _worker_loop(self) -> None:
        """Background daemon loop draining queue and flushing batches over HTTP."""
        batch = []
        last_flush_time = time.time()

        while not self._stop_event.is_set():
            timeout = max(0.1, self.flush_interval_s - (time.time() - last_flush_time))
            try:
                span_data = self.queue.get(timeout=timeout)
                batch.append(span_data)
                self.queue.task_done()
            except queue.Empty:
                pass

            now = time.time()
            if (len(batch) >= self.batch_size) or (batch and (now - last_flush_time) >= self.flush_interval_s):
                self._flush_batch(batch)
                batch = []
                last_flush_time = now

        # Drain any remaining items upon shutdown
        while not self.queue.empty():
            try:
                batch.append(self.queue.get_nowait())
                self.queue.task_done()
            except queue.Empty:
                break
        if batch:
            self._flush_batch(batch)

    def _flush_batch(self, batch: List[Dict[str, Any]]) -> bool:
        """Posts a span batch to /api/v1/ingest."""
        if not batch or not self.is_configured:
            return False

        url = f"{self.endpoint_url}/api/v1/ingest"
        payload = {
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "node_id": self.node_id,
            "hostname": self.hostname,
            "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "spans": batch,
        }

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "User-Agent": "NanoTrace-RemoteExporter/0.2.0",
        }

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                if 200 <= resp.status < 300:
                    self.spans_sent += len(batch)
                    self.last_flush_status = "success"
                    return True
                else:
                    self.spans_dropped += len(batch)
                    self.last_flush_status = f"http_{resp.status}"
                    return False
        except Exception as e:
            self.spans_dropped += len(batch)
            self.last_flush_status = f"error_{str(e)}"
            return False

    def shutdown(self, timeout: float = 3.0) -> None:
        """Signals worker to stop and flushes remaining queue."""
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)


def get_default_config_path() -> str:
    """Returns ~/.nanotrace/config.json."""
    config_dir = os.path.expanduser("~/.nanotrace")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "config.json")


def load_client_config() -> Dict[str, Any]:
    """Loads stored remote server configuration."""
    cfg_path = get_default_config_path()
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_client_config(config: Dict[str, Any]) -> None:
    """Saves remote server configuration."""
    cfg_path = get_default_config_path()
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
