"""Agent 02 — Research Assistant

Pattern: ReAct Tool-Calling Loop (Reason-Act-Observe)
    ResearchAssistant (root, @trace_agent)
      ├── chat claude-3-5-sonnet  (plan: decide what to search)
      ├── tool: web_search         (search knowledge base)
      ├── tool: read_document      (read specific documentation)
      ├── chat claude-3-5-sonnet  (reason: evaluate findings & determine next step)
      ├── tool: web_search / read_document (optional secondary retrieval)
      └── chat claude-3-5-sonnet  (synthesize: generate authoritative answer)

Demonstrates variable-depth span trees, iterative reasoning cycles,
and multi-turn tool calling using Claude 3.5 Sonnet.
"""

from __future__ import annotations

import nanotrace
from showcase._simulator import mock_llm_call, mock_tool_call

# ── Initialise NanoTrace ────────────────────────────────────────────────────
nanotrace.init(storage_path="./.traces/showcase.duckdb")

PLANNER_SYSTEM_PROMPT = (
    "You are an expert research planner. Given a research query, outline which "
    "knowledge sources to query and what specific technical concepts to look up."
)

REASONING_SYSTEM_PROMPT = (
    "You are an analytical research agent. Review the search results and document "
    "passages gathered so far. Decide whether sufficient evidence exists to answer "
    "the query, or formulate a follow-up search query."
)

SYNTHESIS_SYSTEM_PROMPT = (
    "You are an authoritative technical writer. Synthesize all retrieved findings "
    "into a rigorous, clear, and comprehensive answer with architectural trade-offs."
)


@nanotrace.trace_agent(name="ResearchAssistant", agent_type="react_loop")
def run_research_react(scenario: dict) -> dict:
    """Execute a multi-step ReAct reasoning and tool-calling workflow."""
    query = scenario["query"]
    iterations = scenario["iterations"]

    # Step 1: Initial Planning LLM Call
    plan = mock_llm_call(
        model="claude-3-5-sonnet",
        system_prompt=PLANNER_SYSTEM_PROMPT,
        user_message=f"Formulate research strategy for: {query}",
        response=scenario["plan_text"],
        span_name="chat claude-3-5-sonnet (Plan)",
        temperature=0.2,
    )

    gathered_evidence = []

    # Step 2: Iterative ReAct Loop (1 to N cycles)
    for idx, step in enumerate(iterations, 1):
        # Action: Web Search tool
        search_res = mock_tool_call(
            tool_name="web_search",
            arguments={"query": step["search_query"], "limit": 3},
            result=step["search_results"],
            latency_ms=18.0,
        )

        # Action: Read Document tool
        doc_res = mock_tool_call(
            tool_name="read_document",
            arguments={"doc_id": step["doc_id"]},
            result=step["doc_content"],
            latency_ms=22.0,
        )
        gathered_evidence.append(doc_res)

        # Reason: Intermediate reasoning step
        mock_llm_call(
            model="claude-3-5-sonnet",
            system_prompt=REASONING_SYSTEM_PROMPT,
            user_message=f"Evaluate step {idx} findings for: {query}\nDoc: {doc_res[:200]}...",
            response=step["thought"],
            span_name=f"chat claude-3-5-sonnet (Reason Step {idx})",
            temperature=0.3,
        )

    # Step 3: Final Synthesis LLM Call
    synthesis = mock_llm_call(
        model="claude-3-5-sonnet",
        system_prompt=SYNTHESIS_SYSTEM_PROMPT,
        user_message=f"Query: {query}\nEvidence: {len(gathered_evidence)} documents analyzed.",
        response=scenario["final_synthesis"],
        span_name="chat claude-3-5-sonnet (Synthesize)",
        temperature=0.5,
    )

    return {
        "query": query,
        "tool_steps": len(iterations) * 2,
        "synthesis": synthesis,
    }


# ── 5 Realistic Research Scenarios ──────────────────────────────────────────
SCENARIOS = [
    {
        "query": "What are the main architectural differences between REST and GraphQL?",
        "plan_text": "Search API design paradigms, compare network over-fetching, caching layers, and schema strictness.",
        "iterations": [
            {
                "search_query": "REST vs GraphQL architectural comparison",
                "search_results": [
                    {"title": "REST API Guidelines", "snippet": "Resource-oriented with standard HTTP methods and URL paths."},
                    {"title": "GraphQL Specification", "snippet": "Single endpoint, declarative data fetching with graph schemas."}
                ],
                "doc_id": "api_paradigms.md",
                "doc_content": "REST uses distinct URLs for entities and leverages HTTP status codes and standard browser/CDN caching. However, client views often require multiple round-trips (under-fetching) or receive unused fields (over-fetching). GraphQL uses a single POST endpoint with typed queries, solving over-fetching but shifting caching complexity to client-side normalized caches like Apollo or Relay.",
                "thought": "Evidence clearly highlights caching vs payload flexibility trade-offs. Ready for comprehensive synthesis."
            }
        ],
        "final_synthesis": (
            "Architecturally, REST models systems as addressable HTTP resources with built-in caching (RFC 7234) "
            "and idempotent operations, making it optimal for public web APIs and CDN-heavy read workloads. "
            "In contrast, GraphQL decouples data requirements from endpoint structure via a strongly-typed schema, "
            "eliminating round-trips and over-fetching, but introduces query-complexity vulnerabilities and requires "
            "application-level cache invalidation mechanisms."
        )
    },
    {
        "query": "Explain how transformer attention mechanisms work and why scaled dot-product is necessary.",
        "plan_text": "Break down Q/K/V projections, matrix multiplication, softmax stability, and dimension scaling factor sqrt(d_k).",
        "iterations": [
            {
                "search_query": "Attention Is All You Need Vaswani QKV",
                "search_results": [
                    {"title": "Attention Paper Summary", "snippet": "Computes compatibility between Query and Key vectors to weight Value vectors."}
                ],
                "doc_id": "transformer_foundations.md",
                "doc_content": "Inputs are linearly projected into Query (Q), Key (K), and Value (V) matrices. The dot product Q·K^T measures raw pairwise token alignment scores. For large projection dimensions d_k, dot products grow large in magnitude, pushing softmax into regions of vanishingly small gradients.",
                "thought": "Need deeper detail on why scaling by 1/sqrt(d_k) restores gradient variance."
            },
            {
                "search_query": "Scaled dot product softmax gradient vanishing sqrt dk",
                "search_results": [
                    {"title": "Numerical Stability in Self-Attention", "snippet": "Under independent variance assumptions, dot product variance equals d_k."}
                ],
                "doc_id": "variance_scaling_proof.md",
                "doc_content": "If components of Q and K have mean 0 and variance 1, their dot product has mean 0 and variance d_k. Dividing by sqrt(d_k) rescales variance to 1, preventing the softmax function from saturating into near-one-hot probability distributions where gradients vanish during backpropagation.",
                "thought": "Mechanistic mathematical justification established. Ready to synthesize."
            }
        ],
        "final_synthesis": (
            "The Transformer self-attention mechanism maps a set of Query, Key, and Value vectors via "
            "Attention(Q,K,V) = softmax(Q K^T / sqrt(d_k)) V. The scaling factor 1/sqrt(d_k) is critical: "
            "as projection dimension d_k increases, the dot products grow large in magnitude, causing softmax "
            "to saturate with negligible gradients. Dividing by sqrt(d_k) preserves unit variance and ensures "
            "stable gradient flow during training."
        )
    },
    {
        "query": "What is the CAP theorem and how does it apply to modern distributed databases?",
        "plan_text": "Explore Brewer's conjecture, PACELC theorem extension, and partition tolerance reality in cloud networks.",
        "iterations": [
            {
                "search_query": "CAP theorem Brewer PACELC cloud networks",
                "search_results": [
                    {"title": "Distributed Consistency Trade-offs", "snippet": "Network partitions are unavoidable, forcing a choice between C and A."}
                ],
                "doc_id": "cap_theorem_analysis.md",
                "doc_content": "Brewer's CAP theorem proves that in an asynchronous network subject to partitions (P), a distributed data store can guarantee either Consistency (linearizability) or Availability (every non-failing node returns a response), but not both. Modern systems like Spanner choose CP with TrueTime hardware clocks, while Dynamo-style stores choose AP with eventual consistency.",
                "thought": "Clear consensus. Partition tolerance is non-negotiable in distributed real-world networks; systems choose CP or AP."
            }
        ],
        "final_synthesis": (
            "The CAP theorem dictates that when a distributed system experiences network partitions (P)—which are "
            "inevitable in physical networks—it must trade off between strict consistency (CP, e.g., Google Spanner, CockroachDB) "
            "and uninterrupted availability (AP, e.g., Cassandra, DynamoDB). The PACELC theorem further extends this by showing "
            "that even in the absence of partitions, a system must continuously trade off between Latency (L) and Consistency (C)."
        )
    },
    {
        "query": "Compare Docker containers and Kubernetes orchestration — when to use each?",
        "plan_text": "Investigate container virtualization layer vs cluster scheduler, lifecycle management, and operational overhead.",
        "iterations": [
            {
                "search_query": "Docker container runtime vs Kubernetes scheduler",
                "search_results": [
                    {"title": "Container vs Orchestrator", "snippet": "Docker packages apps; Kubernetes manages fleets of hosts."}
                ],
                "doc_id": "container_abstractions.md",
                "doc_content": "Docker packages applications with dependencies into reproducible OCI images running inside isolated Linux namespaces and cgroups. Kubernetes (K8s) is an orchestration control plane that schedules, scales, auto-heals, and networks thousands of container pods across multiple computing nodes.",
                "thought": "Need to clarify operational boundaries: single-node Docker Compose vs multi-node K8s."
            },
            {
                "search_query": "When to avoid Kubernetes operational complexity",
                "search_results": [
                    {"title": "Kubernetes Complexity Tax", "snippet": "K8s introduces high cognitive overhead for small engineering teams."}
                ],
                "doc_id": "k8s_decision_framework.md",
                "doc_content": "Teams with fewer than 10 microservices and predictable workloads often suffer from Kubernetes overhead. Simpler alternatives like Docker Compose, AWS ECS, or Cloud Run provide 80% of container benefits with a fraction of maintenance costs.",
                "thought": "Decision boundary clearly defined. Ready for final synthesis."
            }
        ],
        "final_synthesis": (
            "Docker is a containerization technology that packages application code and dependencies into portable images. "
            "Kubernetes is an orchestration platform that manages clusters of containerized applications—handling service discovery, "
            "rolling deployments, autoscaling, and self-healing. Organizations should start with Docker Compose or serverless "
            "containers (Cloud Run/ECS) and graduate to Kubernetes only when multi-node fleet scheduling and automated traffic topologies are required."
        )
    },
    {
        "query": "What are production best practices for API rate limiting algorithms?",
        "plan_text": "Review Token Bucket, Leaky Bucket, Sliding Window Counter, and Redis cluster synchronization.",
        "iterations": [
            {
                "search_query": "Token bucket vs Sliding window log rate limiting",
                "search_results": [
                    {"title": "Rate Limiting in Distributed Systems", "snippet": "Sliding window counter balances memory efficiency with boundary burst protection."}
                ],
                "doc_id": "rate_limiting_algorithms.md",
                "doc_content": "Fixed window algorithms suffer from boundary burst vulnerabilities (2x traffic at window edges). Token bucket handles bursty traffic well by refilling tokens at a constant rate. Sliding window counter combines fixed window memory economy with sliding log smoothing, making it the industry standard for Stripe and Cloudflare.",
                "thought": "Need details on HTTP response conventions: 429 status, Retry-After header, and RateLimit headers."
            },
            {
                "search_query": "IETF RateLimit HTTP headers standard 429",
                "search_results": [
                    {"title": "IETF Draft RateLimit Headers", "snippet": "RateLimit-Limit, RateLimit-Remaining, RateLimit-Reset."}
                ],
                "doc_id": "ietf_ratelimit_spec.md",
                "doc_content": "RFC 6585 specifies HTTP 429 Too Many Requests. Production systems should return standard IETF headers: RateLimit-Limit, RateLimit-Remaining, and RateLimit-Reset (epoch seconds), alongside Retry-After for clients to back off exponentially.",
                "thought": "Comprehensive architectural guidance complete."
            }
        ],
        "final_synthesis": (
            "Production rate limiting should employ the Sliding Window Counter algorithm backed by Redis Lua scripts "
            "to prevent edge-bursting while maintaining low memory footprint. Applications should strictly adhere to "
            "RFC 6585 by returning HTTP 429 with standard headers (RateLimit-Limit, RateLimit-Remaining, RateLimit-Reset, "
            "and Retry-After), allowing clients to implement intelligent jittered exponential backoff."
        )
    }
]


# ── Runner ──────────────────────────────────────────────────────────────────
def run_all_scenarios() -> None:
    """Execute all research scenarios and print a summary."""
    print("=" * 72)
    print("  Agent 02 — Research Assistant (ReAct Loop with Variable Depth)")
    print("=" * 72)

    for i, item in enumerate(SCENARIOS, 1):
        result = run_research_react(item)
        preview = result["synthesis"][:100].replace("\n", " ") + "…"
        print(f"\n  Research Query {i}")
        print(f"    Topic     : {item['query'][:65]}…")
        print(f"    Tool Calls: {result['tool_steps']} operations executed")
        print(f"    Synthesis : {preview}")

    nanotrace.flush()
    print("\n" + "-" * 72)
    print(f"  ✓ {len(SCENARIOS)} research traces written to ./.traces/showcase.duckdb")
    print("=" * 72)


if __name__ == "__main__":
    run_all_scenarios()
