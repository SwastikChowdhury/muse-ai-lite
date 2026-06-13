"""Input safety filter. Runs BEFORE any agent — the LLM never sees flagged messages,
so no prompt injection can override the escalation path.

Two layers, fast-path first:
  Layer 1 — a deterministic keyword filter. For a crisis path we want
    predictability and zero dependence on a model that could be slow or wrong;
    a keyword hit short-circuits immediately and never runs the classifier.
  Layer 2 — the ML moderation pipeline (moderation.moderate). When no keyword
    matches, the suicidality classifier (primary) plus the emotion distress
    proxy (secondary) decide whether to escalate; either crossing its threshold
    sets flag_type to "crisis"/"both" and triggers the hotline response.

It is a safety net for a practice tool, not a clinical triage system — it errs
toward catching obvious crisis language and will both miss paraphrases and
occasionally over-trigger. main.py calls check_safety on every inbound message,
short-circuits the turn on a hit, and persists the returned moderation result
(including the recorded emotion distribution).
"""

from moderation import moderate

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

def check_safety(message: str) -> tuple[str | None, dict]:
    """Run the two-layer safety gate on a mentor message.

    Returns (escalation_response | None, moderation_result):
      Layer 1: keyword check (fast path). On a match, return the escalation
        response immediately WITHOUT running the models; the moderation result
        is marked as a crisis flag (with an empty emotion record) so the caller
        can persist it uniformly.
      Layer 2: ML moderation via moderate(). The suicidality model (primary)
        and the emotion distress proxy (secondary) decide crisis; if the result
        is flagged as crisis ("crisis"/"both"), return the escalation response.

    The moderation result is always returned (even when not escalating) so the
    caller can persist the moderation signal — including the recorded emotion
    distribution — for every message.
    """
    lower = message.lower()
    for pattern in CRISIS_PATTERNS:
        if pattern in lower:
            # Fast path: a deterministic keyword hit escalates without paying
            # for the models. Record it as a crisis flag for observation.
            return ESCALATION_RESPONSE, {
                "flagged": True,
                "flag_type": "crisis",
                "suicide_score": None,
                "crisis_score": None,
                "toxic_scores": None,
                "emotions": {},
            }

    # No keyword match — fall through to the ML layer.
    mod_result = moderate(message, role="mentor")
    if mod_result.get("flag_type") in ("crisis", "both"):
        return ESCALATION_RESPONSE, mod_result
    return None, mod_result