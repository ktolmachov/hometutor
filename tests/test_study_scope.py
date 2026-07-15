"""Unit tests for active course scope helpers."""

from __future__ import annotations

import json

import pytest
import streamlit as st

from app.ui import study_scope


def _empty_state() -> dict:
    return {}


@pytest.fixture(autouse=True)
def _isolate_ui_preferences_kv(monkeypatch):
    """activate_scope() now also nudges the UI level (ensure_min_ui_level).

    app.ui_preferences binds get_kv/set_kv at import time (not a lazy/local
    import), so patching app.user_state_core.get_kv/set_kv alone — the seam
    the rest of this file already uses — would not stop that nudge from
    hitting the real data/user_state.db. Patch its own seam too, and pin
    _has_existing_activity so the default-level fallback is deterministic.
    """
    from app import ui_preferences

    store: dict[str, str] = {}
    monkeypatch.setattr(ui_preferences, "_read_raw_kv", lambda key, default=None: store.get(key, default))
    monkeypatch.setattr(ui_preferences, "_write_raw_kv", lambda key, value: store.__setitem__(key, value))
    monkeypatch.setattr(ui_preferences, "_ensure_auth_context", lambda: None)
    monkeypatch.setattr(ui_preferences, "_maybe_migrate_global_ui_prefs", lambda: None)
    monkeypatch.setattr(ui_preferences, "_has_existing_activity", lambda: False)
    return store


def test_deactivate_saves_last_scope(monkeypatch):
    state = _empty_state()
    monkeypatch.setattr(st, "session_state", state)
    study_scope.activate_scope(
        folder_rel="ai-agents",
        title="Курс: ИИ Агенты",
        source_paths=["ai-agents/lecture1.md"],
        state=state,
    )

    study_scope.deactivate_scope(state=state)

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
        state=state,
    )
    study_scope.deactivate_scope(state=state)

    restored = study_scope.restore_scope(state=state)

    assert restored is not None
    assert restored["folder_rel"] == "ai-agents"
    assert restored["active"] is True
    assert study_scope.get_active_scope() == restored
    assert study_scope.get_last_deactivated_scope() is None


def test_restore_scope_without_last_returns_none(monkeypatch):
    state = _empty_state()
    monkeypatch.setattr(st, "session_state", state)

    assert study_scope.restore_scope(state=state) is None


class TestScopeAppKvPersistence:
    """Активный курс автосохраняется в app_kv и гидрируется при старте сессии.

    Персист гейтится ``state is None``: инжектированный dict (юнит-тесты) не пишет в БД.
    """

    def _capture_kv(self, monkeypatch):
        import app.user_state_core as user_state_core

        saved: dict = {}
        monkeypatch.setattr(user_state_core, "set_kv", lambda key, value: saved.__setitem__(key, value))
        monkeypatch.setattr(user_state_core, "get_kv", lambda key, default=None: saved.get(key, default))
        return saved

    def test_activate_with_injected_state_does_not_persist(self, monkeypatch):
        saved = self._capture_kv(monkeypatch)
        study_scope.activate_scope(folder_rel="ai-agents", title="Курс", state={})
        assert saved == {}

    def test_activate_persists_active_scope_to_kv(self, monkeypatch):
        saved = self._capture_kv(monkeypatch)
        monkeypatch.setattr(st, "session_state", {})
        study_scope.activate_scope(folder_rel="ai-agents", title="Курс: ИИ", source_paths=["ai-agents/a.md"])
        persisted = json.loads(saved["study_scope.active"])
        assert persisted["folder_rel"] == "ai-agents"
        assert persisted["title"] == "Курс: ИИ"
        assert persisted["active"] is True

    def test_deactivate_clears_active_and_persists_last_deactivated(self, monkeypatch):
        saved = self._capture_kv(monkeypatch)
        monkeypatch.setattr(st, "session_state", {})
        study_scope.activate_scope(folder_rel="ai-agents", title="Курс: ИИ", source_paths=["ai-agents/a.md"])
        study_scope.deactivate_scope()
        assert saved["study_scope.active"] == ""
        last = json.loads(saved["study_scope.last_deactivated"])
        assert last["folder_rel"] == "ai-agents"
        assert "active" not in last

    def test_restore_clears_last_deactivated_and_persists_active(self, monkeypatch):
        saved = self._capture_kv(monkeypatch)
        monkeypatch.setattr(st, "session_state", {})
        study_scope.activate_scope(folder_rel="ai-agents", title="Курс: ИИ")
        study_scope.deactivate_scope()
        study_scope.restore_scope()
        assert saved["study_scope.last_deactivated"] == ""
        active = json.loads(saved["study_scope.active"])
        assert active["folder_rel"] == "ai-agents"
        assert active["active"] is True


class TestRestoreScopeFromAppKv:
    """Восстановление активного курса из app_kv при старте UI-сессии."""

    def _kv_store(self, monkeypatch, payload):
        import app.user_state_core as user_state_core

        store = dict(payload)
        writes: list = []

        def fake_set(key, value):
            writes.append((key, value))
            store[key] = value

        monkeypatch.setattr(user_state_core, "get_kv", lambda key, default=None: store.get(key, default))
        monkeypatch.setattr(user_state_core, "set_kv", fake_set)
        return writes

    def test_hydrates_active_scope_when_folder_exists(self, monkeypatch):
        payload = {
            "study_scope.active": json.dumps(
                {
                    "folder_rel": "ai-agents",
                    "title": "Курс: ИИ",
                    "source_paths": [],
                    "id": "abc",
                    "created_at": "2024-01-01T00:00:00+00:00",
                }
            )
        }
        self._kv_store(monkeypatch, payload)
        monkeypatch.setattr(study_scope, "_scope_folder_exists", lambda fr: True)
        monkeypatch.setattr(st, "session_state", {})
        notice = study_scope.restore_scope_from_app_kv()
        assert notice is None
        active = study_scope.get_active_scope()
        assert active is not None
        assert active["folder_rel"] == "ai-agents"
        assert active["active"] is True

    def test_degrades_when_folder_missing(self, monkeypatch):
        payload = {
            "study_scope.active": json.dumps(
                {"folder_rel": "gone", "title": "Удалённый курс", "source_paths": []}
            )
        }
        writes = self._kv_store(monkeypatch, payload)
        monkeypatch.setattr(study_scope, "_scope_folder_exists", lambda fr: False)
        monkeypatch.setattr(st, "session_state", {})
        notice = study_scope.restore_scope_from_app_kv()
        assert notice is not None
        assert "Удалённый курс" in notice
        assert study_scope.get_active_scope() is None
        assert ("study_scope.active", "") in writes

    def test_idempotent_once_per_session(self, monkeypatch):
        import app.user_state_core as user_state_core

        calls: list = []
        monkeypatch.setattr(user_state_core, "get_kv", lambda key, default=None: calls.append(key) or None)
        monkeypatch.setattr(st, "session_state", {})
        study_scope.restore_scope_from_app_kv()
        study_scope.restore_scope_from_app_kv()
        assert calls.count("study_scope.active") == 1

    def test_does_not_overwrite_existing_active(self, monkeypatch):
        payload = {"study_scope.active": json.dumps({"folder_rel": "kv-scope"})}
        self._kv_store(monkeypatch, payload)
        monkeypatch.setattr(study_scope, "_scope_folder_exists", lambda fr: True)
        state = {study_scope.ACTIVE_SCOPE_KEY: {"folder_rel": "session-scope", "active": True}}
        monkeypatch.setattr(st, "session_state", state)
        study_scope.restore_scope_from_app_kv()
        assert study_scope.get_active_scope()["folder_rel"] == "session-scope"

    def test_hydrates_last_deactivated_for_restore_button(self, monkeypatch):
        payload = {
            "study_scope.last_deactivated": json.dumps(
                {"folder_rel": "old-course", "title": "Старый курс", "source_paths": []}
            )
        }
        self._kv_store(monkeypatch, payload)
        monkeypatch.setattr(st, "session_state", {})
        study_scope.restore_scope_from_app_kv()
        last = study_scope.get_last_deactivated_scope()
        assert last is not None
        assert last["folder_rel"] == "old-course"

    def test_injected_state_does_not_read_app_kv(self, monkeypatch):
        import app.user_state_core as user_state_core

        calls: list = []
        monkeypatch.setattr(user_state_core, "get_kv", lambda key, default=None: calls.append(key) or None)
        study_scope.restore_scope_from_app_kv(state={})
        assert calls == []


def test_folder_rel_from_paths_keeps_uploaded_course_pack_scope():
    assert (
        study_scope.folder_rel_from_paths(
            [
                "uploads/hometutor_101/README.md",
                "uploads/hometutor_101/lectures/urok_1.md",
                "uploads/hometutor_101/konspekts/urok_1.konspekt.md",
            ]
        )
        == "uploads/hometutor_101"
    )


class TestPromoteUiLevelForCourse:
    """Activating a course should reveal Course/Plan/Graph without a manual visit
    to the control panel (see app.ui_preferences.LEVEL_FULL)."""

    def test_activate_promotes_study_to_full(self, monkeypatch, _isolate_ui_preferences_kv):
        from app import ui_preferences

        monkeypatch.setattr(st, "session_state", {})
        _isolate_ui_preferences_kv[ui_preferences.UI_LEVEL_KEY] = ui_preferences.LEVEL_STUDY

        study_scope.activate_scope(folder_rel="ai-agents", title="Курс: ИИ")

        assert _isolate_ui_preferences_kv[ui_preferences.UI_LEVEL_KEY] == ui_preferences.LEVEL_FULL

    def test_activate_does_not_downgrade_diagnostic(self, monkeypatch, _isolate_ui_preferences_kv):
        from app import ui_preferences

        monkeypatch.setattr(st, "session_state", {})
        _isolate_ui_preferences_kv[ui_preferences.UI_LEVEL_KEY] = ui_preferences.LEVEL_DIAGNOSTIC

        study_scope.activate_scope(folder_rel="ai-agents", title="Курс: ИИ")

        assert _isolate_ui_preferences_kv[ui_preferences.UI_LEVEL_KEY] == ui_preferences.LEVEL_DIAGNOSTIC

    def test_activate_with_injected_state_does_not_promote(self, monkeypatch, _isolate_ui_preferences_kv):
        from app import ui_preferences

        _isolate_ui_preferences_kv[ui_preferences.UI_LEVEL_KEY] = ui_preferences.LEVEL_STUDY

        study_scope.activate_scope(folder_rel="ai-agents", title="Курс", state={})

        assert _isolate_ui_preferences_kv[ui_preferences.UI_LEVEL_KEY] == ui_preferences.LEVEL_STUDY


class TestMaybeAutoActivateDemoCourse:
    """First-run auto-activation of the built-in hometutor_101 course on HF Space
    / local demo runs (HOME_RAG_DATA_MODE=demo)."""

    def _kv_store(self, monkeypatch, payload=None):
        import app.user_state_core as user_state_core

        store = dict(payload or {})
        monkeypatch.setattr(user_state_core, "get_kv", lambda key, default=None: store.get(key, default))
        monkeypatch.setattr(user_state_core, "set_kv", lambda key, value: store.__setitem__(key, value))
        return store

    def test_activates_when_demo_mode_and_course_present(self, monkeypatch, tmp_path):
        monkeypatch.setattr(st, "session_state", {})
        store = self._kv_store(monkeypatch)
        monkeypatch.setattr("app.course_graduation.delight_data_mode_is_demo", lambda: True)
        course_dir = tmp_path / "hometutor_101"
        course_dir.mkdir()
        (course_dir / "README.md").write_text("demo course", encoding="utf-8")
        monkeypatch.setattr("app.demo_sandbox.builtin_demo_course_target_dir", lambda: course_dir)

        activated = study_scope.maybe_auto_activate_demo_course()

        assert activated is True
        active = study_scope.get_active_scope()
        assert active is not None
        assert active["folder_rel"] == "uploads/hometutor_101"
        assert store["study_scope.demo_course_autoactivated"] == "1"

    def test_skips_when_not_demo_mode(self, monkeypatch, tmp_path):
        monkeypatch.setattr(st, "session_state", {})
        self._kv_store(monkeypatch)
        monkeypatch.setattr("app.course_graduation.delight_data_mode_is_demo", lambda: False)

        assert study_scope.maybe_auto_activate_demo_course() is False
        assert study_scope.get_active_scope() is None

    def test_skips_when_already_fired(self, monkeypatch, tmp_path):
        monkeypatch.setattr(st, "session_state", {})
        self._kv_store(monkeypatch, {"study_scope.demo_course_autoactivated": "1"})
        monkeypatch.setattr("app.course_graduation.delight_data_mode_is_demo", lambda: True)

        assert study_scope.maybe_auto_activate_demo_course() is False
        assert study_scope.get_active_scope() is None

    def test_skips_when_learner_already_has_a_scope_choice(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            st,
            "session_state",
            {study_scope.ACTIVE_SCOPE_KEY: {"folder_rel": "other-course", "active": True}},
        )
        self._kv_store(monkeypatch)
        monkeypatch.setattr("app.course_graduation.delight_data_mode_is_demo", lambda: True)

        assert study_scope.maybe_auto_activate_demo_course() is False
        active = study_scope.get_active_scope()
        assert active["folder_rel"] == "other-course"

    def test_skips_when_course_folder_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(st, "session_state", {})
        self._kv_store(monkeypatch)
        monkeypatch.setattr("app.course_graduation.delight_data_mode_is_demo", lambda: True)
        monkeypatch.setattr(
            "app.demo_sandbox.builtin_demo_course_target_dir", lambda: tmp_path / "missing"
        )

        assert study_scope.maybe_auto_activate_demo_course() is False
        assert study_scope.get_active_scope() is None

    def test_injected_state_never_activates(self, monkeypatch, tmp_path):
        self._kv_store(monkeypatch)
        monkeypatch.setattr("app.course_graduation.delight_data_mode_is_demo", lambda: True)

        assert study_scope.maybe_auto_activate_demo_course(state={}) is False
