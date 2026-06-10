import uuid
import chromadb

chroma_client = chromadb.PersistentClient(path="./chroma_data")
memory_collection = chroma_client.get_or_create_collection("mentor_patterns")


def add_memory(user_id: str, text: str) -> None:
    """Store a mentor message so it can be recalled in future sessions."""
    memory_collection.add(
        documents=[text],
        metadatas=[{"user_id": user_id}],
        ids=[str(uuid.uuid4())],
    )


def get_relevant_memories(user_id: str, query: str, n: int = 3) -> list[str]:
    """Retrieve the mentor's most relevant past messages for the current turn."""
    try:
        results = memory_collection.query(
            query_texts=[query],
            n_results=n,
            where={"user_id": user_id},
        )
        docs = results.get("documents") or [[]]
        return docs[0]
    except Exception:
        return []