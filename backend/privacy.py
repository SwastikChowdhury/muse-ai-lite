"""PII redaction. Applied at intake — PII never reaches the LLM, MongoDB, or the vector store.

Redaction happens at the very front of the turn in main.py, so the redacted text
is what everything downstream sees: it's persisted, embedded into memory, and
sent to Gemini. This is regex-based best-effort coverage of common identifiers
(email/phone/SSN), not a comprehensive PII detector — it's a privacy guardrail
for a demo, and patterns can be extended as needed.
"""

import re

# US-centric patterns; each is anchored on word boundaries to limit false hits.
# The phone pattern tolerates optional country code and common separators.
PII_PATTERNS = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
}


def redact_pii(text: str) -> str:
    """Replace each detected PII span with a "[REDACTED_<TYPE>]" placeholder.

    Applies every pattern in turn and returns the scrubbed string. Pure function
    (no side effects); the typed placeholder preserves enough context for the
    conversation to still read naturally.
    """
    for label, pattern in PII_PATTERNS.items():
        text = pattern.sub(f"[REDACTED_{label.upper()}]", text)
    return text