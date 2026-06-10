import asyncio
from types import SimpleNamespace

import orchestrator


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


def _chunks(*texts):
    return [SimpleNamespace(text=t) for t in texts]


def test_handle_turn_happy_path(monkeypatch):
    ws = FakeWebSocket()
    monkeypatch.setattr(orchestrator, "get_relevant_memories", lambda uid, q: [])
    monkeypatch.setattr(orchestrator, "add_memory", lambda uid, t: None)
    monkeypatch.setattr(orchestrator, "conversation_agent_stream",
                        lambda h, m: _chunks("Hello ", "there"))
    monkeypatch.setattr(orchestrator, "whisper_agent",
                        lambda h, m, r, p: "Nice opening.")

    full_reply, whisper = asyncio.run(
        orchestrator.handle_turn(ws, [], "Hi Alex", "demo-user")
    )

    assert full_reply == "Hello there"
    assert whisper == "Nice opening."
    types_sent = [p["type"] for p in ws.sent]
    assert "token" in types_sent and "done" in types_sent and "whisper" in types_sent


def test_handle_turn_quota_exhausted(monkeypatch):
    ws = FakeWebSocket()
    monkeypatch.setattr(orchestrator, "get_relevant_memories", lambda uid, q: [])
    monkeypatch.setattr(orchestrator, "add_memory", lambda uid, t: None)

    def boom(h, m):
        raise Exception("429 RESOURCE_EXHAUSTED")
    monkeypatch.setattr(orchestrator, "conversation_agent_stream", boom)
    monkeypatch.setattr(orchestrator, "whisper_agent", lambda h, m, r, p: "note")

    full_reply, whisper = asyncio.run(orchestrator.handle_turn(ws, [], "Hi", "demo-user"))

    assert "limit" in full_reply.lower()   # the graceful QUOTA_MSG, not a crash
    assert whisper == "note"


def test_handle_turn_whisper_failure_returns_none(monkeypatch):
    ws = FakeWebSocket()

    async def no_sleep(*a, **k):
        return
    monkeypatch.setattr(orchestrator.asyncio, "sleep", no_sleep)  # skip retry backoff
    monkeypatch.setattr(orchestrator, "get_relevant_memories", lambda uid, q: [])
    monkeypatch.setattr(orchestrator, "add_memory", lambda uid, t: None)
    monkeypatch.setattr(orchestrator, "conversation_agent_stream", lambda h, m: _chunks("ok"))

    def boom(h, m, r, p):
        raise Exception("503 overloaded")
    monkeypatch.setattr(orchestrator, "whisper_agent", boom)

    full_reply, whisper = asyncio.run(orchestrator.handle_turn(ws, [], "Hi", "demo-user"))

    assert full_reply == "ok"
    assert whisper is None   # so main.py won't persist a fallback note