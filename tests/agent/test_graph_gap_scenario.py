"""Tests: Wave 1B graph-gap finder scenario on the read-only agent."""
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
    GRAPH_GAP_FINDER_SCENARIO,
    build_graph_gap_report,
    get_agent_scenario,
)
from app.agent.stop_controller import RunState
from app.agent.tool_registry import ToolRegistry
from app.models import QueryOptions
from app.prompts._impl import AGENT_GRAPH_GAP_FINDER_SYSTEM_PROMPT


class _NoArgs(ToolArgModel):
    pass


class _ConceptArgs(ToolArgModel):
    concept: str | None = None


class _MasteryArgs(ToolArgModel):
    topic: str | None = None


class _SearchArgs(ToolArgModel):
    query: str
    top_k: int = 4


def _scripted_decide_fn(decisions, captured_messages=None):
    queue = list(decisions)

    def _fn(messages):
        if captured_messages is not None:
            captured_messages.append(messages)
        if not queue:
            return DecisionResult(action="final_answer", final_answer="done"), None
        return queue.pop(0), None

    return _fn


def _graph_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="learner.get_profile",
            description="profile",
            when_to_use="start",
            args_schema=_NoArgs,
        ),
        lambda ctx, args: ToolResult.success({"level": "beginner"}),
    )
    reg.register(
        ToolSpec(
            name="graph.inspect",
            description="graph",
            when_to_use="inspect",
            args_schema=_ConceptArgs,
        ),
        lambda ctx, args: ToolResult.success(
            {
                "concept": "Bayes rule",
                "found": True,
                "prerequisites": ["conditional probability", "evidence"],
            }
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
            name="rag.search",
            description="search",
            when_to_use="grounding",
            args_schema=_SearchArgs,
        ),
        lambda ctx, args: ToolResult.success(
            {
                "chunks": [
                    {
                        "text": "Conditional probability is a prerequisite for Bayes rule.",
                        "file": "probability.md",
                    }
                ]
            },
            sources=[{"file": "probability.md"}],
        ),
    )
    return reg


def test_graph_gap_intent_routes_before_study_session():
    scenario = get_agent_scenario("найди пробелы в графе по правилу Байеса")

    assert scenario is GRAPH_GAP_FINDER_SCENARIO


def test_graph_gap_happy_path_uses_graph_progress_and_rag():
    captured_messages = []
    decisions = [
        DecisionResult(
            action="tool_call",
            tool_name="learner.get_profile",
            tool_args={},
        ),
        DecisionResult(
            action="tool_call",
            tool_name="graph.inspect",
            tool_args={"concept": "Bayes rule"},
        ),
        DecisionResult(
            action="tool_call",
            tool_name="progress.get_mastery",
            tool_args={"topic": "Bayes rule"},
        ),
        DecisionResult(
            action="tool_call",
            tool_name="rag.search",
            tool_args={"query": "conditional probability Bayes rule"},
        ),
        DecisionResult(
            action="final_answer",
            final_answer=(
                "## Карта пробелов\n- conditional probability\n\n"
                "## Цепочка prerequisites\nconditional probability → Bayes rule\n\n"
                "## Почему это мешает\nБез условия сложно понять обновление вероятности.\n\n"
                "## Рекомендуемый порядок\n1. conditional probability\n2. Bayes rule\n\n"
                "## Практическая проверка\n1. Что является условием?"
            ),
        ),
    ]
    runner = AgentRunner(
        _graph_registry(),
        run_state=RunState(max_steps=7),
        decide_fn=_scripted_decide_fn(decisions, captured_messages),
        system_prompt=GRAPH_GAP_FINDER_SCENARIO.system_prompt,
        finalize_answer=GRAPH_GAP_FINDER_SCENARIO.finalize_answer,
    )

    result = runner.run(
        question="найди graph gap по Bayes rule",
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
        "graph.inspect",
        "progress.get_mastery",
        "rag.search",
    ]
    assert captured_messages[0][0].content == AGENT_GRAPH_GAP_FINDER_SYSTEM_PROMPT
    for heading in (
        "## Карта пробелов",
        "## Цепочка prerequisites",
        "## Почему это мешает",
        "## Рекомендуемый порядок",
        "## Практическая проверка",
        "## Источники",
    ):
        assert heading in result.answer
    assert "[probability.md]" in result.answer


def test_graph_gap_fallback_is_structured_with_weak_data():
    report = build_graph_gap_report(answer="", sources=[], steps=[])

    assert report.weak_data is True
    assert "## Карта пробелов" in report.answer
    assert "## Практическая проверка" in report.answer
    assert "Недостаточно данных" in report.answer


def test_run_agent_flow_wires_graph_gap_scenario(monkeypatch):
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
        "найди пробелы в графе по теме",
        QueryOptions(query_mode="agent"),
        SimpleNamespace(trace={}),
    )

    assert captured["system_prompt"] == AGENT_GRAPH_GAP_FINDER_SYSTEM_PROMPT
    assert captured["finalize_answer"] is GRAPH_GAP_FINDER_SCENARIO.finalize_answer
    assert response["debug"]["answer_path"]["scenario_id"] == "graph_gap_finder"
