"""Tests for the three guardrails: crisis safety, PII redaction, and memory grounding.

All three are pure/deterministic functions, so these run without any LLM or DB.
"""

import re

from safety import check_safety
from privacy import redact_pii
from orchestrator import verify_grounding


def test_crisis_message_escalates():
    """Crisis phrasing triggers escalation, and the response includes the 988 hotline."""
    assert check_safety("I want to kill myself") is not None
    assert "988" in check_safety("i've been thinking about self harm")


def test_normal_message_passes():
    """Ordinary mentoring feedback is not flagged (no false-positive escalation)."""
    assert check_safety("Alex, your report needs work") is None


def test_pii_redaction():
    """Email, phone, and SSN are detected and replaced with salted hash tokens.

    Presidio finds the PII and each span is swapped for an irreversible "[<8 hex>]"
    token. Raw values must not survive, and the same input must hash consistently.
    """
    # Use a realistic SSN: Presidio intentionally ignores well-known dummy SSNs
    # (e.g. 123-45-6789, 078-05-1120) via UsSsnRecognizer.invalidate_result.
    ssn = "457-55-5462"
    text = f"Email me at jo@x.com or call 412-555-1234, SSN {ssn}"
    out = redact_pii(text)
    assert "jo@x.com" not in out and "412-555-1234" not in out and ssn not in out
    # Tokens are 8 lowercase hex chars wrapped in brackets, e.g. "[a3f9b2c1]".
    assert len(re.findall(r"\[[0-9a-f]{8}\]", out)) >= 3
    # Deterministic: same input + same salt yields the same output.
    assert redact_pii(text) == out


def test_grounding_valid_citation():
    """A citation pointing to a real memory is 'grounded' and the [Mn] marker is stripped."""
    text, status = verify_grounding("You're softening again [M1].", ["past note"])
    assert status == "grounded" and "[M1]" not in text


def test_grounding_hallucinated_citation():
    """Citing [M3] when only one memory exists is flagged 'ungrounded' (out-of-range index)."""
    _, status = verify_grounding("As before [M3].", ["only one memory"])
    assert status == "ungrounded"


def test_grounding_cited_with_no_memories():
    """Citing any memory when none were provided is 'ungrounded' — a clear hallucination."""
    _, status = verify_grounding("Like last time [M1].", [])
    assert status == "ungrounded"