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


def test_telegram_daily_topic_line_marks_weekly_fallback(monkeypatch) -> None:
    class _PlanService:
        def generate_personalized_plan(self, *, user_progress: bool) -> dict:
            assert user_progress is True
            return {"daily_plan": [{"concept": "Векторы"}]}

    monkeypatch.setattr(learning_plan_service, "get_today_primary_learning_item", lambda: None)
    monkeypatch.setattr(learning_plan_service, "plan_service", _PlanService())

    assert telegram_notifications._daily_topic_line() == "Сегодня (резервный план): Векторы"
