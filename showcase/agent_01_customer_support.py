"""Agent 01 — Customer Support Classifier

Pattern: Simple Linear Chain
    CustomerSupportAgent (root, @trace_agent)
      ├── chat gpt-4o-mini  (classify ticket — fast, cheap model)
      └── chat gpt-4o       (generate detailed response — powerful model)

Takes a customer support ticket, classifies it into a category
(billing, technical, account_access, feature_request, cancellation),
then generates a helpful, empathetic response using a more powerful model.
"""

from __future__ import annotations

import nanotrace
from showcase._simulator import mock_llm_call

# ── Initialise NanoTrace ────────────────────────────────────────────────────
nanotrace.init(storage_path="./.traces/showcase.duckdb")

# ── Prompts ─────────────────────────────────────────────────────────────────
CLASSIFIER_SYSTEM_PROMPT = (
    "You are a customer-support ticket classifier. "
    "Read the ticket and respond with exactly ONE label from: "
    "billing, technical, account_access, feature_request, cancellation. "
    "Do not explain; output only the label."
)

RESPONDER_SYSTEM_PROMPT = (
    "You are a friendly, empathetic customer-support agent for a SaaS platform. "
    "Draft a concise, helpful reply (3-5 sentences) to the customer's ticket. "
    "Include next steps, reference numbers where relevant, and maintain a professional tone."
)


# ── Agent ───────────────────────────────────────────────────────────────────
@nanotrace.trace_agent(name="CustomerSupportAgent", agent_type="classifier_responder")
def handle_ticket(ticket_text: str, expected_category: str, canned_response: str) -> dict:
    """Classify a support ticket and generate a response.

    Args:
        ticket_text: Raw customer message.
        expected_category: The scripted classification label for the mock.
        canned_response: The scripted agent reply for the mock.

    Returns:
        dict with keys ``category`` and ``response``.
    """
    # Step 1 — fast classification with gpt-4o-mini
    category = mock_llm_call(
        model="gpt-4o-mini",
        system_prompt=CLASSIFIER_SYSTEM_PROMPT,
        user_message=ticket_text,
        response=expected_category,
        span_name="chat gpt-4o-mini",
        temperature=0.0,
    )

    # Step 2 — detailed response with gpt-4o
    response = mock_llm_call(
        model="gpt-4o",
        system_prompt=RESPONDER_SYSTEM_PROMPT,
        user_message=(
            f"Category: {category}\n\nOriginal ticket:\n{ticket_text}"
        ),
        response=canned_response,
        span_name="chat gpt-4o",
        temperature=0.7,
    )

    return {"category": category, "response": response}


# ── Scenario Data ──────────────────────────────────────────────────────────
TICKETS = [
    {
        "ticket": (
            "I was charged twice for my Pro subscription last month. "
            "Order #ORD-8834."
        ),
        "category": "billing",
        "response": (
            "Thank you for reaching out — I sincerely apologize for the duplicate charge "
            "on order #ORD-8834. I've initiated a full refund for the second payment, which "
            "should appear in your account within 3–5 business days. Your refund reference "
            "number is REF-20240412-8834. If you don't see the credit by then, please reply "
            "to this ticket and we'll escalate it immediately."
        ),
    },
    {
        "ticket": (
            "The API keeps returning 500 errors when I try to upload files larger "
            "than 10MB through the /v2/files endpoint."
        ),
        "category": "technical",
        "response": (
            "Thanks for the detailed report — the /v2/files endpoint enforces a 10 MB "
            "per-request limit on the Starter and Pro plans. For files exceeding that "
            "threshold, please use our multipart chunked-upload endpoint at "
            "POST /v2/files/multipart, which supports uploads up to 5 GB. You can find "
            "a complete code example in our docs at docs.example.com/uploads#chunked. "
            "Let us know if you run into any further issues!"
        ),
    },
    {
        "ticket": (
            "I forgot my password and the reset email never arrives. "
            "I've checked spam. My email is john@company.com."
        ),
        "category": "account_access",
        "response": (
            "I'm sorry you're having trouble accessing your account. First, please "
            "confirm that john@company.com is the email address you registered with, "
            "as sometimes accounts are created with a different alias. If it is correct, "
            "I've escalated your case to our security team (ticket SEC-77231) for a manual "
            "identity verification — they'll reach out within 24 hours with next steps. "
            "In the meantime, please have a photo ID ready to speed things up."
        ),
    },
    {
        "ticket": (
            "Would it be possible to add webhook support to the Starter plan? "
            "We'd love real-time event notifications."
        ),
        "category": "feature_request",
        "response": (
            "Thank you for the suggestion — we love hearing how customers want to use "
            "the platform! Webhook support is currently available on our Pro and Enterprise "
            "plans. I've logged your request with our product team (FR-9921) so it's on "
            "their radar for future Starter-plan enhancements. In the meantime, you can "
            "use our polling API (GET /v2/events?since=<timestamp>) to check for new "
            "events at whatever frequency works for your workflow."
        ),
    },
    {
        "ticket": (
            "I want to cancel my annual subscription. I have 7 months remaining "
            "and would like a pro-rated refund."
        ),
        "category": "cancellation",
        "response": (
            "I understand, and I'm sorry to see you considering cancellation. Per our "
            "policy, annual plans purchased within the last 30 days qualify for a full "
            "refund; beyond that window we offer a pro-rated credit toward future usage "
            "rather than a cash refund. I'd love to schedule a brief 15-minute call with "
            "our Customer Success team to see if there's anything we can adjust before "
            "you finalize — would you be open to that? Either way, just reply and I'll "
            "process your request promptly."
        ),
    },
]


# ── Runner ──────────────────────────────────────────────────────────────────
def run_all_scenarios() -> None:
    """Execute all five support-ticket scenarios and print a summary."""
    print("=" * 72)
    print("  Agent 01 — Customer Support Classifier (Linear Chain)")
    print("=" * 72)

    results = []
    for i, item in enumerate(TICKETS, 1):
        result = handle_ticket(
            ticket_text=item["ticket"],
            expected_category=item["category"],
            canned_response=item["response"],
        )
        results.append(result)

        preview = result["response"][:90].replace("\n", " ") + "…"
        print(f"\n  Ticket {i}")
        print(f"    Input   : {item['ticket'][:70]}…")
        print(f"    Category: {result['category']}")
        print(f"    Response: {preview}")

    nanotrace.flush()

    print("\n" + "-" * 72)
    print(f"  ✓ {len(results)} traces written to ./.traces/showcase.duckdb")
    print("=" * 72)


if __name__ == "__main__":
    run_all_scenarios()
