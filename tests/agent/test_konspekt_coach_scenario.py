"""Tests: Wave 1C Living Konspekt Coach scenario on the read-only agent."""
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
    LIVING_KONSPEKT_COACH_SCENARIO,
    build_konspekt_coach_draft,
    get_agent_scenario,
)
from app.agent.stop_controller import RunState
from app.agent.tool_registry import ToolRegistry
from app.models import QueryOptions
from app.prompts._impl import AGENT_LIVING_KONSPEKT_COACH_SYSTEM_PROMPT


class _NoArgs(ToolArgModel):
    pass


class _SearchArgs(ToolArgModel):
    query: str
    top_k: int = 4


class _ConceptArgs(ToolArgModel):
    concept: str | None = None


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


def _konspekt_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="konspekt.inspect",
            description="konspekt",
            when_to_use="inspect",
            args_schema=_NoArgs,
        ),
        lambda ctx, args: ToolResult.success(
            {
                "total_rows": 2,
                "rows": [
                    {"id": "r1", "title": "Bayes rule", "source_count": 1},
                    {"id": "r2", "title": "Conditional probability", "source_count": 0},
                ],
            }
        ),
    )
    reg.register(
        ToolSpec(
            name="rag.search",
            description="search",
            when_to_use="grounding",
            args_schema=_SearchArgs,
        ),
        lambda ctx, args: ToolResult.success(
            {
                "chunks": [
                    {
                        "text": "Bayes notes need an example and a source citation.",
                        "file": "bayes_notes.md",
                    }
                ]
            },
            sources=[{"file": "bayes_notes.md"}],
        ),
    )
    reg.register(
        ToolSpec(
            name="graph.inspect",
            description="graph",
            when_to_use="relations",
            args_schema=_ConceptArgs,
        ),
        lambda ctx, args: ToolResult.success(
            {
                "concept": "Bayes rule",
                "found": True,
                "prerequisites": ["conditional probability"],
            }
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
            {"questions": [{"question": "What source supports the Bayes note?"}]}
        ),
    )
    reg.register(
        ToolSpec(
            name="cards.propose",
            description="cards",
            when_to_use="draft",
            args_schema=_CardsArgs,
        ),
        lambda ctx, args: ToolResult.success(
            {"candidates": [{"front": "What is missing from the Bayes note?"}]}
        ),
    )
    return reg


def test_konspekt_intent_routes_before_default_study_session():
    scenario = get_agent_scenario("проверь живой конспект и что добавить")

    assert scenario is LIVING_KONSPEKT_COACH_SCENARIO


def test_konspekt_coach_happy_path_uses_read_only_tools():
    captured_messages = []
    decisions = [
        DecisionResult(
            action="tool_call",
            tool_name="konspekt.inspect",
            tool_args={},
        ),
        DecisionResult(
            action="tool_call",
            tool_name="rag.search",
            tool_args={"query": "Bayes notes source citation"},
        ),
        DecisionResult(
            action="tool_call",
            tool_name="graph.inspect",
            tool_args={"concept": "Bayes rule"},
        ),
        DecisionResult(
            action="tool_call",
            tool_name="quiz.generate",
            tool_args={"topic": "Bayes rule"},
        ),
        DecisionResult(
            action="tool_call",
            tool_name="cards.propose",
            tool_args={"topic": "Bayes rule", "context": "Bayes notes"},
        ),
        DecisionResult(
            action="final_answer",
            final_answer=(
                "## Состояние конспекта\nЕсть два раздела.\n\n"
                "## Что добавить или уточнить\n- Добавить источник к conditional probability.\n\n"
                "## Что повторить\n- Bayes rule\n\n"
                "## Проверка понимания\n1. Какой источник подтверждает заметку?\n\n"
                "## Draft-карточки\n- Draft: What is missing from the Bayes note?\n\n"
                "## Следующий шаг\nДобавить один тезис вручную."
            ),
        ),
    ]
    runner = AgentRunner(
        _konspekt_registry(),
        run_state=RunState(max_steps=8),
        decide_fn=_scripted_decide_fn(decisions, captured_messages),
        system_prompt=LIVING_KONSPEKT_COACH_SCENARIO.system_prompt,
        finalize_answer=LIVING_KONSPEKT_COACH_SCENARIO.finalize_answer,
    )

    result = runner.run(
        question="проверь living konspekt",
        tool_ctx=ToolContext(
            user_id="user-1",
            session_id="session-1",
            question="q",
            query_options=QueryOptions(query_mode="agent"),
        ),
    )

    assert result.is_success
    assert result.trace["tool_calls"] == [
        "konspekt.inspect",
        "rag.search",
        "graph.inspect",
        "quiz.generate",
        "cards.propose",
    ]
    assert captured_messages[0][0].content == AGENT_LIVING_KONSPEKT_COACH_SYSTEM_PROMPT
    for heading in (
        "## Состояние конспекта",
        "## Что добавить или уточнить",
        "## Что повторить",
        "## Проверка понимания",
        "## Draft-карточки",
        "## Следующий шаг",
        "## Источники",
    ):
        assert heading in result.answer
    assert "[bayes_notes.md]" in result.answer
    assert "сохран" not in result.answer.lower()


def test_konspekt_empty_fallback_is_structured_and_weak():
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="konspekt.inspect",
            description="konspekt",
            when_to_use="inspect",
            args_schema=_NoArgs,
        ),
        lambda ctx, args: ToolResult.success({"total_rows": 0, "rows": []}),
    )
    decisions = [
        DecisionResult(
            action="tool_call",
            tool_name="konspekt.inspect",
            tool_args={},
        ),
        DecisionResult(action="final_answer", final_answer=""),
    ]
    runner = AgentRunner(
        reg,
        decide_fn=_scripted_decide_fn(decisions),
        system_prompt=LIVING_KONSPEKT_COACH_SCENARIO.system_prompt,
        finalize_answer=LIVING_KONSPEKT_COACH_SCENARIO.finalize_answer,
    )

    result = runner.run(
        question="конспект пуст?",
        tool_ctx=ToolContext(
            user_id="local",
            question="конспект пуст?",
            query_options=QueryOptions(query_mode="agent"),
        ),
    )

    assert result.is_success
    assert "## Состояние конспекта" in result.answer
    assert "пуст" in result.answer.lower()
    assert "автоматически" in result.answer.lower()

    draft = build_konspekt_coach_draft("", [], result.steps)
    assert draft.weak_data is True


def test_run_agent_flow_wires_konspekt_scenario(monkeypatch):
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
        "проверь конспект",
        QueryOptions(query_mode="agent"),
        SimpleNamespace(trace={}),
        persist_history=False,
    )

    assert captured["system_prompt"] == AGENT_LIVING_KONSPEKT_COACH_SYSTEM_PROMPT
    assert captured["finalize_answer"] is LIVING_KONSPEKT_COACH_SCENARIO.finalize_answer
    assert response["debug"]["answer_path"]["scenario_id"] == "living_konspekt_coach"
