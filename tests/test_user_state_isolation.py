"""Pytest guard tests for user-state isolation from production DB.

Verifies that ``tests/conftest.py`` isolation (HOME_RAG_DATA_DIR → temp)
and the ``PYTEST_CURRENT_TEST`` guard in ``app/user_state_db._resolve_state_db_path``
work correctly.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.user_state_db import _resolve_state_db_path, reset_schema_cache_for_tests


class TestPytestGuardRedirectsToTemp:
    """``_resolve_state_db_path`` passes under pytest when isolation is active."""

    @pytest.fixture(autouse=True)
    def _ensure_isolation(self) -> None:
        assert "PYTEST_CURRENT_TEST" in os.environ, (
            "PYTEST_CURRENT_TEST must be set during pytest runs"
        )

    def test_resolve_not_under_production_data(self) -> None:
        prod_data = (Path(__file__).resolve().parent.parent / "data").resolve()
        path = Path(_resolve_state_db_path()).resolve()
        try:
            path.relative_to(prod_data)
            pytest.fail(f"DB path {path} must not be under production data dir {prod_data}")
        except ValueError:
            pass

    def test_guard_raises_on_production_path(self, monkeypatch) -> None:
        """If conftest isolation fails, the guard raises RuntimeError."""
        data_root = (Path(__file__).resolve().parent.parent / "data").resolve()
        prod_db = str(data_root / "user_state.db")

        with patch("app.user_state_db.get_settings") as mock_settings:
            mock_settings.return_value.user_state_db = prod_db
            with pytest.raises(RuntimeError, match="production data dir"):
                _resolve_state_db_path()

    def test_guard_raises_on_production_per_user_path(self, monkeypatch) -> None:
        """Guard fires even when per-user path branch is taken (was a bypass)."""
        data_root = (Path(__file__).resolve().parent.parent / "data").resolve()
        prod_db = str(data_root / "user_state.db")

        with patch("app.user_state_db.get_settings") as mock_settings, \
             patch("app.user_state_db.get_current_user_id", return_value="test-user"):
            mock_settings.return_value.user_state_db = prod_db
            with pytest.raises(RuntimeError, match="production data dir"):
                _resolve_state_db_path()

    def test_config_isolation_data_dir_is_temp(self) -> None:
        from app.config import get_settings

        s = get_settings()
        db_path = Path(s.user_state_db).resolve()
        prod_data = (Path(__file__).resolve().parent.parent / "data").resolve()
        try:
            db_path.relative_to(prod_data)
            pytest.fail(f"Settings user_state_db must not be under production: {db_path}")
        except ValueError:
            pass


class TestUserStateDBIsolation:
    """Test session runs against isolated DB, not production DB."""

    def test_write_goes_to_temp_not_production(self) -> None:
        from app.user_state_core import set_kv, get_kv

        key = f"test_isolation_{os.environ.get('PYTEST_CURRENT_TEST', '')[:20]}"
        set_kv(key, "isolation_check")
        result = get_kv(key)
        assert result == "isolation_check"

        db_path = Path(_resolve_state_db_path()).resolve()
        assert db_path.exists(), f"DB was not created at {db_path}"

        prod_data = (Path(__file__).resolve().parent.parent / "data").resolve()
        try:
            db_path.relative_to(prod_data)
            pytest.fail(f"Session DB must be temp, got: {db_path}")
        except ValueError:
            pass

    def test_schema_cache_reset_works(self) -> None:
        reset_schema_cache_for_tests()


class TestEmotionalHeatmapFilter:
    """Heatmap pivot filters ghost concepts via active knowledge graph."""

    def test_pivot_filters_non_graph_concepts(self) -> None:
        from app.learner_model_service import (
            EMOTIONAL_HEATMAP_KV_KEY,
            get_emotional_heatmap_pivot,
        )
        from app.user_state_core import set_kv
        from unittest.mock import MagicMock, patch

        rows = [
            {"date": "2026-07-18", "concept": "TopicB", "emotional_score": 0.5, "state": "neutral"},
            {"date": "2026-07-18", "concept": "TopicA", "emotional_score": 0.3, "state": "bored"},
            {"date": "2026-07-18", "concept": "real-concept", "emotional_score": 0.7, "state": "engaged"},
            {"date": "2026-07-18", "concept": "global", "emotional_score": 0.6, "state": "neutral"},
        ]
        set_kv(EMOTIONAL_HEATMAP_KV_KEY, json.dumps(rows, ensure_ascii=False))

        fake_kg = MagicMock()
        fake_kg.get_concepts.return_value = {
            "real-concept": {"label": "Real Concept"},
        }
        with patch("app.learner_model_service.get_active_knowledge_graph", return_value=fake_kg):
            pivot = get_emotional_heatmap_pivot(last_days=30)
            assert pivot is not None and not pivot.empty, "pivot should not be empty"
            index_concepts = {str(c).strip().lower() for c in pivot.index}
            assert "topica" not in index_concepts, f"Fixture concepts leaked: {index_concepts}"
            assert "topicb" not in index_concepts, f"Fixture concepts leaked: {index_concepts}"
            assert "real-concept" in index_concepts, f"Valid concept missing: {index_concepts}"
            assert "global" not in index_concepts, (
                f"'global' merged into 'общий фон': {index_concepts}"
            )
            assert "общий фон" in index_concepts, (
                f"'общий фон' aggregate row missing: {index_concepts}"
            )

    def test_pivot_without_active_graph_returns_none(self) -> None:
        """Graph error → return None, don't leak fixture concepts."""
        from app.learner_model_service import (
            EMOTIONAL_HEATMAP_KV_KEY,
            get_emotional_heatmap_pivot,
        )
        from app.user_state_core import set_kv
        from unittest.mock import patch

        rows = [
            {"date": "2026-07-18", "concept": "TopicB", "emotional_score": 0.5, "state": "neutral"},
            {"date": "2026-07-18", "concept": "global", "emotional_score": 0.6, "state": "neutral"},
        ]
        set_kv(EMOTIONAL_HEATMAP_KV_KEY, json.dumps(rows, ensure_ascii=False))

        with patch("app.learner_model_service.get_active_knowledge_graph", side_effect=Exception("no graph")):
            pivot = get_emotional_heatmap_pivot(last_days=30)
            assert pivot is None, "Graph error → must return None, not leak ghosts"


class TestWeeklyNarrativeWeakConcepts:
    """Weekly narrative uses graph-scoped weak concepts; never leaks raw on error."""

    def test_signals_use_weak_concepts_for_kg(self) -> None:
        from app.ssr_weekly_narrative import _collect_production_signals

        signals = _collect_production_signals(now_utc=None)
        assert signals is not None
        for w in signals.weak_concepts:
            assert w not in ("TopicB", "TopicA", "e2e_topic", "topic_x"), (
                f"Fixture concept leaked into narrative: {w}"
            )


class TestConfigSingletonReset:
    """``pytest_configure`` hook resets the Settings singleton."""

    def test_settings_rebuilt_after_hook(self) -> None:
        from app.config import get_settings

        s1 = get_settings()
        assert s1 is not None
        db = Path(s1.user_state_db).resolve()
        prod_data = (Path(__file__).resolve().parent.parent / "data").resolve()
        try:
            db.relative_to(prod_data)
            pytest.fail(f"Settings not isolated: {db}")
        except ValueError:
            pass


class TestNarrativeGraphErrorFallback:
    """Narrative returns empty weak-concepts on graph error, never raw get_weak_concepts()."""

    def test_graph_error_returns_empty_weak(self) -> None:
        from app.ssr_weekly_narrative import _collect_production_signals
        from unittest.mock import patch

        with patch("app.ssr_weekly_narrative.get_active_knowledge_graph", side_effect=Exception("graph down")):
            signals = _collect_production_signals(now_utc=None)
            assert signals is not None
            assert signals.weak_concepts == (), (
                f"Graph error must yield empty tuple, got: {signals.weak_concepts}"
            )


class TestCleanProgressGhosts:
    """Fixture matcher and ghost snapshot logic — destructive script safety."""

    def test_is_fixture_concept_exact_matches(self) -> None:
        from scripts.clean_progress_ghosts import _is_fixture_concept

        assert _is_fixture_concept("topic_x")
        assert _is_fixture_concept("TopicB")
        assert _is_fixture_concept("e2e_topic")
        assert _is_fixture_concept("legacytopic")
        assert _is_fixture_concept("t")

    def test_is_fixture_concept_false_positives_are_safe(self) -> None:
        from scripts.clean_progress_ghosts import _is_fixture_concept

        assert not _is_fixture_concept("attention"), "'t' is exact-match only"
        assert not _is_fixture_concept("token"), "'t' is exact-match only"
        assert not _is_fixture_concept("binding"), "'bind'/'binda'/'bindb' are exact-match only"
        assert not _is_fixture_concept("statistical_test_power"), "'test_' is prefix, not substring"
        assert not _is_fixture_concept("pretest_sensitivity"), "'test_' is prefix, not substring"
        assert not _is_fixture_concept("global"), "global is not a fixture"
        assert not _is_fixture_concept("общая"), "общая is not a fixture"
        assert not _is_fixture_concept("real-concept"), "real concept should not match"

    def test_is_fixture_concept_exact_bind_matches(self) -> None:
        from scripts.clean_progress_ghosts import _is_fixture_concept

        assert _is_fixture_concept("BindA")
        assert _is_fixture_concept("bindb")

    def test_is_fixture_concept_prefix_matches(self) -> None:
        from scripts.clean_progress_ghosts import _is_fixture_concept

        assert _is_fixture_concept("test_xxx")
        assert _is_fixture_concept("fixture_something")
        assert not _is_fixture_concept("some_fixture_dangling"), "'fixture_' is prefix, not substring"

    def test_collect_ghost_snapshot_dry_run(self, tmp_path: Path) -> None:
        import sqlite3
        from scripts.clean_progress_ghosts import collect_ghost_snapshot, _GHOST_TABLES

        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        for table in _GHOST_TABLES:
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (concept TEXT)")
        conn.execute("INSERT INTO quiz_mastery VALUES ('real-concept')")
        conn.execute("INSERT INTO quiz_mastery VALUES ('topic_x')")
        conn.execute("INSERT INTO quiz_mastery VALUES ('attention')")
        conn.execute("INSERT INTO spaced_repetition VALUES ('TopicB')")
        conn.execute("INSERT INTO quiz_results VALUES ('binding')")
        conn.execute("INSERT INTO quiz_results VALUES ('BindA')")
        conn.execute("CREATE TABLE IF NOT EXISTS app_kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
        conn.execute(
            "INSERT INTO app_kv VALUES ('emotional_heatmap_json', ?, '')",
            (json.dumps([
                {"concept": "TopicA", "date": "2026-07-18", "emotional_score": 0.5},
                {"concept": "real-concept", "date": "2026-07-18", "emotional_score": 0.7},
                {"concept": "attention", "date": "2026-07-18", "emotional_score": 0.6},
            ]),)
        )
        conn.commit()
        conn.close()

        active_ids = {"real-concept", "another-concept"}
        snapshot = collect_ghost_snapshot(db, active_ids)

        quiz_ghosts = {str(r.get("concept")) for r in snapshot.get("quiz_mastery", [])}
        assert "topic_x" in quiz_ghosts
        assert "real-concept" not in quiz_ghosts, "valid concept must not be a ghost"
        assert "attention" not in quiz_ghosts, "'attention' must not match fixture patterns"

        sr_ghosts = {str(r.get("concept")) for r in snapshot.get("spaced_repetition", [])}
        assert "TopicB" in sr_ghosts

        qr_ghosts = {str(r.get("concept")) for r in snapshot.get("quiz_results", [])}
        assert "binding" not in qr_ghosts, "'binding' must be false-negative safe"
        assert "BindA" in qr_ghosts, "'BindA' is an exact fixture match"

        heatmap = snapshot.get("app_kv_emotional_heatmap", [])
        hm_concepts = {str(e.get("concept")) for e in heatmap}
        assert "TopicA" in hm_concepts
        assert "real-concept" not in hm_concepts
        assert "attention" not in hm_concepts, "attention must not be flagged as ghost"

    def test_global_not_in_fixture_list(self) -> None:
        from scripts.clean_progress_ghosts import _is_fixture_concept

        assert not _is_fixture_concept("global")
        assert not _is_fixture_concept("Global")
        assert not _is_fixture_concept("общая")
        assert not _is_fixture_concept("общий фон")
