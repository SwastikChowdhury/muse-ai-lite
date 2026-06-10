import io
from types import SimpleNamespace

from fastapi.testclient import TestClient
import main

client = TestClient(main.app)

def test_transcribe(monkeypatch):
    fake_groq = SimpleNamespace(
        audio=SimpleNamespace(
            transcriptions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(text="hello from voice")
            )
        )
    )
    monkeypatch.setattr(main, "groq_client", fake_groq)

    resp = client.post(
        "/transcribe",
        files={"audio": ("audio.webm", io.BytesIO(b"fake-bytes"), "audio/webm")},
    )
    assert resp.status_code == 200
    assert resp.json() == {"text": "hello from voice"}