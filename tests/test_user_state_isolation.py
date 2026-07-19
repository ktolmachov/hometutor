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

    def test_pivot_without_active_graph_keeps_all(self) -> None:
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
            if pivot is not None and not pivot.empty:
                index_concepts = {str(c).strip().lower() for c in pivot.index}
                assert "topicb" in index_concepts, "Without graph, all concepts pass through"
                assert "global" in index_concepts, "global should remain without graph"


class TestWeeklyNarrativeWeakConcepts:
    """Weekly narrative uses graph-scoped weak concepts."""

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
