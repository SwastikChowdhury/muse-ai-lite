"""Input safety filter. Runs BEFORE any agent — the LLM never sees flagged messages,
so no prompt injection can override the escalation path."""

CRISIS_PATTERNS = [
    "kill myself", "want to die", "end my life", "suicide",
    "hurt myself", "self harm", "self-harm",
]

ESCALATION_RESPONSE = (
    "I hear you, and what you're feeling matters. This practice tool isn't the right "
    "support for this moment — please reach out to the 988 Suicide & Crisis Lifeline "
    "(call or text 988, available 24/7). You deserve real support."
)


def check_safety(message: str) -> str | None:
    """Return an escalation response if the message triggers a crisis rule, else None."""
    lower = message.lower()
    for pattern in CRISIS_PATTERNS:
        if pattern in lower:
            return ESCALATION_RESPONSE
    return None