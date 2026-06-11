"""Lightweight model registry for API-hosted models.

Single source of truth for which model each agent runs on,
with version history and live rollback.
"""

REGISTRY = {
#   Better for the demo (needs billing):
#   "gemini-3.5-flash"            # $1.50 / $9.00  · near-Pro quality at Flash speed — best responses (Recommended)
#   "gemini-3-flash"              # $0.50 / $3.00  · cheaper middle ground
#   "gemini-2.5-flash"            # $0.30 / $2.50  · current
    "conversation": {
        "model": "gemini-3.5-flash",
        "previous": "gemini-2.5-flash",
        "version": 2,
        "reason": "Near-Pro quality for the mentee persona",
    },
#   "gemini-2.5-flash-lite"     # $0.10 / $0.40  · current
#   "gemini-3.1-flash-lite"       # $0.25 / $1.50  · newer, very low latency (Recommended)
    "whisper": {
        "model": "gemini-3.1-flash-lite",
        "previous": "gemini-2.5-flash-lite",
        "version": 2,
        "reason": "Low latency + low cost for short coaching notes",
    },
}


def get_model(agent: str) -> str:
    return REGISTRY[agent]["model"]


def rollback(agent: str) -> dict:
    """Swap an agent to its previous model. Returns the new state."""
    entry = REGISTRY.get(agent)
    if not entry or not entry.get("previous"):
        return {"error": f"No previous model for agent '{agent}'"}
    entry["model"], entry["previous"] = entry["previous"], entry["model"]
    entry["version"] += 1
    return {"agent": agent, "model": entry["model"], "version": entry["version"]}