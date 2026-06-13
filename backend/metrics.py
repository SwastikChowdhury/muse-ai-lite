"""
Prometheus metric definitions for operational visibility.

Central registry of the custom metrics emitted across the backend (agent calls,
latency, live connections, safety/grounding events, rollbacks). Defined once
here and imported wherever they're incremented so there's a single source of
truth for names/labels. Exposed at GET /metrics via the Instrumentator set up in
main.py and scraped by Prometheus (see monitoring/). LLM token/cost metrics live
separately in llm_metrics.py.

Metric-type rationale: Counters for monotonically increasing event tallies,
a Histogram for latency distributions, and a Gauge for a value that goes up and
down (currently-open connections).
"""

from prometheus_client import Counter, Histogram, Gauge

gemini_calls = Counter(
    "muse_gemini_calls_total",
    "Gemini API calls by agent and outcome",
    ["agent", "outcome"],
)

agent_latency = Histogram(
    "muse_agent_latency_seconds",
    "Agent response latency in seconds",
    ["agent"],
)

active_ws = Gauge(
    "muse_active_websocket_connections",
    "Currently open chat WebSocket connections",
)

safety_escalations = Counter(
    "muse_safety_escalations_total",
    "Messages caught by the safety filter before reaching any agent",
)

whisper_grounding = Counter(
    "muse_whisper_grounding_total",
    "Whisper notes by grounding status",
    ["status"],  # grounded | ungrounded | no_memory
)

model_rollbacks = Counter(
    "muse_model_rollbacks_total",
    "Live model rollbacks by agent",
    ["agent"],
)

moderation_flags = Counter(
    "muse_moderation_flags_total",
    "Messages flagged by the moderation pipeline",
    ["role", "flag_type"],  # role: mentor|mentee, flag_type: crisis|toxic|both
)

message_emotions = Counter(
    "muse_message_emotions_total",
    "Messages by dominant emotion (observability only, does not gate anything)",
    ["role", "emotion"],  # role: mentor|mentee, emotion: anger|fear|sadness|joy|...
)


def record_dominant_emotion(role: str, emotions: dict | None) -> None:
    """Increment the dominant-emotion counter for one message.

    `emotions` is the full distribution from moderation.score_emotion (or empty
    on failure). We chart the single strongest emotion per message so Grafana
    can show, by rate, how mentor/mentee emotional tone shifts over time. A
    no-op when there's nothing to record (e.g. moderation failed).
    """
    if not emotions:
        return
    dominant = max(emotions, key=emotions.get)
    message_emotions.labels(role=role, emotion=dominant).inc()