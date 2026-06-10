from fastapi.testclient import TestClient
import main


def test_websocket_protocol(monkeypatch):
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
        await ws.send_json({"type": "whisper", "content": "coaching note"})
        return "Hi", "coaching note"

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