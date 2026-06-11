"""
MongoDB persistence layer for chat transcripts and coaching whispers.

Thin async data-access module: it owns the Mongo connection and the small set
of read/write helpers main.py uses to persist and replay a conversation. There
is intentionally no ORM and no business logic here — callers pass in validated
`models.Message` objects and get back plain dicts.

Two collections under the "muse" database:
  - messages  -> the mentor/mentee dialogue (role "user"/"assistant")
  - whispers  -> the private coaching notes (role "whisper")
They are kept separate so the conversation transcript and the coach's
side-channel can be queried and cleared independently.

Uses Motor (async MongoDB driver) so these calls don't block the event loop
that's also servicing the chat websocket.
"""

import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

client = AsyncIOMotorClient(os.environ["MONGODB_URI"])
db = client["muse"]
messages_collection = db["messages"]
whispers_collection = db["whispers"]



async def save_message(message) -> None:
    """Insert one mentor/mentee message. `message` is a models.Message.

    model_dump() flattens the Pydantic model (including the auto `created_at`)
    into the BSON document Mongo stores. Side effect: one insert.
    """
    await messages_collection.insert_one(message.model_dump())


async def get_history(user_id: str, conversation_id: str) -> list[dict]:
    """Fetch a conversation's full message history, oldest first.

    Sorted ascending by `created_at` so the agents and UI see turns in order.
    Capped at 1000 messages — a pragmatic ceiling for this demo that avoids
    unbounded reads; revisit (windowing/pagination) before long-lived chats.
    """
    cursor = messages_collection.find(
        {"user_id": user_id, "conversation_id": conversation_id}
    ).sort("created_at", 1)
    return await cursor.to_list(length=1000)

async def save_whisper(message) -> None:
    """Insert one coaching whisper (stored separately from the transcript)."""
    await whispers_collection.insert_one(message.model_dump())


async def get_whispers(user_id: str, conversation_id: str) -> list[dict]:
    """Fetch all persisted whispers for a conversation, oldest first.

    Mirrors get_history but against the whispers collection; used on websocket
    connect to rehydrate the Muse side-panel. Same 1000-doc cap applies.
    """
    cursor = whispers_collection.find(
        {"user_id": user_id, "conversation_id": conversation_id}
    ).sort("created_at", 1)
    return await cursor.to_list(length=1000)