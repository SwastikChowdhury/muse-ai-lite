"""PII pseudonymization. Applied at intake — raw PII never reaches the LLM, MongoDB, or the vector store.

Detection happens at the very front of the turn in main.py, so the scrubbed text
is what everything downstream sees: it's persisted, embedded into memory, and
sent to Gemini. Microsoft Presidio's local NER/recognizers find PII entities, and
each detected value is replaced with a short, salted HMAC-SHA256 token instead of a
generic placeholder. This is deterministic (same input + same salt => same token)
so references stay linkable across turns, while remaining unreadable and irreversible.
"""

import hashlib
import hmac
import logging
import os

from dotenv import load_dotenv
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

logger = logging.getLogger(__name__)

load_dotenv()

# Salt for the HMAC. A default is provided so the module never hard-fails, but a
# default salt makes the tokens guessable, so we warn loudly if it's in use.
_DEFAULT_SALT = "default-salt"
PII_SALT = os.environ.get("PII_SALT", _DEFAULT_SALT)
if PII_SALT == _DEFAULT_SALT:
    logger.warning(
        "PII_SALT not set in environment; using insecure default salt. "
        "Set PII_SALT in the environment for irreversible, non-guessable PII tokens."
    )

_SALT_BYTES = PII_SALT.encode("utf-8")

# Initialize the Presidio engines once at import time — loading the spaCy model
# is expensive and must not happen per call. The anonymizer is reused so that
# overlapping detections (e.g. an email that also matches a URL) are resolved by
# Presidio's conflict handling rather than by naive string surgery.
_analyzer = AnalyzerEngine()
_anonymizer = AnonymizerEngine()


def _hash_pii(value: str) -> str:
    """Return a short, deterministic, salted token for a PII value.

    HMAC-SHA256 over the salt keeps the mapping one-way and consistent; we take
    the first 8 hex chars of the digest and wrap them in brackets, e.g. "[a3f9b2c1]".
    """
    digest = hmac.new(_SALT_BYTES, value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"[{digest[:8]}]"


def redact_pii(text: str) -> str:
    """Replace each detected PII span with a short salted hash token.

    Presidio detects PII entities locally and the anonymizer applies a custom
    operator that swaps each span for an irreversible "[<8 hex>]" token. Using the
    anonymizer (rather than manual slicing) lets Presidio resolve overlapping
    detections. Same input + same salt always yields the same token.
    """
    if not text:
        return text

    results = _analyzer.analyze(text=text, language="en")
    if not results:
        return text

    anonymized = _anonymizer.anonymize(
        text=text,
        analyzer_results=results,
        operators={
            "DEFAULT": OperatorConfig("custom", {"lambda": lambda value: _hash_pii(value)})
        },
    )
    return anonymized.text
