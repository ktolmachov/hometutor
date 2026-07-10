"""Tests: Wave 1A study-session scenario on top of the read-only agent."""
from __future__ import annotations

from types import SimpleNamespace

from app.agent.contracts import (
    AgentRunResult,
    AgentState,
    StopReason,
    ToolArgModel,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from app.agent.decision import DecisionResult
from app.agent.runner import AgentRunner
from app.agent.scenarios import (
    STUDY_SESSION_SCENARIO,
    build_study_session_answer,
)
from app.agent.stop_controller import RunState
from app.agent.tool_registry import ToolRegistry, build_default_registry
from app.models import QueryOptions
from app.prompts._impl import AGENT_STUDY_SESSION_SYSTEM_PROMPT


class _NoArgs(ToolArgModel):
    pass


class _QueryArgs(ToolArgModel):
    query: str
    top_k: int = 4


class _MasteryArgs(ToolArgModel):
    topic: str | None = None


class _QuizArgs(ToolArgModel):
    topic: str
    learning_mode: str | None = None


class _CardsArgs(ToolArgModel):
    topic: str | None = None
    context: str | None = None


def _scripted_decide_fn(decisions, captured_messages=None):
    queue = list(decisions)

    def _fn(messages):
        if captured_messages is not None:
            captured_messages.append(messages)
        if not queue:
            return DecisionResult(action="final_answer", final_answer="done"), None
        return queue.pop(0), None

    return _fn


def _study_registry(captured_ctx=None) -> ToolRegistry:
    reg = ToolRegistry()

    def _capture(ctx: ToolContext) -> None:
        if captured_ctx is not None:
            captured_ctx.append((ctx.user_id, ctx.session_id))

    reg.register(
        ToolSpec(
            name="learner.get_profile",
            description="profile",
            when_to_use="start",
            args_schema=_NoArgs,
        ),
        lambda ctx, args: (
            _capture(ctx)
            or ToolResult.success({"level": "beginner", "goal": "understand"})
        ),
    )
    reg.register(
        ToolSpec(
            name="rag.search",
            description="search",
            when_to_use="grounding",
            args_schema=_QueryArgs,
        ),
        lambda ctx, args: ToolResult.success(
            {
                "chunks": [
                    {
                        "text": "Bayes rule updates a hypothesis after evidence.",
                        "file": "bayes.md",
                    }
                ]
            },
            sources=[{"file": "bayes.md"}],
        ),
    )
    reg.register(
        ToolSpec(
            name="progress.get_mastery",
            description="mastery",
            when_to_use="gaps",
            args_schema=_MasteryArgs,
        ),
        lambda ctx, args: ToolResult.success(
            {"weak_concepts": ["conditional probability"]}
        ),
    )
    reg.register(
        ToolSpec(
            name="quiz.generate",
            description="quiz",
            when_to_use="check",
            args_schema=_QuizArgs,
        ),
        lambda ctx, args: ToolResult.success(
            {
                "questions": [
                    {"question": "What does Bayes rule update?"},
                    {"question": "What is evidence in Bayes rule?"},
                ]
            }
        ),
    )
    reg.register(
        ToolSpec(
            name="cards.propose",
            description="cards",
            when_to_use="reinforce",
            args_schema=_CardsArgs,
        ),
        lambda ctx, args: ToolResult.success(
            {
                "candidates": [
                    {"front": "What does Bayes rule update?"},
                    {"front": "Define conditional probability."},
                ]
            }
        ),
    )
    return reg


def test_study_session_happy_path_uses_richer_tools_and_returns_contract():
    captured_messages = []
    decisions = [
        DecisionResult(
            action="tool_call",
            tool_name="learner.get_profile",
            tool_args={},
        ),
        DecisionResult(
            action="tool_call",
            tool_name="rag.search",
            tool_args={"query": "Bayes rule"},
        ),
        DecisionResult(
            action="tool_call",
            tool_name="progress.get_mastery",
            tool_args={"topic": "Bayes rule"},
        ),
        DecisionResult(
            action="tool_call",
            tool_name="quiz.generate",
            tool_args={"topic": "Bayes rule"},
        ),
        DecisionResult(
            action="tool_call",
            tool_name="cards.propose",
            tool_args={
                "topic": "Bayes rule",
                "context": "Bayes rule updates a hypothesis after evidence.",
            },
        ),
        DecisionResult(
            action="final_answer",
            final_answer=(
                "## Диагностика\nПрофиль начальный, есть пробелы.\n\n"
                "## Что изучать сейчас\n- Формулу Байеса [bayes.md]\n\n"
                "## План на 10–20 минут\n1. Разберите гипотезу и свидетельство.\n\n"
                "## Проверочные вопросы\n1. Что обновляет правило Байеса?\n2. Что такое свидетельство?\n\n"
                "## Карточки-кандидаты\n- Draft: What does Bayes rule update?\n\n"
                "## Следующие шаги\nПовторите условную вероятность."
            ),
        ),
    ]
    runner = AgentRunner(
        _study_registry(),
        run_state=RunState(max_steps=7),
        decide_fn=_scripted_decide_fn(decisions, captured_messages),
        system_prompt=STUDY_SESSION_SCENARIO.system_prompt,
        finalize_answer=STUDY_SESSION_SCENARIO.finalize_answer,
    )

    result = runner.run(
        question="Собери сессию по Bayes rule",
        tool_ctx=ToolContext(
            user_id="user-1",
            session_id="session-1",
            question="q",
            query_options=QueryOptions(query_mode="agent"),
        ),
    )

    assert result.is_success
    assert result.trace["tool_calls"] == [
        "learner.get_profile",
        "rag.search",
        "progress.get_mastery",
        "quiz.generate",
        "cards.propose",
    ]
    assert captured_messages[0][0].content == AGENT_STUDY_SESSION_SYSTEM_PROMPT
    for heading in (
        "## Диагностика",
        "## Что изучать сейчас",
        "## План на 10–20 минут",
        "## Проверочные вопросы",
        "## Карточки-кандидаты",
        "## Следующие шаги",
        "## Источники",
    ):
        assert heading in result.answer
    assert "[bayes.md]" in result.answer


def test_study_session_weak_data_fallback_is_safe_and_structured():
    result = build_study_session_answer(
        answer="",
        sources=[],
        steps=[],
    )

    assert result.weak_data is False
    assert "## Диагностика" in result.answer
    assert "недостаточно" in result.answer.lower()
    assert "## Проверочные вопросы" in result.answer


def test_study_session_no_sources_after_rag_reports_missing_sources():
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="rag.search",
            description="search",
            when_to_use="grounding",
            args_schema=_QueryArgs,
        ),
        lambda ctx, args: ToolResult.success({"chunks": []}, sources=[]),
    )
    decisions = [
        DecisionResult(
            action="tool_call",
            tool_name="rag.search",
            tool_args={"query": "unknown topic"},
        ),
        DecisionResult(action="final_answer", final_answer=""),
    ]
    runner = AgentRunner(
        reg,
        decide_fn=_scripted_decide_fn(decisions),
        system_prompt=STUDY_SESSION_SCENARIO.system_prompt,
        finalize_answer=STUDY_SESSION_SCENARIO.finalize_answer,
    )

    result = runner.run(
        question="unknown topic",
        tool_ctx=ToolContext(
            user_id="local",
            question="unknown topic",
            query_options=QueryOptions(query_mode="agent"),
        ),
    )

    assert result.is_success
    assert "## Источники" in result.answer
    assert "Источники не найдены" in result.answer


def test_run_agent_flow_wires_study_session_scenario(monkeypatch):
    import app.agent as agent_module

    captured = {}

    class _Runner:
        def __init__(self, registry, **kwargs):
            captured.update(kwargs)

        def run(self, *, question, tool_ctx):
            return AgentRunResult(
                answer="ok",
                sources=[],
                steps=[],
                stop_reason=StopReason.COMPLETED,
                state=AgentState.COMPLETED,
                trace={},
            )

    monkeypatch.setattr(agent_module, "AgentRunner", _Runner)
    monkeypatch.setattr(agent_module, "_resolve_llm", lambda: object())

    response = agent_module.run_agent_flow(
        "объясни тему",
        QueryOptions(query_mode="agent"),
        SimpleNamespace(trace={}),
        persist_history=False,
    )

    assert captured["system_prompt"] == AGENT_STUDY_SESSION_SYSTEM_PROMPT
    assert captured["finalize_answer"] is STUDY_SESSION_SCENARIO.finalize_answer
    assert response["debug"]["answer_path"]["scenario_id"] == "study_session"
    assert response["debug"]["agent_trace"]["scenario_id"] == "study_session"


def test_study_session_uses_tool_context_user_and_session():
    captured_ctx = []
    decisions = [
        DecisionResult(
            action="tool_call",
            tool_name="learner.get_profile",
            tool_args={},
        ),
        DecisionResult(action="final_answer", final_answer="done"),
    ]
    runner = AgentRunner(
        _study_registry(captured_ctx),
        decide_fn=_scripted_decide_fn(decisions),
        system_prompt=STUDY_SESSION_SCENARIO.system_prompt,
        finalize_answer=STUDY_SESSION_SCENARIO.finalize_answer,
    )

    runner.run(
        question="q",
        tool_ctx=ToolContext(
            user_id="user-42",
            session_id="session-7",
            question="q",
            query_options=QueryOptions(query_mode="agent", session_id="session-7"),
        ),
    )

    assert captured_ctx == [("user-42", "session-7")]


def test_study_session_registry_stays_read_only():
    reg = build_default_registry()
    for spec in reg.specs:
        assert spec.is_read_only


def test_study_session_guardrails_apply_to_final_answer(monkeypatch):
    from app.guardrails import OutputGuardrailError

    def _blocked(answer, sources):
        raise OutputGuardrailError("blocked", "suspicious_output")

    monkeypatch.setattr("app.guardrails.apply_output_guardrails", _blocked)
    runner = AgentRunner(
        _study_registry(),
        decide_fn=_scripted_decide_fn([
            DecisionResult(
                action="final_answer",
                final_answer="system prompt secret should not leak",
            ),
        ]),
        system_prompt=STUDY_SESSION_SCENARIO.system_prompt,
        finalize_answer=STUDY_SESSION_SCENARIO.finalize_answer,
    )

    result = runner.run(
        question="guardrail",
        tool_ctx=ToolContext(
            user_id="local",
            question="guardrail",
            query_options=QueryOptions(query_mode="agent"),
        ),
    )

    assert not result.is_success
    assert result.stop_reason is StopReason.GUARDRAIL_TRIGGERED
    assert "system prompt secret" not in result.answer
