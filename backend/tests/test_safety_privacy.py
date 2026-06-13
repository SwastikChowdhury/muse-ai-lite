"""Tests for the three guardrails: crisis safety, PII redaction, and memory grounding.

All three are pure/deterministic functions, so these run without any LLM or DB.
"""

import re

from safety import check_safety
from privacy import redact_pii
from orchestrator import verify_grounding


def test_crisis_message_escalates():
    """Crisis phrasing triggers escalation, and the response includes the 988 hotline.

    check_safety now returns (escalation | None, moderation_result); the keyword
    fast path matches here so this never reaches the ML layer.
    """
    escalation, _ = check_safety("I want to kill myself")
    assert escalation is not None
    escalation, _ = check_safety("i've been thinking about self harm")
    assert "988" in escalation


def test_ml_crisis_escalates_without_keyword():
    """Crisis phrasing that dodges the keyword list still escalates via Layer 2.

    "jump from a building" matches none of the keyword patterns, so this only
    passes if the suicidality model (primary crisis signal) fires.
    """
    escalation, mod = check_safety("I feel like I need to jump from a building")
    assert escalation is not None and "988" in escalation
    assert mod["flag_type"] in ("crisis", "both")


def test_normal_message_passes():
    """Ordinary mentoring feedback is not flagged (no false-positive escalation)."""
    escalation, mod = check_safety("Alex, your report needs work")
    assert escalation is None
    # The full emotion distribution is still recorded for observability.
    assert isinstance(mod["emotions"], dict)


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