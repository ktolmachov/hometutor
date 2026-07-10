"""Tests: query_service branch dispatches to agent flow correctly.

AGENT_ENABLED=false preserves existing main flow; AGENT_ENABLED=true +
query_mode=agent calls run_agent_flow. Other query_modes always use main flow.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models import QueryOptions
from app.query_service import answer_question


def _setup_branch_test(monkeypatch, *, agent_enabled: bool):
    """Patch query_service internals so we can observe the branch decision.

    Returns (main_flow_mock, agent_flow_mock) to assert call counts.
    """
    fake_ctx = MagicMock()
    fake_ctx.trace = {}
    monkeypatch.setattr(
        "app.query_service._prepare_query_context",
        lambda question, options: (fake_ctx, question, False, 0.0),
    )
    monkeypatch.setattr(
        "app.query_service.get_settings",
        lambda: SimpleNamespace(
            agent_enabled=agent_enabled,
            session_tape_full_events_enabled=False,
        ),
    )

    main_flow_mock = MagicMock(return_value={"answer": "MAIN", "sources": [], "debug": {}})
    monkeypatch.setattr("app.query_service._answer_question_main_flow", main_flow_mock)

    agent_flow_mock = MagicMock(return_value={"answer": "AGENT", "sources": [], "debug": {}})
    monkeypatch.setattr("app.agent.run_agent_flow", agent_flow_mock)

    # Bypass budget wrapper: call fn directly, wrap in BudgetResult.
    from app.latency_budget import BudgetMeta, BudgetResult

    def _passthrough_budget(surface, fn, **kwargs):
        return BudgetResult(result=fn(), meta=MagicMock(spec=BudgetMeta))

    monkeypatch.setattr("app.query_service.with_budget", _passthrough_budget)
    # Bypass finalization (session tape / answer events).
    monkeypatch.setattr(
        "app.query_service._finalize_budgeted_answer",
        lambda result, meta, options: result,
    )
    return main_flow_mock, agent_flow_mock


def test_agent_disabled_uses_main_flow_even_with_agent_mode(monkeypatch):
    main_flow, agent_flow = _setup_branch_test(monkeypatch, agent_enabled=False)
    answer_question("test question", QueryOptions(query_mode="agent"))
    main_flow.assert_called_once()
    agent_flow.assert_not_called()


def test_agent_enabled_with_agent_mode_calls_run_agent_flow(monkeypatch):
    main_flow, agent_flow = _setup_branch_test(monkeypatch, agent_enabled=True)
    result = answer_question("test question", QueryOptions(query_mode="agent"))
    main_flow.assert_not_called()
    agent_flow.assert_called_once()
    assert result["answer"] == "AGENT"


def test_agent_enabled_with_non_agent_mode_uses_main_flow(monkeypatch):
    main_flow, agent_flow = _setup_branch_test(monkeypatch, agent_enabled=True)
    result = answer_question("test question", QueryOptions(query_mode="qa"))
    main_flow.assert_called_once()
    agent_flow.assert_not_called()
    assert result["answer"] == "MAIN"


def test_agent_enabled_with_no_mode_uses_main_flow(monkeypatch):
    main_flow, agent_flow = _setup_branch_test(monkeypatch, agent_enabled=True)
    answer_question("test question", QueryOptions(query_mode=None))
    main_flow.assert_called_once()
    agent_flow.assert_not_called()
