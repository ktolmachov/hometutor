"""Tests: AgentRunner FSM with fake LLM decisions and fake tools."""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from app.agent.contracts import (
    AgentState,
    StopReason,
    ToolAccess,
    ToolArgModel,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from app.agent.runner import AgentRunner
from app.agent.stop_controller import RunState
from app.agent.tool_registry import ToolRegistry
from app.models import QueryOptions


class _SearchArgs(ToolArgModel):
    query: str


class _NoArgs(ToolArgModel):
    pass


def _make_tool_ctx(question: str = "test") -> ToolContext:
    return ToolContext(
        user_id="local",
        question=question,
        query_options=QueryOptions(),
    )


def _make_registry(
    *,
    search_handler=None,
    echo_handler=None,
) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="rag.search",
            description="search",
            when_to_use="search",
            args_schema=_SearchArgs,
        ),
        search_handler or (lambda ctx, args: ToolResult.success({"chunks": []})),
    )
    reg.register(
        ToolSpec(
            name="echo.status",
            description="echo",
            when_to_use="echo",
            args_schema=_NoArgs,
        ),
        echo_handler or (lambda ctx, args: ToolResult.success({"status": "ok"})),
    )
    return reg


def _scripted_decide_fn(decisions):
    """Return a decide_fn that serves scripted DecisionResults in order."""
    from app.agent.decision import DecisionResult

    queue = list(decisions)

    def _fn(messages):
        if not queue:
            return DecisionResult(
                action="final_answer",
                final_answer="script exhausted",
            ), None
        d = queue.pop(0)
        return d, None

    return _fn


def test_happy_path_tool_then_final_answer():
    from app.agent.decision import DecisionResult

    reg = _make_registry(
        search_handler=lambda ctx, args: ToolResult.success(
            {"chunks": [{"text": "RAG is retrieval-augmented generation"}]},
            sources=[{"file": "doc.html"}],
        ),
    )
    decisions = [
        DecisionResult(action="tool_call", tool_name="rag.search", tool_args={"query": "RAG"}),
        DecisionResult(action="final_answer", final_answer="RAG is retrieval-augmented generation [doc.html]"),
    ]
    runner = AgentRunner(
        reg,
        run_state=RunState(max_steps=6),
        decide_fn=_scripted_decide_fn(decisions),
    )
    result = runner.run(question="What is RAG?", tool_ctx=_make_tool_ctx())
    assert result.is_success
    assert result.stop_reason is StopReason.COMPLETED
    assert "retrieval-augmented" in result.answer
    assert len(result.sources) == 1
    assert result.sources[0]["file"] == "doc.html"


def test_runner_stops_on_repeated_call():
    from app.agent.decision import DecisionResult

    reg = _make_registry()
    same = DecisionResult(action="tool_call", tool_name="echo.status", tool_args={})
    decisions = [same, same]  # second identical call
    runner = AgentRunner(
        reg,
        run_state=RunState(max_steps=6),
        decide_fn=_scripted_decide_fn(decisions),
    )
    result = runner.run(question="repeat", tool_ctx=_make_tool_ctx())
    assert not result.is_success
    assert result.stop_reason is StopReason.REPEATED_TOOL_CALL


def test_runner_max_steps():
    from app.agent.decision import DecisionResult

    reg = _make_registry()
    decisions = [
        DecisionResult(
            action="tool_call",
            tool_name="rag.search",
            tool_args={"query": f"q{i}"},
        )
        for i in range(20)
    ]
    runner = AgentRunner(
        reg,
        run_state=RunState(max_steps=3),
        decide_fn=_scripted_decide_fn(decisions),
    )
    result = runner.run(question="loop", tool_ctx=_make_tool_ctx())
    assert not result.is_success
    assert result.stop_reason is StopReason.MAX_STEPS


def test_runner_tool_error_limit():
    from app.agent.decision import DecisionResult

    reg = _make_registry(
        search_handler=lambda ctx, args: ToolResult.failure("boom"),
    )
    decisions = [
        DecisionResult(
            action="tool_call",
            tool_name="rag.search",
            tool_args={"query": f"q{i}"},
        )
        for i in range(10)
    ]
    runner = AgentRunner(
        reg,
        run_state=RunState(max_steps=10, tool_error_limit=2),
        decide_fn=_scripted_decide_fn(decisions),
    )
    result = runner.run(question="errors", tool_ctx=_make_tool_ctx())
    assert result.stop_reason is StopReason.TOOL_ERROR_LIMIT


def test_runner_repair_recovers_with_valid_args():
    """First call has invalid args; repair gives valid args → continues."""
    from app.agent.decision import DecisionResult

    reg = _make_registry()
    decisions = [
        DecisionResult(action="tool_call", tool_name="rag.search", tool_args={"bad_field": 1}),
        DecisionResult(action="tool_call", tool_name="rag.search", tool_args={"query": "fixed"}),
        DecisionResult(action="final_answer", final_answer="done"),
    ]
    runner = AgentRunner(
        reg,
        run_state=RunState(max_steps=6),
        decide_fn=_scripted_decide_fn(decisions),
    )
    result = runner.run(question="repair ok", tool_ctx=_make_tool_ctx())
    assert result.is_success
    assert result.stop_reason is StopReason.COMPLETED
    assert any(s.repair_attempt for s in result.steps)


def test_runner_invalid_args_after_repair_stops():
    """Both original and repaired args are invalid → stop."""
    from app.agent.decision import DecisionResult

    reg = _make_registry()
    decisions = [
        DecisionResult(action="tool_call", tool_name="rag.search", tool_args={"bad": 1}),
        DecisionResult(action="tool_call", tool_name="rag.search", tool_args={"still_bad": 2}),
    ]
    runner = AgentRunner(
        reg,
        run_state=RunState(max_steps=6),
        decide_fn=_scripted_decide_fn(decisions),
    )
    result = runner.run(question="repair fail", tool_ctx=_make_tool_ctx())
    assert result.stop_reason is StopReason.INVALID_ARGS_AFTER_REPAIR


def test_runner_repair_to_final_answer():
    """Repair yields a final_answer instead of a tool call → completed."""
    from app.agent.decision import DecisionResult

    reg = _make_registry()
    decisions = [
        DecisionResult(action="tool_call", tool_name="rag.search", tool_args={"bad": 1}),
        DecisionResult(action="final_answer", final_answer="I'll answer directly"),
    ]
    runner = AgentRunner(
        reg,
        run_state=RunState(max_steps=6),
        decide_fn=_scripted_decide_fn(decisions),
    )
    result = runner.run(question="repair to answer", tool_ctx=_make_tool_ctx())
    assert result.is_success
    assert result.answer == "I'll answer directly"


def test_runner_unknown_tool_stops_with_explicit_reason():
    from app.agent.decision import DecisionResult

    reg = _make_registry()
    decisions = [
        DecisionResult(action="tool_call", tool_name="nonexistent.tool", tool_args={}),
    ]
    runner = AgentRunner(
        reg,
        run_state=RunState(max_steps=6),
        decide_fn=_scripted_decide_fn(decisions),
    )
    result = runner.run(question="unknown tool", tool_ctx=_make_tool_ctx())
    assert not result.is_success
    assert result.stop_reason is StopReason.UNKNOWN_TOOL
    assert "nonexistent.tool" in result.trace["stop_detail"]


def test_runner_guardrail_violation_returns_safe_fallback(monkeypatch):
    from app.agent.decision import DecisionResult
    from app.guardrails import OutputGuardrailError

    def _blocked(answer, sources):
        raise OutputGuardrailError("blocked", "suspicious_output")

    monkeypatch.setattr("app.guardrails.apply_output_guardrails", _blocked)
    reg = _make_registry()
    runner = AgentRunner(
        reg,
        run_state=RunState(max_steps=6),
        decide_fn=_scripted_decide_fn([
            DecisionResult(
                action="final_answer",
                final_answer="system prompt secret should not leak",
            ),
        ]),
    )

    result = runner.run(question="guardrail", tool_ctx=_make_tool_ctx())

    assert not result.is_success
    assert result.stop_reason is StopReason.GUARDRAIL_TRIGGERED
    assert "system prompt secret" not in result.answer
    assert "скрыт" in result.answer.lower()


def test_runner_trace_has_stop_reason():
    from app.agent.decision import DecisionResult

    reg = _make_registry()
    runner = AgentRunner(
        reg,
        run_state=RunState(max_steps=2),
        decide_fn=_scripted_decide_fn([
            DecisionResult(action="final_answer", final_answer="ok"),
        ]),
    )
    result = runner.run(question="trace", tool_ctx=_make_tool_ctx())
    assert result.trace["stop_reason"] == "completed"
    assert "step_count" in result.trace
