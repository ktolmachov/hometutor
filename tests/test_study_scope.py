"""Unit tests for active course scope helpers."""

from __future__ import annotations

import streamlit as st

from app.ui import study_scope


def _empty_state() -> dict:
    return {}


def test_deactivate_saves_last_scope(monkeypatch):
    state = _empty_state()
    monkeypatch.setattr(st, "session_state", state)
    study_scope.activate_scope(
        folder_rel="ai-agents",
        title="Курс: ИИ Агенты",
        source_paths=["ai-agents/lecture1.md"],
    )

    study_scope.deactivate_scope()

    assert study_scope.get_active_scope() is None
    last = study_scope.get_last_deactivated_scope()
    assert last is not None
    assert last["folder_rel"] == "ai-agents"
    assert last["title"] == "Курс: ИИ Агенты"
    assert last["source_paths"] == ["ai-agents/lecture1.md"]


def test_restore_scope_reactivates_last_deactivated(monkeypatch):
    state = _empty_state()
    monkeypatch.setattr(st, "session_state", state)
    study_scope.activate_scope(
        folder_rel="ai-agents",
        title="Курс: ИИ Агенты",
        source_paths=["ai-agents/lecture1.md"],
    )
    study_scope.deactivate_scope()

    restored = study_scope.restore_scope()

    assert restored is not None
    assert restored["folder_rel"] == "ai-agents"
    assert restored["active"] is True
    assert study_scope.get_active_scope() == restored
    assert study_scope.get_last_deactivated_scope() is None


def test_restore_scope_without_last_returns_none(monkeypatch):
    state = _empty_state()
    monkeypatch.setattr(st, "session_state", state)

    assert study_scope.restore_scope() is None
