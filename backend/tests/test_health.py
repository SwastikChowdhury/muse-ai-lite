from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_metrics_exposed():
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "# HELP" in resp.text