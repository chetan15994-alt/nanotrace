"""Agent 03 — Code Review Agent

Pattern: RAG (Retrieval-Augmented Generation)
    CodeReviewAgent (root, @trace_agent)
      ├── embedding text-embedding-3-small  (embed source snippet)
      ├── retrieval vector_search            (retrieve known vulnerability patterns)
      ├── chat gpt-4o                        (analyze AST patterns against CWE vectors)
      └── chat gpt-4o                        (generate structured remediation report)

Demonstrates OpenTelemetry GenAI RAG conventions (`gen_ai.retrieval.*`,
`gen_ai.operation.name=retrieval`, `embedding`), multi-stage analysis,
and structured security audits using OpenAI GPT-4o.
"""

from __future__ import annotations

import nanotrace
from showcase._simulator import (
    mock_llm_call,
    mock_embedding,
    mock_retrieval,
)

# ── Initialise NanoTrace ────────────────────────────────────────────────────
nanotrace.init(storage_path="./.traces/showcase.duckdb")

ANALYSIS_SYSTEM_PROMPT = (
    "You are a principal security engineer. Analyze the provided source code "
    "against retrieved vulnerability descriptions and identify any security flaws, "
    "concurrency bugs, or memory safety issues."
)

REPORT_SYSTEM_PROMPT = (
    "You are an automated code quality auditor. Produce an executive remediation report "
    "specifying severity (CRITICAL/HIGH/MEDIUM/LOW/PASS), CWE identifier, root cause, "
    "and concrete code patch."
)


@nanotrace.trace_agent(name="CodeReviewAgent", agent_type="rag_auditor")
def review_code_snippet(scenario: dict) -> dict:
    """Perform an embedding-backed RAG code review workflow."""
    snippet = scenario["code"]
    title = scenario["title"]

    # Step 1: Embed source code snippet
    mock_embedding(
        model="text-embedding-3-small",
        text=snippet,
        dimensions=1536,
        latency_ms=12.0,
    )

    # Step 2: Retrieve relevant vulnerability knowledge base entries
    retrieved_patterns = mock_retrieval(
        query=f"vulnerabilities matching: {title}",
        results=scenario["retrieved_cwe"],
        top_k=2,
        latency_ms=20.0,
    )

    # Step 3: Deep analysis of AST against patterns
    analysis = mock_llm_call(
        model="gpt-4o",
        system_prompt=ANALYSIS_SYSTEM_PROMPT,
        user_message=(
            f"Code:\n```python\n{snippet}\n```\n\n"
            f"Retrieved Patterns:\n{retrieved_patterns}"
        ),
        response=scenario["analysis_response"],
        span_name="chat gpt-4o (Security Analysis)",
        temperature=0.1,
    )

    # Step 4: Final structured audit report
    report = mock_llm_call(
        model="gpt-4o",
        system_prompt=REPORT_SYSTEM_PROMPT,
        user_message=f"Generate remediation report for findings:\n{analysis}",
        response=scenario["report_response"],
        span_name="chat gpt-4o (Remediation Report)",
        temperature=0.2,
    )

    return {
        "title": title,
        "severity": scenario["severity"],
        "report": report,
    }


# ── 5 Realistic Code Review Scenarios ───────────────────────────────────────
SNIPPETS = [
    {
        "title": "SQL Injection in User Lookup",
        "severity": "CRITICAL",
        "code": (
            "def get_user_profile(username: str):\n"
            "    query = f\"SELECT id, email, role FROM users WHERE username = '{username}'\"\n"
            "    return db.execute(query).fetchone()\n"
        ),
        "retrieved_cwe": [
            {
                "id": "CWE-89",
                "title": "Improper Neutralization of Special Elements used in an SQL Command",
                "score": 0.94,
                "remedy": "Use parameterized queries or prepared statements; never interpolate unsanitized strings.",
            },
            {
                "id": "CWE-20",
                "title": "Improper Input Validation",
                "score": 0.81,
                "remedy": "Sanitize and validate input against strict character whitelists.",
            }
        ],
        "analysis_response": (
            "CRITICAL VULNERABILITY DETECTED: The parameter `username` is directly interpolated "
            "into the SQL query string using Python f-strings. An attacker can supply payload: "
            "' OR '1'='1' -- to bypass authentication or extract entire database tables via UNION-based injection."
        ),
        "report_response": (
            "Severity: CRITICAL | CWE-89 (SQL Injection)\n"
            "Root Cause: String formatting into dynamic SQL query statement.\n"
            "Remediation:\n"
            "```python\n"
            "def get_user_profile(username: str):\n"
            "    query = 'SELECT id, email, role FROM users WHERE username = :username'\n"
            "    return db.execute(query, {'username': username}).fetchone()\n"
            "```"
        )
    },
    {
        "title": "Unchecked Null Reference in Order Shipping",
        "severity": "HIGH",
        "code": (
            "def dispatch_order(order: dict):\n"
            "    customer = order.get('customer')\n"
            "    shipping = customer['address']\n"
            "    send_carrier_notification(shipping['postal_code'], order['id'])\n"
        ),
        "retrieved_cwe": [
            {
                "id": "CWE-476",
                "title": "NULL Pointer Dereference / NoneType Attribute Access",
                "score": 0.89,
                "remedy": "Guard against missing keys and None values before nested access.",
            }
        ],
        "analysis_response": (
            "HIGH SEVERITY FLAW: If `order.get('customer')` returns None (for guest checkouts or corrupted payloads), "
            "`customer['address']` raises an unhandled TypeError: 'NoneType' object is not subscriptable, causing worker crashes."
        ),
        "report_response": (
            "Severity: HIGH | CWE-476 (Unchecked NoneType Dereference)\n"
            "Root Cause: Direct dictionary indexing on potentially None object.\n"
            "Remediation:\n"
            "```python\n"
            "def dispatch_order(order: dict):\n"
            "    customer = order.get('customer') or {}\n"
            "    shipping = customer.get('address')\n"
            "    if not shipping:\n"
            "        raise ValueError(f'Order {order.get(\"id\")} lacks valid shipping address')\n"
            "    send_carrier_notification(shipping.get('postal_code'), order['id'])\n"
            "```"
        )
    },
    {
        "title": "Non-Atomic Balance Check-Then-Act Race Condition",
        "severity": "HIGH",
        "code": (
            "def withdraw_funds(account_id: str, amount: float):\n"
            "    balance = db.get_balance(account_id)\n"
            "    if balance >= amount:\n"
            "        db.update_balance(account_id, balance - amount)\n"
            "        return True\n"
            "    return False\n"
        ),
        "retrieved_cwe": [
            {
                "id": "CWE-362",
                "title": "Concurrent Execution using Shared Resource with Improper Synchronization (Race Condition)",
                "score": 0.92,
                "remedy": "Use database row-level locking (SELECT FOR UPDATE) or optimistic version locking.",
            }
        ],
        "analysis_response": (
            "HIGH SEVERITY CONCURRENCY BUG: Classic Time-of-Check to Time-of-Use (TOCTOU) race condition. "
            "Two concurrent withdrawal requests can both read the same initial balance before either updates it, "
            "allowing a malicious user to double-spend and overdraft funds beyond zero."
        ),
        "report_response": (
            "Severity: HIGH | CWE-362 (Race Condition / TOCTOU)\n"
            "Root Cause: Balance check and update operations are separated and un-locked.\n"
            "Remediation: Wrap within a transactional block using atomic SQL decrement: "
            "`UPDATE accounts SET balance = balance - :amt WHERE id = :id AND balance >= :amt`"
        )
    },
    {
        "title": "Unclosed File Descriptor Resource Leak",
        "severity": "MEDIUM",
        "code": (
            "def load_system_config(path: str) -> dict:\n"
            "    f = open(path, 'r', encoding='utf-8')\n"
            "    config = json.load(f)\n"
            "    return config\n"
        ),
        "retrieved_cwe": [
            {
                "id": "CWE-775",
                "title": "Missing Release of File Descriptor or Handle After Effective Lifetime",
                "score": 0.86,
                "remedy": "Utilize structured context managers (with statements) to guarantee descriptor cleanup.",
            }
        ],
        "analysis_response": (
            "MEDIUM RISK: File handle `f` is never explicitly closed. If `json.load()` encounters a syntax error, "
            "an exception is raised and the descriptor remains leaked until garbage collection, risking process FD exhaustion."
        ),
        "report_response": (
            "Severity: MEDIUM | CWE-775 (Resource Leak)\n"
            "Root Cause: Missing context manager protocol.\n"
            "Remediation:\n"
            "```python\n"
            "def load_system_config(path: str) -> dict:\n"
            "    with open(path, 'r', encoding='utf-8') as f:\n"
            "        return json.load(f)\n"
            "```"
        )
    },
    {
        "title": "Clean Typed Discount Calculation",
        "severity": "PASS",
        "code": (
            "def calculate_cart_subtotal(items: list[dict], discount_ratio: float = 0.0) -> float:\n"
            "    \"\"\"Calculate total price of active cart items with applied discount.\"\"\"\n"
            "    if not 0.0 <= discount_ratio <= 1.0:\n"
            "        raise ValueError('Discount ratio must fall between 0.0 and 1.0')\n"
            "    subtotal = sum(i['price'] * i['quantity'] for i in items if i.get('active', True))\n"
            "    return round(subtotal * (1.0 - discount_ratio), 2)\n"
        ),
        "retrieved_cwe": [
            {
                "id": "BEST-PRACTICE",
                "title": "Clean Architecture & Explicit Input Validation",
                "score": 0.95,
                "remedy": "Maintain type hints, range boundaries, and deterministic rounding.",
            }
        ],
        "analysis_response": (
            "PASS: The code adheres to secure coding standards. Proper parameter boundary validation "
            "prevents invalid discount ratios, type hints are explicit, and safe dict `.get()` handling is observed."
        ),
        "report_response": (
            "Severity: PASS | Clean Code Quality\n"
            "Auditor Assessment: Zero security vulnerabilities or resource leaks detected.\n"
            "Recommendation: Approved for production merge."
        )
    }
]


# ── Runner ──────────────────────────────────────────────────────────────────
def run_all_scenarios() -> None:
    """Execute all code review scenarios and print a summary."""
    print("=" * 72)
    print("  Agent 03 — Code Review Agent (RAG: Embeddings + Retrieval + Audit)")
    print("=" * 72)

    for i, item in enumerate(SNIPPETS, 1):
        result = review_code_snippet(item)
        preview = result["report"].split("\n")[0]
        print(f"\n  Code Audit {i}: {result['title']}")
        print(f"    Severity : {result['severity']}")
        print(f"    Finding  : {preview}")

    nanotrace.flush()
    print("\n" + "-" * 72)
    print(f"  ✓ {len(SNIPPETS)} RAG review traces written to ./.traces/showcase.duckdb")
    print("=" * 72)


if __name__ == "__main__":
    run_all_scenarios()
