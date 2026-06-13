"""
ML content-moderation pipeline (Layer 2 of the safety stack).

Three local HuggingFace classifiers, loaded once at import time and reused on
every call (model load is expensive and must never happen per-request):

  - suicidality_classifier (sentinet/suicidality):
      the PRIMARY crisis detector — a RoBERTa fine-tuned for suicidality. Its
      score directly drives the 988 escalation. This replaces the old
      emotion-as-crisis proxy, which missed risk phrased as fear/neutral.
  - emotion_classifier (j-hartmann/emotion-english-distilroberta-base):
      retained for OBSERVABILITY. We record the full emotion distribution on
      every message (tracked over time in MongoDB / Grafana) and also keep a
      secondary sadness+fear "distress" crisis signal gated by CRISIS_THRESHOLD.
  - toxic_classifier (unitary/toxic-bert):
      six toxicity categories (toxic, severe_toxic, obscene, threat, insult,
      identity_hate), run on mentor input AND mentee output.

Crisis (988) escalation fires when EITHER the suicidality score exceeds
SUICIDE_THRESHOLD OR the emotion distress proxy exceeds CRISIS_THRESHOLD — a
defense-in-depth OR. The suicidality model is the strong signal; the emotion
proxy is a secondary net (raise CRISIS_THRESHOLD toward 1.0 to make suicidality
effectively the sole trigger).

Design contract: moderation is best-effort and must NEVER break a conversation.
Every model call is wrapped in try/except and the module degrades to a safe,
un-flagged result on any error. This sits behind safety.check_safety's fast
keyword path — the keyword filter still owns the deterministic crisis short-
circuit; this layer adds the model-based net plus toxicity scoring.
"""

import os

from dotenv import load_dotenv
from transformers import pipeline

load_dotenv()

# Thresholds are env-configurable so they can be tuned/toggled without a code
# change (e.g. tighten in prod, loosen for a demo). Defaults preserve behavior
# when the vars are unset.
# PRIMARY crisis signal: sentinet/suicidality probability above this escalates.
SUICIDE_THRESHOLD = float(os.environ.get("SUICIDE_THRESHOLD", "0.5"))
# SECONDARY crisis signal: emotion distress proxy (sadness + fear) above this.
CRISIS_THRESHOLD = float(os.environ.get("CRISIS_THRESHOLD", "0.85"))
# Any single toxic-bert category above this marks a toxic flag.
TOXIC_THRESHOLD = float(os.environ.get("TOXIC_THRESHOLD", "0.5"))

# Emotion scores below this are dropped as noise when computing the distress
# proxy. NOTE: this only affects the secondary crisis proxy — the FULL emotion
# distribution is always recorded for observability regardless of this floor.
_EMOTION_MIN_SCORE = 0.3

# Initialize all pipelines once at module level. top_k=None returns the full
# label distribution (rather than just the argmax) so we can combine/threshold
# categories ourselves.
suicidality_classifier = pipeline(
    "text-classification",
    model="sentinet/suicidality",
    top_k=None,
)
emotion_classifier = pipeline(
    "text-classification",
    model="j-hartmann/emotion-english-distilroberta-base",
    top_k=None,
)
toxic_classifier = pipeline(
    "text-classification",
    model="unitary/toxic-bert",
    top_k=None,
)


def _to_score_dict(raw) -> dict:
    """Normalize a transformers text-classification result into {label: score}.

    With top_k=None the pipeline returns either a list of {label, score} dicts
    or a single-element batch wrapping that list; flatten either shape.
    """
    if raw and isinstance(raw[0], list):
        raw = raw[0]
    return {item["label"].lower(): float(item["score"]) for item in raw}


def score_emotion(text: str) -> dict:
    """Returns the full emotion distribution (anger, fear, sadness, joy, ...)."""
    return _to_score_dict(emotion_classifier(text))


def score_toxic(text: str) -> dict:
    """Returns all six toxic-bert category scores."""
    return _to_score_dict(toxic_classifier(text))


def score_suicidality(text: str) -> float:
    """Returns the suicidality probability (sentinet/suicidality, label_1)."""
    scores = _to_score_dict(suicidality_classifier(text))
    # sentinet/suicidality emits label_0 (non-suicidal) / label_1 (suicidal).
    return scores.get("label_1", 0.0)


def moderate(text: str, role: str) -> dict:
    """Run moderation on a message.

    Runs all three classifiers and returns:
        {
            "flagged": bool,
            "flag_type": str | None,        # "crisis", "toxic", "both"
            "suicide_score": float | None,  # sentinet prob, only when it escalated
            "crisis_score": float | None,   # emotion sadness+fear, only if over CRISIS_THRESHOLD
            "toxic_scores": dict | None,    # only categories scoring above threshold
            "emotions": dict,               # ALWAYS present — full distribution, for tracking
        }

    Crisis is flagged when suicide_score > SUICIDE_THRESHOLD OR the emotion
    distress proxy > CRISIS_THRESHOLD. Toxic is flagged when any toxic-bert
    category > TOXIC_THRESHOLD. flag_type is "both" when crisis and toxic
    co-occur.

    `emotions` is recorded for every message (mentor and mentee) regardless of
    whether anything was flagged — it's the observability signal, not a gate.

    Never raises: any failure degrades to an un-flagged result with no emotions.
    """
    try:
        # Always recorded for observability (full 7-emotion distribution).
        emotions = score_emotion(text)

        # PRIMARY crisis signal.
        suicide_score = score_suicidality(text)
        is_suicide = suicide_score > SUICIDE_THRESHOLD

        # SECONDARY crisis signal: emotion distress proxy, gated by the noise
        # floor so near-zero emotions don't contribute.
        meaningful = {k: v for k, v in emotions.items() if v >= _EMOTION_MIN_SCORE}
        crisis_score = meaningful.get("sadness", 0.0) + meaningful.get("fear", 0.0)
        is_emotion_crisis = crisis_score > CRISIS_THRESHOLD

        is_crisis = is_suicide or is_emotion_crisis

        toxic_all = score_toxic(text)
        # Surface only the categories that actually crossed the threshold.
        toxic_hits = {k: v for k, v in toxic_all.items() if v > TOXIC_THRESHOLD}
        is_toxic = bool(toxic_hits)

        if is_crisis and is_toxic:
            flag_type = "both"
        elif is_crisis:
            flag_type = "crisis"
        elif is_toxic:
            flag_type = "toxic"
        else:
            flag_type = None

        return {
            "flagged": bool(flag_type),
            "flag_type": flag_type,
            "suicide_score": suicide_score if is_suicide else None,
            "crisis_score": crisis_score if is_emotion_crisis else None,
            "toxic_scores": toxic_hits if is_toxic else None,
            "emotions": emotions,
        }
    except Exception as e:  # noqa: BLE001 — moderation must never break a turn
        print(f"Moderation failed (degrading to flagged=False): {e}")
        return {
            "flagged": False,
            "flag_type": None,
            "suicide_score": None,
            "crisis_score": None,
            "toxic_scores": None,
            "emotions": {},
        }
