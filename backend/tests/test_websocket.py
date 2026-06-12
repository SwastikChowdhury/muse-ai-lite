"""End-to-end test of the /ws frame protocol with DB and orchestrator stubbed.

Verifies the transport contract main.py promises clients: a history frame on
connect, then token/done/whisper frames per turn, and that a truthy whisper is
persisted. All persistence and agent work is faked so the test is fast and
network-free.
"""

from fastapi.testclient import TestClient
import main


def test_websocket_protocol(monkeypatch):
    """Connect -> receive history -> send a message -> receive token/done/whisper in order.

    Also asserts exactly one whisper is persisted, exercising main.py's
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

    async def fake_handle_turn(ws, history, user_message, user_id):
        await ws.send_json({"type": "token", "content": "Hi"})
        await ws.send_json({"type": "done"})
        await ws.send_json({"type": "whisper", "content": "coaching note", "label": "Tone"})
        return "Hi", "Tone", "coaching note"

    monkeypatch.setattr(main, "get_history", fake_get_history)
    monkeypatch.setattr(main, "get_whispers", fake_get_whispers)
    monkeypatch.setattr(main, "save_message", fake_save_message)
    monkeypatch.setattr(main, "save_whisper", fake_save_whisper)
    monkeypatch.setattr(main, "handle_turn", fake_handle_turn)

    client = TestClient(main.app)
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "history"
        ws.send_text("hello")
        types_ = [ws.receive_json()["type"] for _ in range(3)]
        assert types_ == ["token", "done", "whisper"]

    assert len(saved_whispers) == 1   # whisper persisted because it was truthy
    assert saved_whispers[0].label == "Tone"   # tone/category persisted alongside the note