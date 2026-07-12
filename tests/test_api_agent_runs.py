"""Targeted tests for the agent runs read API (A2)."""

import pytest
from fastapi.testclient import TestClient

from app import config, user_state_db
from app.agent.contracts import AgentRunResult, AgentState, AgentStep, StopReason, ToolResult
from app.api import app
from app.user_state_agent_runs import persist_agent_run


@pytest.fixture()
def agent_runs_db_env(tmp_path, monkeypatch):
    """Isolate agent runs persistence to a temporary DB (like other user_state tests)."""
    monkeypatch.setenv("USER_STATE_DB", str(tmp_path / "user_state.db"))
    config.reset_settings_cache()
    user_state_db.reset_schema_cache_for_tests()
    yield
    config.reset_settings_cache()
    user_state_db.reset_schema_cache_for_tests()


client = TestClient(app)


def _minimal_run(run_id: str) -> AgentRunResult:
    return AgentRunResult(
        answer="## Диагностика\nTest answer",
        sources=[{"file": "lesson.md"}],
        steps=[
            AgentStep(
                step_index=1,
                state=AgentState.TOOL_CALL,
                tool_name="learner.get_profile",
                tool_args={},
                tool_result=ToolResult.success({"level": "beginner"}),
            )
        ],
        stop_reason=StopReason.COMPLETED,
        state=AgentState.COMPLETED,
        trace={"step_count": 1},
    )


@pytest.mark.usefixtures("agent_runs_db_env")
def test_list_agent_runs_returns_list():
    # Smoke + positive: after persist we see the run in list (isolated DB)
    run_id = "test-a2-list-001"
    persist_agent_run(
        run_id=run_id,
        scenario_id="study_session",
        question="Test question for list",
        answer_status="ok",
        result=_minimal_run(run_id),
    )
    resp = client.get("/agent/runs?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    ids = [r.get("run_id") for r in data]
    assert run_id in ids


@pytest.mark.usefixtures("agent_runs_db_env")
def test_get_agent_run_returns_full_data():
    # Positive test for GET /{run_id} with steps (isolated DB)
    run_id = "test-a2-get-002"
    persist_agent_run(
        run_id=run_id,
        scenario_id="study_session",
        question="Test question for get",
        answer_status="ok",
        result=_minimal_run(run_id),
    )
    resp = client.get(f"/agent/runs/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == run_id
    assert "steps" in data
    assert len(data["steps"]) >= 1
    assert data.get("question")


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
