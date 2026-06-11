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