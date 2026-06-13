"""
LLM token-usage and cost accounting.

Separate from metrics.py because this concerns spend rather than service health:
it turns each Gemini response's usage_metadata into Prometheus counters for
tokens consumed and estimated USD cost, broken out per agent. Lets us watch the
relative cost of the conversation vs. whisper agents and catch runaway spend.

Cost is an *estimate*: token counts are exact (from the API), but the per-token
prices and the agent->model mapping are hardcoded here and must be kept in sync
with model_registry.py when models change. record_usage is called by agents.py
(whisper) and orchestrator.py (conversation, after the stream completes).
"""

from prometheus_client import Counter

llm_tokens = Counter(
    "muse_llm_tokens_total",
    "LLM tokens consumed, by agent and kind",
    ["agent", "kind"],          # kind: prompt | completion
)

llm_cost = Counter(
    "muse_llm_cost_usd_total",
    "Estimated LLM spend in USD, by agent",
    ["agent"],
)

# USD per token (input, output). Source: Google Gemini API pricing.
PRICES = {
    "gemini-2.5-flash":      {"in": 0.30 / 1_000_000, "out": 2.50 / 1_000_000},
    "gemini-3-flash":        {"in": 0.50 / 1_000_000, "out": 3.00 / 1_000_000},
    "gemini-3.5-flash":      {"in": 1.50 / 1_000_000, "out": 9.00 / 1_000_000},
    "gemini-3.1-flash-lite": {"in": 0.25 / 1_000_000, "out": 1.50 / 1_000_000},
}
_DEFAULT = {"in": 0.30 / 1_000_000, "out": 2.50 / 1_000_000}

# Which model each agent runs on (edit if you change buckets).
AGENT_MODEL = {
    "conversation": "gemini-2.5-flash", # "gemini-3.5-flash"
    "whisper": "gemini-2.5-flash", # "gemini-3.1-flash-lite"
}


def record_usage(agent: str, usage) -> None:
    """Record token counts + estimated cost from a Gemini response's usage_metadata.

    `usage` is the SDK's usage_metadata object (or None — e.g. a stream that
    never reported usage, in which case we no-op). Attribute reads are defensive
    (getattr ... or 0) because not every response/chunk populates both counts.

    Cost falls back to `_DEFAULT` pricing if the agent's model isn't in PRICES,
    so an unknown/newly-swapped model still produces a (rough) cost figure rather
    than zero. Side effect: increments the llm_tokens and llm_cost counters.
    """
    if usage is None:
        return
    prompt = getattr(usage, "prompt_token_count", 0) or 0
    completion = getattr(usage, "candidates_token_count", 0) or 0

    llm_tokens.labels(agent=agent, kind="prompt").inc(prompt)
    llm_tokens.labels(agent=agent, kind="completion").inc(completion)

    price = PRICES.get(AGENT_MODEL.get(agent, ""), _DEFAULT)
    llm_cost.labels(agent=agent).inc(prompt * price["in"] + completion * price["out"])