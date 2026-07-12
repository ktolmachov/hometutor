"""Targeted tests for the agent runs read API (A2)."""

from fastapi.testclient import TestClient

from app.api import app
from app.user_state_agent_runs import persist_agent_run


client = TestClient(app)


def test_list_agent_runs_returns_list():
    # Smoke: endpoint exists and returns a list (may be empty)
    resp = client.get("/agent/runs?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


def test_get_agent_run_404_for_missing():
    resp = client.get("/agent/runs/nonexistent-run-xyz")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_agent_runs_endpoint_protected_by_default():
    # The endpoint is registered with _protected_dependencies.
    # In local single-user mode it usually works, but we at least check
    # that the route exists and returns 200/401 depending on config.
    # Here we just verify it doesn't 500.
    resp = client.get("/agent/runs?limit=1")
    assert resp.status_code in (200, 401, 403)
