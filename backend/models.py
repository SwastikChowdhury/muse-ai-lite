from datetime import datetime, timezone
from pydantic import BaseModel, Field


class User(BaseModel):
    user_id: str
    name: str | None = None


class Conversation(BaseModel):
    conversation_id: str
    user_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Message(BaseModel):
    user_id: str
    conversation_id: str
    role: str  # "user" or "assistant"
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))