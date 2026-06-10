from models import Message, User, Conversation


def test_message_fields_and_timestamp():
    m = Message(user_id="u1", conversation_id="c1", role="user", content="hello")
    assert m.role == "user"
    assert m.content == "hello"
    assert m.created_at is not None


def test_message_serializes_for_mongo():
    m = Message(user_id="u1", conversation_id="c1", role="whisper", content="note")
    doc = m.model_dump()
    assert doc["role"] == "whisper"
    assert doc["content"] == "note"
    assert "created_at" in doc


def test_user_name_optional():
    assert User(user_id="u1").name is None
    assert Conversation(conversation_id="c1", user_id="u1").created_at is not None