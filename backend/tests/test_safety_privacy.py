from safety import check_safety
from privacy import redact_pii
from orchestrator import verify_grounding


def test_crisis_message_escalates():
    assert check_safety("I want to kill myself") is not None
    assert "988" in check_safety("i've been thinking about self harm")


def test_normal_message_passes():
    assert check_safety("Alex, your report needs work") is None


def test_pii_redaction():
    out = redact_pii("Email me at jo@x.com or call 412-555-1234, SSN 123-45-6789")
    assert "jo@x.com" not in out and "412-555-1234" not in out and "123-45-6789" not in out
    assert "[REDACTED_EMAIL]" in out and "[REDACTED_PHONE]" in out and "[REDACTED_SSN]" in out


def test_grounding_valid_citation():
    text, status = verify_grounding("You're softening again [M1].", ["past note"])
    assert status == "grounded" and "[M1]" not in text


def test_grounding_hallucinated_citation():
    _, status = verify_grounding("As before [M3].", ["only one memory"])
    assert status == "ungrounded"


def test_grounding_cited_with_no_memories():
    _, status = verify_grounding("Like last time [M1].", [])
    assert status == "ungrounded"