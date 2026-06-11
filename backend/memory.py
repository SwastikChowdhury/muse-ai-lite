"""
Long-term mentor memory backed by a local Chroma vector store.

Gives the whisper/coach agent cross-session recall so it can point out
*recurring* mentor habits (e.g. "you're softening your feedback again") rather
than only reacting to the current exchange. Each mentor message is embedded and
stored; on later turns the orchestrator retrieves the most relevant past
messages and injects them into the whisper prompt as citable [Mn] notes.

Design notes:
  - Persistence is a local on-disk Chroma collection (./chroma_data), so memory
    survives restarts without an external service. Embeddings use Chroma's
    default model.
  - Retrieval is recency-aware (see get_relevant_memories): pure semantic
    similarity would resurface stale one-off moments, so we blend in a time
    decay to favor patterns that are both relevant AND current.
  - Every public function swallows store errors and degrades to an empty/no-op
    result — memory is an enhancement, and a vector-store hiccup must never take
    down a chat turn.

Consumed by orchestrator.handle_turn (add/retrieve) and the /admin/clear-data
endpoint (clear) for data-rights deletion.
"""

import time
import uuid
import chromadb

chroma_client = chromadb.PersistentClient(path="./chroma_data")
memory_collection = chroma_client.get_or_create_collection("mentor_patterns")

RECENCY_HALF_LIFE_DAYS = 14  # a memory's recency weight halves every 2 weeks


def add_memory(user_id: str, text: str) -> None:
    """Embed and store one mentor message, tagged by user and wall-clock time.

    The timestamp (`ts`) is what makes recency-aware retrieval possible later.
    Called once per turn by the orchestrator. Side effect: a write to the Chroma
    collection. A random UUID id keeps every entry distinct (we never update or
    dedupe memories).
    """
    memory_collection.add(
        documents=[text],
        metadatas=[{"user_id": user_id, "ts": time.time()}],
        ids=[str(uuid.uuid4())],
    )


def get_relevant_memories(user_id: str, query: str, n: int = 3) -> list[str]:
    """Return the top-`n` past mentor messages most useful for coaching `query`.

    Two-stage retrieval:
      1. Ask Chroma for ~2n nearest neighbours by embedding similarity (scoped
         to this user). Over-fetching gives the rerank step room to promote a
         slightly-less-similar but much-more-recent memory.
      2. Rerank by combined similarity × recency and keep the best n.

    Scoring details:
      - similarity = 1/(1+distance): converts Chroma's distance (smaller = closer)
        into a 0–1 score where higher is better.
      - recency = 0.5 ** (age_days / half_life): exponential decay, halving every
        RECENCY_HALF_LIFE_DAYS.
      - final = similarity * (0.7 + 0.3 * recency): recency is a gentle 30%
        modifier, NOT a hard filter — a highly relevant old memory can still win
        over a recent irrelevant one, but ties break toward fresher patterns.

    Returns a list of memory strings (possibly empty). Never raises: any store
    error degrades to [] so the whisper agent simply coaches without memory.
    """
    try:
        results = memory_collection.query(
            query_texts=[query],
            n_results=max(n * 2, 6),
            where={"user_id": user_id},
            include=["documents", "distances", "metadatas"],
        )
        # Chroma returns one result-list per query; we sent a single query so we
        # index [0]. The `or [[]]` guards against a missing key on empty results.
        docs = (results.get("documents") or [[]])[0]
        dists = (results.get("distances") or [[]])[0]
        metas = (results.get("metadatas") or [[]])[0]
        if not docs:
            return []

        now = time.time()
        scored = []
        for doc, dist, meta in zip(docs, dists, metas):
            similarity = 1.0 / (1.0 + dist)          # smaller distance -> higher score
            age_days = (now - meta.get("ts", now)) / 86400
            recency = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
            scored.append((similarity * (0.7 + 0.3 * recency), doc))

        scored.sort(key=lambda s: s[0], reverse=True)
        return [doc for _, doc in scored[:n]]
    except Exception:
        return []


def clear_memories(user_id: str) -> int:
    """Delete every stored memory for a user; return how many were removed.

    Backs the data-rights wipe in /admin/clear-data. Side effect: deletes from
    the Chroma collection. Returns 0 (rather than raising) on any error so the
    surrounding bulk-delete endpoint can still report partial success.
    """
    try:
        existing = memory_collection.get(where={"user_id": user_id})
        ids = existing.get("ids") or []
        if ids:
            memory_collection.delete(ids=ids)
        return len(ids)
    except Exception:
        return 0