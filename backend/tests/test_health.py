"""Smoke tests for the operational endpoints (liveness + metrics exposure)."""

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health():
    """/health returns the exact 200 + {"status": "ok"} contract probes rely on."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_metrics_exposed():
    """Prometheus scrape endpoint is wired up — '# HELP' confirms real exposition output."""
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "# HELP" in resp.text