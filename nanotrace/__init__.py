"""NanoTrace: Ultra-low latency, zero-infra OpenTelemetry tracing & evaluation engine for AI agents and LLMs.

The DuckDB of AI Observability.
"""

from __future__ import annotations

from typing import Optional, Dict, Any, Callable, List
from contextlib import contextmanager

from nanotrace._version import __version__
from nanotrace.schema.otel import (
    GenAIAttributes,
    GenAIOperation,
    SpanKind,
    StatusCode,
)
from nanotrace.core.span import Span, SpanEvent
from nanotrace.core.tracer import NanoTracer
from nanotrace.core.healer import TraceHealer
from nanotrace.eval.bridge import load_traces, TraceDataset
from nanotrace.patchers import autoinstrument
from nanotrace.exceptions import NanoTraceError, CircuitBreakerTrip, ReplayError
from nanotrace.guardrails.breakers import (
    CircuitBreaker,
    MaxLoopBreaker,
    BudgetCapBreaker,
    MaxTokenBreaker,
    PIIRedaction,
    TimeoutBreaker,
)
from nanotrace.core.replay import ReplayEngine, ForkResult
from nanotrace.eval.golden import GoldenCase, GoldenDatasetManager
from nanotrace.eval.regression import RegressionEngine, RegressionRun, RegressionCaseResult
from nanotrace.prompts import PromptTemplate, PromptRegistry
from nanotrace.feedback import FeedbackEntry, FeedbackCollector
from nanotrace.media import detect_media, sanitize_payload_for_display, scan_trace_multimodal_artifacts
from nanotrace.rag import (
    RetrievedChunk,
    RAGQueryRecord,
    RAGRadarPoint,
    RAGRadarSummary,
    RAGRadarEngine,
)
from nanotrace.security import (
    AttackType,
    AdversarialAttack,
    AttackResult,
    SecurityScorecard,
    AdversarialGenerator,
    RedTeamRunner,
)
from nanotrace.fleet import (
    FleetNode,
    SyncResult,
    FleetOverview,
    FleetSyncEngine,
)
from nanotrace.topology import (
    TopologyNode,
    TopologyEdge,
    OptimizationRecommendation,
    TopologyAnalysis,
    TopologyOptimizer,
)
from nanotrace.exceptions import (
    NanoTraceError,
    CircuitBreakerTrip,
    ReplayError,
    PromptError,
    FeedbackError,
    RAGDriftError,
    SecurityError,
)

_DEFAULT_TRACER: Optional[NanoTracer] = None
_DEFAULT_PROMPT_REGISTRY: Optional[PromptRegistry] = None
_DEFAULT_FEEDBACK_COLLECTOR: Optional[FeedbackCollector] = None
_DEFAULT_RAG_RADAR_ENGINE: Optional[RAGRadarEngine] = None
_DEFAULT_REDTEAM_RUNNER: Optional[RedTeamRunner] = None



def init(
    storage_path: str = "./.traces/nanotrace.duckdb",
    buffer_capacity: int = 50_000,
    flush_interval: float = 0.25,
    auto_patch: bool = False,
    circuit_breakers: Optional[List[CircuitBreaker]] = None,
    db_path: Optional[str] = None,
) -> NanoTracer:
    """Initialize the global NanoTrace engine.

    Args:
        storage_path: Path to the local DuckDB database file (e.g. "./.traces/nanotrace.duckdb" or ":memory:")
        buffer_capacity: Max in-memory queue capacity before dropping spans
        flush_interval: Background worker flush interval in seconds
        auto_patch: If True, automatically instruments OpenAI and Anthropic SDKs if installed
        circuit_breakers: Optional active NanoShield guardrails applied to all traces
        db_path: Alias for storage_path
    """
    global _DEFAULT_TRACER
    target_path = db_path or storage_path
    if _DEFAULT_TRACER is not None:
        if getattr(_DEFAULT_TRACER.sink, "db_path", None) == target_path and getattr(_DEFAULT_TRACER.worker, "is_running", False):
            if auto_patch:
                autoinstrument(_DEFAULT_TRACER)
            if circuit_breakers:
                _DEFAULT_TRACER.circuit_breakers.extend(circuit_breakers)
            return _DEFAULT_TRACER
        _DEFAULT_TRACER.shutdown()

    _DEFAULT_TRACER = NanoTracer(
        db_path=target_path,
        buffer_capacity=buffer_capacity,
        flush_interval=flush_interval,
        circuit_breakers=circuit_breakers,
    )

    if auto_patch:
        autoinstrument(_DEFAULT_TRACER)

    return _DEFAULT_TRACER


def get_tracer() -> NanoTracer:
    """Get the active global NanoTracer instance (initializes default if not yet initialized)."""
    global _DEFAULT_TRACER
    if _DEFAULT_TRACER is None:
        _DEFAULT_TRACER = init()
    return _DEFAULT_TRACER


@contextmanager
def span(
    name: str,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    parent_span_id: Optional[str] = None,
    circuit_breakers: Optional[List[CircuitBreaker]] = None,
):
    """Context manager to trace a block of code within the active trace tree."""
    tracer = get_tracer()
    with tracer.span(
        name=name,
        kind=kind,
        attributes=attributes,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        circuit_breakers=circuit_breakers,
    ) as sp:
        yield sp


def trace_agent(
    name: Optional[str] = None,
    agent_type: Optional[str] = None,
    circuit_breakers: Optional[List[CircuitBreaker]] = None,
) -> Callable:
    """Decorator to trace an agent function or method (sync or async) with optional NanoShield breakers."""
    return get_tracer().trace_agent(name=name, agent_type=agent_type, circuit_breakers=circuit_breakers)


def trace_tool(
    name: Optional[str] = None,
    circuit_breakers: Optional[List[CircuitBreaker]] = None,
) -> Callable:
    """Decorator to trace tool execution (sync or async) with optional NanoShield breakers."""
    return get_tracer().trace_tool(name=name, circuit_breakers=circuit_breakers)


def flush() -> int:
    """Force flush all buffered spans to storage."""
    if _DEFAULT_TRACER is not None:
        return _DEFAULT_TRACER.flush()
    return 0


def shutdown() -> None:
    """Shutdown the tracer worker and cleanly close the database connection."""
    global _DEFAULT_TRACER
    if _DEFAULT_TRACER is not None:
        _DEFAULT_TRACER.shutdown()
        _DEFAULT_TRACER = None


def ingest(
    data: Any,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> list[Span]:
    """Universal Telemetry Ingestion: Ingest and heal chaotic or non-standard telemetry.

    Supports LangGraph trees, CrewAI logs, AutoGen conversation arrays, raw dictionaries,
    and stdout text. Automatically performs fuzzy key mapping, orphan tree grafting,
    token estimation, and soft error detection before writing to DuckDB.
    """
    tracer = get_tracer()
    healer = TraceHealer()
    spans = healer.parse_and_heal(data, default_trace_id=trace_id, default_session_id=session_id)
    if spans:
        tracer.sink.write_spans(spans)
    return spans


def get_prompt_registry(db_path: Optional[str] = None) -> PromptRegistry:
    """Retrieve or initialize the active PromptRegistry."""
    global _DEFAULT_PROMPT_REGISTRY
    target_path = db_path
    if not target_path:
        target_path = getattr(_DEFAULT_TRACER.sink, "db_path", "./.traces/nanotrace.duckdb") if _DEFAULT_TRACER else "./.traces/nanotrace.duckdb"
    if _DEFAULT_PROMPT_REGISTRY is None or _DEFAULT_PROMPT_REGISTRY.db_path != target_path:
        _DEFAULT_PROMPT_REGISTRY = PromptRegistry(db_path=target_path)
    return _DEFAULT_PROMPT_REGISTRY


def get_feedback_collector(db_path: Optional[str] = None) -> FeedbackCollector:
    """Retrieve or initialize the active FeedbackCollector."""
    global _DEFAULT_FEEDBACK_COLLECTOR
    target_path = db_path
    if not target_path:
        target_path = getattr(_DEFAULT_TRACER.sink, "db_path", "./.traces/nanotrace.duckdb") if _DEFAULT_TRACER else "./.traces/nanotrace.duckdb"
    if _DEFAULT_FEEDBACK_COLLECTOR is None or _DEFAULT_FEEDBACK_COLLECTOR.db_path != target_path:
        _DEFAULT_FEEDBACK_COLLECTOR = FeedbackCollector(db_path=target_path)
    return _DEFAULT_FEEDBACK_COLLECTOR


def get_rag_radar_engine(db_path: Optional[str] = None) -> RAGRadarEngine:
    """Retrieve or initialize the active RAGRadarEngine."""
    global _DEFAULT_RAG_RADAR_ENGINE
    target_path = db_path
    if not target_path:
        target_path = getattr(_DEFAULT_TRACER.sink, "db_path", "./.traces/nanotrace.duckdb") if _DEFAULT_TRACER else "./.traces/nanotrace.duckdb"
    if _DEFAULT_RAG_RADAR_ENGINE is None or _DEFAULT_RAG_RADAR_ENGINE.db_path != target_path:
        _DEFAULT_RAG_RADAR_ENGINE = RAGRadarEngine(db_path=target_path)
    return _DEFAULT_RAG_RADAR_ENGINE


def get_redteam_runner(db_path: Optional[str] = None) -> RedTeamRunner:
    """Retrieve or initialize the active RedTeamRunner."""
    global _DEFAULT_REDTEAM_RUNNER
    target_path = db_path
    if not target_path:
        target_path = getattr(_DEFAULT_TRACER.sink, "db_path", "./.traces/nanotrace.duckdb") if _DEFAULT_TRACER else "./.traces/nanotrace.duckdb"
    if _DEFAULT_REDTEAM_RUNNER is None or _DEFAULT_REDTEAM_RUNNER.db_path != target_path:
        _DEFAULT_REDTEAM_RUNNER = RedTeamRunner(db_path=target_path)
    return _DEFAULT_REDTEAM_RUNNER


_DEFAULT_FLEET_ENGINE: Optional[FleetSyncEngine] = None
_DEFAULT_TOPOLOGY_OPTIMIZER: Optional[TopologyOptimizer] = None


def get_fleet_engine(db_path: Optional[str] = None) -> FleetSyncEngine:
    """Retrieve or initialize the active FleetSyncEngine."""
    global _DEFAULT_FLEET_ENGINE
    target_path = db_path
    if not target_path:
        target_path = getattr(_DEFAULT_TRACER.sink, "db_path", "./.traces/nanotrace.duckdb") if _DEFAULT_TRACER else "./.traces/nanotrace.duckdb"
    if _DEFAULT_FLEET_ENGINE is None or _DEFAULT_FLEET_ENGINE.db_path != target_path:
        _DEFAULT_FLEET_ENGINE = FleetSyncEngine(db_path=target_path)
    return _DEFAULT_FLEET_ENGINE


def get_topology_optimizer(db_path: Optional[str] = None) -> TopologyOptimizer:
    """Retrieve or initialize the active TopologyOptimizer."""
    global _DEFAULT_TOPOLOGY_OPTIMIZER
    target_path = db_path
    if not target_path:
        target_path = getattr(_DEFAULT_TRACER.sink, "db_path", "./.traces/nanotrace.duckdb") if _DEFAULT_TRACER else "./.traces/nanotrace.duckdb"
    if _DEFAULT_TOPOLOGY_OPTIMIZER is None or _DEFAULT_TOPOLOGY_OPTIMIZER.db_path != target_path:
        _DEFAULT_TOPOLOGY_OPTIMIZER = TopologyOptimizer(db_path=target_path)
    return _DEFAULT_TOPOLOGY_OPTIMIZER



__all__ = [
    "__version__",
    "init",
    "get_tracer",
    "span",
    "trace_agent",
    "trace_tool",
    "flush",
    "shutdown",
    "ingest",
    "TraceHealer",
    "load_traces",
    "TraceDataset",
    "autoinstrument",
    "GenAIAttributes",
    "GenAIOperation",
    "SpanKind",
    "StatusCode",
    "Span",
    "SpanEvent",
    "CircuitBreaker",
    "MaxLoopBreaker",
    "BudgetCapBreaker",
    "MaxTokenBreaker",
    "PIIRedaction",
    "TimeoutBreaker",
    "CircuitBreakerTrip",
    "ReplayError",
    "PromptError",
    "FeedbackError",
    "RAGDriftError",
    "SecurityError",
    "NanoTraceError",
    "ReplayEngine",
    "ForkResult",
    "GoldenCase",
    "GoldenDatasetManager",
    "RegressionEngine",
    "RegressionRun",
    "RegressionCaseResult",
    "PromptTemplate",
    "PromptRegistry",
    "FeedbackEntry",
    "FeedbackCollector",
    "get_prompt_registry",
    "get_feedback_collector",
    "detect_media",
    "sanitize_payload_for_display",
    "scan_trace_multimodal_artifacts",
    "RetrievedChunk",
    "RAGQueryRecord",
    "RAGRadarPoint",
    "RAGRadarSummary",
    "RAGRadarEngine",
    "get_rag_radar_engine",
    "AttackType",
    "AdversarialAttack",
    "AttackResult",
    "SecurityScorecard",
    "AdversarialGenerator",
    "RedTeamRunner",
    "get_redteam_runner",
    "FleetNode",
    "SyncResult",
    "FleetOverview",
    "FleetSyncEngine",
    "get_fleet_engine",
    "TopologyNode",
    "TopologyEdge",
    "OptimizationRecommendation",
    "TopologyAnalysis",
    "TopologyOptimizer",
    "get_topology_optimizer",
]

