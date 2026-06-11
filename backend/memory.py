import time
import uuid
import chromadb

chroma_client = chromadb.PersistentClient(path="./chroma_data")
memory_collection = chroma_client.get_or_create_collection("mentor_patterns")

RECENCY_HALF_LIFE_DAYS = 14  # a memory's recency weight halves every 2 weeks


def add_memory(user_id: str, text: str) -> None:
    """Store a mentor message with a timestamp for recency-aware retrieval."""
    memory_collection.add(
        documents=[text],
        metadatas=[{"user_id": user_id, "ts": time.time()}],
        ids=[str(uuid.uuid4())],
    )


def get_relevant_memories(user_id: str, query: str, n: int = 3) -> list[str]:
    """Two-stage retrieval: fetch 2n candidates by embedding similarity,
    then rerank by similarity x recency and return the top n."""
    try:
        results = memory_collection.query(
            query_texts=[query],
            n_results=max(n * 2, 6),
            where={"user_id": user_id},
            include=["documents", "distances", "metadatas"],
        )
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
    """Delete all memories for a user. Returns how many were removed."""
    try:
        existing = memory_collection.get(where={"user_id": user_id})
        ids = existing.get("ids") or []
        if ids:
            memory_collection.delete(ids=ids)
        return len(ids)
    except Exception:
        return 0