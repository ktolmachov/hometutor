"""Tests: Wave 2 compact persistence for AI Agent runs."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import config, user_state_db
from app.agent.contracts import (
    AgentRunResult,
    AgentState,
    AgentStep,
    StopReason,
    ToolResult,
)
from app.auth_context import reset_current_user_id, set_current_user_id
from app.models import QueryOptions
from app.user_state_agent_runs import get_agent_run, persist_agent_run


@pytest.fixture()
def user_state_env(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_STATE_DB", str(tmp_path / "user_state.db"))
    config.reset_settings_cache()
    user_state_db.reset_schema_cache_for_tests()
    yield
    config.reset_settings_cache()
    user_state_db.reset_schema_cache_for_tests()


def _sample_result() -> AgentRunResult:
    return AgentRunResult(
        answer="## Диагностика\nКороткий ответ",
        sources=[{"file": "lesson.md"}],
        steps=[
            AgentStep(
                step_index=1,
                state=AgentState.TOOL_CALL,
                tool_name="learner.get_profile",
                tool_args={"user_id": "must-not-store", "session_id": "s1"},
                tool_result=ToolResult.success(
                    {
                        "level": "beginner",
                        "notes": "x" * 900,
                        "token": "must-not-store",
                    }
                ),
            ),
            AgentStep(
                step_index=2,
                state=AgentState.TOOL_CALL,
                tool_name="rag.search",
                tool_args={"query": "Bayes rule", "top_k": 4},
                tool_result=ToolResult.success(
                    {"chunks": [{"text": "Bayes " * 200, "file": "lesson.md"}]},
                    sources=[{"file": "lesson.md"}],
                ),
            ),
        ],
        stop_reason=StopReason.COMPLETED,
        state=AgentState.COMPLETED,
        trace={"tool_calls": ["learner.get_profile", "rag.search"], "step_count": 2},
    )


def test_persist_agent_run_reconstructs_compact_trace(user_state_env):
    persist_agent_run(
        run_id="run-1",
        scenario_id="study_session",
        question="Собери сессию по Bayes rule",
        answer_status="grounded",
        result=_sample_result(),
    )

    stored = get_agent_run("run-1")

    assert stored is not None
    assert stored["scenario_id"] == "study_session"
    assert stored["answer_status"] == "grounded"
    assert stored["tool_calls"] == ["learner.get_profile", "rag.search"]
    assert stored["summary"]["source_count"] == 1
    assert [step["tool_name"] for step in stored["steps"]] == [
        "learner.get_profile",
        "rag.search",
    ]
    assert stored["steps"][0]["tool_args"] == {}
    assert "must-not-store" not in str(stored)
    assert len(str(stored["steps"][1]["result_summary"])) < 1500


def test_agent_runs_follow_auth_user_state_isolation(user_state_env):
    token_a = set_current_user_id("user-a")
    try:
        persist_agent_run(
            run_id="run-user-a",
            scenario_id="study_session",
            question="q",
            answer_status="grounded",
            result=_sample_result(),
        )
    finally:
        reset_current_user_id(token_a)

    token_b = set_current_user_id("user-b")
    try:
        assert get_agent_run("run-user-a") is None
    finally:
        reset_current_user_id(token_b)

    token_a2 = set_current_user_id("user-a")
    try:
        assert get_agent_run("run-user-a") is not None
    finally:
        reset_current_user_id(token_a2)


def test_run_agent_flow_persists_run_id_in_debug_trace(user_state_env, monkeypatch):
    import app.agent as agent_module

    class _Runner:
        def __init__(self, registry, **kwargs):
            pass

        def run(self, *, question, tool_ctx):
            return _sample_result()

    monkeypatch.setattr(agent_module, "AgentRunner", _Runner)
    monkeypatch.setattr(agent_module, "_resolve_llm", lambda: object())
    ctx = SimpleNamespace(trace={})

    response = agent_module.run_agent_flow(
        "объясни Bayes rule",
        QueryOptions(query_mode="agent", session_id="s1"),
        ctx,
    )

    run_id = response["debug"]["agent_trace"]["run_id"]
    stored = get_agent_run(run_id)
    assert stored is not None
    assert stored["scenario_id"] == "study_session"
    assert stored["answer_status"] == "grounded"
    assert ctx.trace["agent"]["run_id"] == run_id


def test_agent_disabled_branch_does_not_persist(monkeypatch):
    from app.query_service import answer_question
    from tests.agent.test_query_service_branch import _setup_branch_test

    persist_mock = MagicMock()
    monkeypatch.setattr("app.user_state_agent_runs.persist_agent_run", persist_mock)
    _setup_branch_test(monkeypatch, agent_enabled=False)

    answer_question("test question", QueryOptions(query_mode="agent"))

    persist_mock.assert_not_called()
