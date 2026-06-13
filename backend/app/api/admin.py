"""Operational/admin endpoints: live model registry, rollback, and data wipe.

The whole /admin/* surface is unauthenticated — acceptable only for this
local/demo build, and must be locked down before any real deployment.
"""

from fastapi import APIRouter

from app.db.mongo import conversation_id_for, messages_collection, whispers_collection
from app.memory.memory import clear_memories
from app.observability.metrics import model_rollbacks
from app.observability.model_registry import REGISTRY, rollback

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/models")
def list_models():
    """Return the live model registry (current/previous model per agent).

    Response: the REGISTRY dict, used by ops to see what each agent is running.
    Unauthenticated — acceptable only because this is a local demo.
    """
    return REGISTRY


@router.post("/rollback/{agent}")
def rollback_model(agent: str):
    """Swap an agent back to its previous model at runtime (no redeploy).

    Path param `agent`: registry key, e.g. "conversation" or "whisper".
    Response: the new model state, or {"error": ...} if no previous model
    exists. The rollback metric is only incremented on a successful swap so
    failed attempts don't pollute the counter.
    """
    result = rollback(agent)
    if "error" not in result:
        model_rollbacks.labels(agent=agent).inc()
    return result


@router.delete("/clear-data/{user_id}")
async def clear_data(user_id: str):
    """Data-rights endpoint: wipe one user's conversation, whispers, and memories.

    Deletes across all three stores so no trace of the user remains:
    MongoDB messages, MongoDB whispers, and the Chroma vector memories. The
    conversation id is derived from the user id (see conversation_id_for) so the
    caller only needs to supply the user.

    Response: per-store deletion counts. Side effects: irreversible deletes in
    both MongoDB collections and the vector store.
    """
    conversation_id = conversation_id_for(user_id)
    deleted_msgs = await messages_collection.delete_many(
        {"user_id": user_id, "conversation_id": conversation_id})
    deleted_whispers = await whispers_collection.delete_many(
        {"user_id": user_id, "conversation_id": conversation_id})
    deleted_memories = clear_memories(user_id)
    return {
        "messages_deleted": deleted_msgs.deleted_count,
        "whispers_deleted": deleted_whispers.deleted_count,
        "memories_deleted": deleted_memories,
    }
