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