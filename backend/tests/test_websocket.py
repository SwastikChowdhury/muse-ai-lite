"""End-to-end test of the /ws frame protocol with DB and orchestrator stubbed.

Verifies the transport contract the chat router promises clients: a history
frame on connect, then token/done/whisper frames per turn, and that a truthy
whisper is persisted. All persistence and agent work is faked so the test is
fast and network-free.
"""

from fastapi.testclient import TestClient
from app.main import app
from app.api import chat


def test_websocket_protocol(monkeypatch):
    """Connect -> receive history -> send a message -> receive token/done/whisper in order.

    Also asserts exactly one whisper is persisted, exercising the chat router's
    "only save truthy whispers" branch.
    """
    async def fake_get_history(uid, cid):
        return []

    async def fake_get_whispers(uid, cid):
        return []

    async def fake_save_message(msg):
        return None

    saved_whispers = []

    async def fake_save_whisper(msg):
        saved_whispers.append(msg)

    async def fake_handle_turn(ws, history, user_message, user_id, conversation_id):
        await ws.send_json({"type": "token", "content": "Hi"})
        await ws.send_json({"type": "done"})
        await ws.send_json({"type": "whisper", "content": "coaching note", "label": "Tone"})
        mentee_mod = {"flagged": False, "flag_type": None, "emotions": None}
        return "Hi", "Tone", "coaching note", mentee_mod

    monkeypatch.setattr(chat, "get_history", fake_get_history)
    monkeypatch.setattr(chat, "get_whispers", fake_get_whispers)
    monkeypatch.setattr(chat, "save_message", fake_save_message)
    monkeypatch.setattr(chat, "save_whisper", fake_save_whisper)
    monkeypatch.setattr(chat, "handle_turn", fake_handle_turn)
    # The /ws endpoint now requires a valid access token; stub verification so the
    # transport contract can be tested without minting a real JWT.
    monkeypatch.setattr(chat, "verify_access_token", lambda token: "test-user")

    client = TestClient(app)
    with client.websocket_connect("/ws?token=test") as ws:
        assert ws.receive_json()["type"] == "history"
        ws.send_text("hello")
        types_ = [ws.receive_json()["type"] for _ in range(3)]
        assert types_ == ["token", "done", "whisper"]

    assert len(saved_whispers) == 1   # whisper persisted because it was truthy
    assert saved_whispers[0].label == "Tone"   # tone/category persisted alongside the note