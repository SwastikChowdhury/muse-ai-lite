"""Input safety filter. Runs BEFORE any agent — the LLM never sees flagged messages,
so no prompt injection can override the escalation path.

This is a deliberately simple, deterministic keyword filter rather than a model:
for a crisis path we want predictability and zero dependence on an LLM that could
be rate-limited, slow, or jailbroken. It is a safety net for a practice tool, not
a clinical triage system — it errs toward catching obvious crisis language and
will both miss paraphrases and occasionally over-trigger. main.py calls
check_safety on every inbound message and short-circuits the turn on a hit.
"""

# Lowercased substrings that trigger escalation. Substring (not word-boundary)
# matching is intentional so variants like "suicidal" are still caught.
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
    """Return the crisis-resource response if `message` matches a crisis pattern, else None.

    A truthy return is the signal main.py uses to bypass the agents entirely and
    reply with support resources. Case-insensitive substring match; no side
    effects.
    """
    lower = message.lower()
    for pattern in CRISIS_PATTERNS:
        if pattern in lower:
            return ESCALATION_RESPONSE
    return None