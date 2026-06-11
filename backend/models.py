"""
Pydantic data models — the canonical shape of records stored in MongoDB.

These define the wire/storage contract used throughout the backend: db.py calls
`.model_dump()` on them to produce BSON documents, and main.py constructs them
per turn. Timestamps default to timezone-aware UTC so ordering is unambiguous
regardless of server locale.

The current single-user demo only actively persists `Message`; `User` and
`Conversation` describe the intended multi-tenant schema and are the seam where
real per-user/per-conversation modelling would plug in.
"""

from datetime import datetime, timezone
from pydantic import BaseModel, Field


class User(BaseModel):
    """An end user. `name` is optional to allow anonymous/demo users."""
    user_id: str
    name: str | None = None


class Conversation(BaseModel):
    """A single chat session, owned by a user and stamped at creation.

    `created_at` defaults to now-UTC via a factory so each instance gets its own
    timestamp (a plain default would freeze one value at import time).
    """
    conversation_id: str
    user_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Message(BaseModel):
    """One stored utterance in a conversation.

    `role` is a free-form string by convention rather than an enum: "user" and
    "assistant" for the transcript, plus "whisper" for coaching notes (which are
    persisted in a separate collection but reuse this same model). `created_at`
    is the sort key used by db.get_history/get_whispers to replay turns in order.
    """
    user_id: str
    conversation_id: str
    role: str  # "user" or "assistant"
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))