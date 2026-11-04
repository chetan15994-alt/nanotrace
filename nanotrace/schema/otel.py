"""OpenTelemetry Semantic Conventions for Generative AI & Agents.

Adheres to CNCF OpenTelemetry GenAI semantic conventions (v1.27+).
Provides standardized attribute keys, operation names, and status codes.
"""

from enum import Enum
from typing import Dict, Any, Optional


class GenAIAttributes:
    """Standardized OpenTelemetry GenAI Attribute keys."""

    # Provider & System
    SYSTEM = "gen_ai.system"
    PROVIDER_NAME = "gen_ai.provider.name"

    # Operation
    OPERATION_NAME = "gen_ai.operation.name"

    # Model parameters
    REQUEST_MODEL = "gen_ai.request.model"
    RESPONSE_MODEL = "gen_ai.response.model"
    REQUEST_TEMPERATURE = "gen_ai.request.temperature"
    REQUEST_TOP_P = "gen_ai.request.top_p"
    REQUEST_MAX_TOKENS = "gen_ai.request.max_tokens"
    REQUEST_PRESENCE_PENALTY = "gen_ai.request.presence_penalty"
    REQUEST_FREQUENCY_PENALTY = "gen_ai.request.frequency_penalty"

    # Token usage & Cost
    USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
    USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
    USAGE_TOTAL_TOKENS = "gen_ai.usage.total_tokens"
    USAGE_COST_USD = "gen_ai.usage.cost_usd"

    # Agent & Orchestration
    AGENT_NAME = "gen_ai.agent.name"
    AGENT_ID = "gen_ai.agent.id"
    AGENT_VERSION = "gen_ai.agent.version"
    AGENT_TYPE = "gen_ai.agent.type"
    CONVERSATION_ID = "gen_ai.conversation.id"
    SESSION_ID = "gen_ai.session.id"

    # Tool Execution
    TOOL_NAME = "gen_ai.tool.name"
    TOOL_CALL_ID = "gen_ai.tool.call_id"
    TOOL_ARGUMENTS = "gen_ai.tool.arguments"
    TOOL_OUTPUT = "gen_ai.tool.output"
    TOOL_STATUS = "gen_ai.tool.status"

    # Retrieval / RAG
    RETRIEVAL_DOCUMENTS = "gen_ai.retrieval.documents"
    RETRIEVAL_QUERY = "gen_ai.retrieval.query"
    RETRIEVAL_TOP_K = "gen_ai.retrieval.top_k"

    # Completion & Finish Reason
    RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
    RESPONSE_ID = "gen_ai.response.id"

    # Prompts & Content
    PROMPT = "gen_ai.prompt"
    COMPLETION = "gen_ai.completion"
    MESSAGES = "gen_ai.input.messages"

    # Error Attributes
    ERROR_TYPE = "error.type"
    ERROR_MESSAGE = "error.message"
    ERROR_STACKTRACE = "error.stacktrace"


class GenAIOperation(str, Enum):
    """Recognized GenAI operation names."""
    CHAT = "chat"
    TEXT_COMPLETION = "text_completion"
    EXECUTE_TOOL = "execute_tool"
    AGENT_RUN = "agent_run"
    RETRIEVAL = "retrieval"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    WORKFLOW = "workflow"


class SpanKind(str, Enum):
    """OpenTelemetry SpanKind."""
    INTERNAL = "INTERNAL"
    CLIENT = "CLIENT"
    SERVER = "SERVER"
    PRODUCER = "PRODUCER"
    CONSUMER = "CONSUMER"


class StatusCode(str, Enum):
    """OpenTelemetry Span StatusCode."""
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"
