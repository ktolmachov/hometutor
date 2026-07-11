from app.learning_plan_adaptive import (
    get_primary_adaptive_daily_plan_block_from_plan,
    primary_learning_item_from_adaptive_daily_plan,
)
from app import telegram_notifications
import app.learning_plan_service as learning_plan_service


def test_primary_learning_item_prefers_explicit_adaptive_daily_primary_block() -> None:
    plan = {
        "date": "2026-07-11",
        "primary_block": {"type": "gap", "concept": "Производная"},
        "blocks": [{"type": "review", "concept": "Предел"}],
    }

    assert get_primary_adaptive_daily_plan_block_from_plan(plan) == plan["primary_block"]

    item = primary_learning_item_from_adaptive_daily_plan(plan)

    assert item is not None
    assert item["topic"] == "Производная"
    assert item["source"] == "adaptive_daily_plan"


def test_primary_learning_item_skips_auto_loop_until_fallback() -> None:
    plan = {
        "blocks": [
            {"type": "auto_loop", "concept": "Автопетля"},
            {"type": "new", "concept": "Интеграл"},
        ]
    }

    item = primary_learning_item_from_adaptive_daily_plan(plan)

    assert item is not None
    assert item["topic"] == "Интеграл"


def test_telegram_daily_topic_line_uses_adaptive_primary(monkeypatch) -> None:
    monkeypatch.setattr(
        learning_plan_service,
        "get_today_primary_learning_item",
        lambda: {"topic": "Матрицы", "source": "adaptive_daily_plan"},
    )

    assert telegram_notifications._daily_topic_line() == "Сегодня: Матрицы"


def test_telegram_daily_topic_line_returns_none_when_no_primary(monkeypatch) -> None:
    """A3: no fallback to old coach plan — returns None gracefully."""
    monkeypatch.setattr(learning_plan_service, "get_today_primary_learning_item", lambda: None)

    assert telegram_notifications._daily_topic_line() is None


# ── C1 state bridge: get_smart_resume checks learning_plan step ──

def _patch_smart_resume_deps(monkeypatch, *, learning_plan_resume):
    """Common dependency stubs so get_smart_resume() runs without real DB/graph."""
    monkeypatch.setattr("app.user_state.get_latest_learning_plan_resume", lambda: learning_plan_resume)

    class _FakeDash:
        @staticmethod
        def get_mastery_data():
            return {}

    class _FakeKG:
        @staticmethod
        def get_concepts():
            return {}

        @staticmethod
        def topological_sort(ids):
            return ids

        @staticmethod
        def get_next_best_actions(user_pct, limit=1, due_priority=None):
            return []

    monkeypatch.setattr(
        "app.learning_plan_generation.plan_service._kg", _FakeKG()
    )
    monkeypatch.setattr("app.visualization_service.dashboard", _FakeDash())


def test_get_smart_resume_prefers_learning_plan_step(monkeypatch) -> None:
    fake_resume = {
        "resource_type": "learning_plan",
        "step_index": 1,
        "step_label": "Векторы — скалярное произведение",
            "display_title": "Программа по теме «Линейная алгебра»",
    }
    _patch_smart_resume_deps(monkeypatch, learning_plan_resume=fake_resume)

    result = learning_plan_service.plan_service.get_smart_resume()

    assert result.startswith("Программа:")
    assert "Векторы" in result or "скалярное" in result


def test_get_smart_resume_falls_through_on_empty_learning_plan(monkeypatch) -> None:
    _patch_smart_resume_deps(monkeypatch, learning_plan_resume=None)

    result = learning_plan_service.plan_service.get_smart_resume()

    assert isinstance(result, str)
    assert result
