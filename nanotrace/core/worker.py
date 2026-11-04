"""Asynchronous background worker for flushing buffered spans to storage sinks.

Runs in a daemon thread, decoupling span recording from storage I/O.
Includes atexit handlers to guarantee zero span loss on application shutdown.
"""

from __future__ import annotations

import time
import atexit
import logging
import threading
from typing import Optional

from nanotrace.core.buffer import SpanBuffer
from nanotrace.storage.base import StorageSink

logger = logging.getLogger("nanotrace")


class FlushWorker:
    """Background daemon thread that periodically flushes buffered spans to sinks."""

    def __init__(
        self,
        buffer: SpanBuffer,
        sink: StorageSink,
        flush_interval_seconds: float = 0.25,
        batch_size: int = 500,
    ):
        self.buffer = buffer
        self.sink = sink
        self.flush_interval = flush_interval_seconds
        self.batch_size = batch_size

        self._shutdown_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._started = False

    @property
    def is_running(self) -> bool:
        """Return True if background worker is actively running."""
        return self._started and not self._shutdown_event.is_set()

    def start(self) -> None:
        """Start the background worker daemon."""
        with self._lock:
            if self._started:
                return
            self._started = True
            self._shutdown_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="nanotrace-flush-worker",
                daemon=True,
            )
            self._thread.start()
            atexit.register(self.shutdown)

    def _run_loop(self) -> None:
        """Periodic background loop."""
        while not self._shutdown_event.is_set():
            try:
                self.flush_once()
            except Exception as e:
                logger.warning(f"[NanoTrace] Error in background flush worker: {e}")
            self._shutdown_event.wait(timeout=self.flush_interval)

    def flush_once(self) -> int:
        """Flush one batch of queued spans to sink."""
        spans = self.buffer.drain(max_items=self.batch_size)
        if spans:
            return self.sink.write_spans(spans)
        return 0

    def flush(self) -> int:
        """Flush all pending spans in buffer."""
        total = 0
        while len(self.buffer) > 0:
            count = self.flush_once()
            total += count
            if count == 0:
                break
        self.sink.flush()
        return total

    def shutdown(self, timeout: float = 2.0) -> None:
        """Flush all remaining spans and stop worker."""
        with self._lock:
            if not self._started:
                return
            self._shutdown_event.set()

        # Flush any remaining spans
        self.flush()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

        self.sink.close()
        self._started = False
