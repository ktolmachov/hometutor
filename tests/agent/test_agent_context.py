"""Tests: agent harness injects authenticated user and session context."""
from __future__ import annotations

from types import SimpleNamespace

from app.agent import run_agent_flow
from app.agent.contracts import AgentRunResult, AgentState, StopReason, ToolResult
from app.agent.tools_learner import LearnerGetProfileArgs, _learner_get_profile_handler
from app.api_models import AskResponse
from app.auth_context import reset_current_user_id, set_current_user_id
from app.models import QueryOptions


class _CapturingRunner:
    def __init__(self) -> None:
        self.tool_ctx = None

    def run(self, *, question, tool_ctx):
        self.tool_ctx = tool_ctx
        return AgentRunResult(
            answer="ok",
            sources=[],
            steps=[],
            stop_reason=StopReason.COMPLETED,
            state=AgentState.COMPLETED,
            trace={},
        )


def test_run_agent_flow_uses_current_auth_user_id():
    runner = _CapturingRunner()
    token = set_current_user_id("user-123")
    try:
        run_agent_flow(
            "q",
            QueryOptions(query_mode="agent", session_id="s1"),
            SimpleNamespace(trace={}),
            runner=runner,
            persist_history=False,
        )
    finally:
        reset_current_user_id(token)

    assert runner.tool_ctx is not None
    assert runner.tool_ctx.user_id == "user-123"
    assert runner.tool_ctx.session_id == "s1"


def test_run_agent_flow_response_validates_against_public_ask_response():
    runner = _CapturingRunner()

    response = run_agent_flow(
        "q",
        QueryOptions(query_mode="agent", session_id="s1"),
        SimpleNamespace(trace={}),
        runner=runner,
        persist_history=False,
    )

    parsed = AskResponse.model_validate(response)
    assert parsed.answer_status == "grounded"
    assert response["debug"]["agent_trace"]["run_id"]


def test_learner_profile_tool_passes_user_and_session(monkeypatch):
    captured = {}

    class _Profile:
        def model_dump(self, mode):
            captured["mode"] = mode
            return {"ok": True}

    def _profile(user_id=None, *, session_id=None):
        captured["user_id"] = user_id
        captured["session_id"] = session_id
        return _Profile()

    monkeypatch.setattr(
        "app.learner_model_service.get_personalized_learner_profile",
        _profile,
    )
    ctx = SimpleNamespace(user_id="user-42", session_id="session-7")

    result = _learner_get_profile_handler(ctx, LearnerGetProfileArgs())

    assert isinstance(result, ToolResult)
    assert result.ok
    assert captured == {
        "user_id": "user-42",
        "session_id": "session-7",
        "mode": "json",
    }
