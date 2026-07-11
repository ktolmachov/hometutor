from app import user_state
from app.ui.course_prepare_view import _preview_cards_from_plan


TABLE_PLAN = """
| # | Тема | Документ(ы) | Ключевые концепции | Зависимости | Время (ч) |
|---|---|---|---|---|---|
| 1 | Векторы | intro.md | координаты, модуль | нет | 1.5 |
| 2 | Скалярное произведение | dot.md | угол, проекция | Векторы | 2 |
""".strip()


def test_learning_plan_steps_from_markdown_parses_table_rows_as_steps() -> None:
    steps = user_state.learning_plan_steps_from_markdown(TABLE_PLAN)

    assert len(steps) == 2
    assert steps[0].startswith("Векторы")
    assert "Концепции: координаты, модуль" in steps[0]
    assert "Документы: intro.md" in steps[0]
    assert "Время: 1.5 ч" in steps[0]
    assert steps[1].startswith("Скалярное произведение")


def test_learning_plan_steps_from_markdown_keeps_legacy_numbered_fallback() -> None:
    plan_md = """
1. Первый шаг
   Деталь первого шага
2. Второй шаг
""".strip()

    steps = user_state.learning_plan_steps_from_markdown(plan_md)

    assert steps == ["1. Первый шаг\n   Деталь первого шага", "2. Второй шаг"]


def test_learning_plan_steps_from_markdown_does_not_leak_table_pipes() -> None:
    steps = user_state.learning_plan_steps_from_markdown(TABLE_PLAN)

    assert steps
    assert all("|" not in step for step in steps)


def test_preview_cards_from_plan_uses_structured_table_steps() -> None:
    cards = _preview_cards_from_plan({"plan": TABLE_PLAN})

    assert len(cards) == 2
    assert cards[0].startswith("Векторы")
    assert all("|" not in card for card in cards)


def test_learning_plan_table_hours_summary_sums_numeric_hours() -> None:
    summary = user_state.learning_plan_table_hours_summary_from_markdown(TABLE_PLAN)

    assert summary == {
        "total_hours": 3.5,
        "steps_count": 2,
        "missing_or_invalid_hours": 0,
    }


def test_learning_plan_table_hours_summary_counts_invalid_hours() -> None:
    plan = """
| # | Тема | Время (ч) |
|---|---|---|
| 1 | Векторы | около часа |
| 2 | Производная | 2,5 |
""".strip()

    summary = user_state.learning_plan_table_hours_summary_from_markdown(plan)

    assert summary == {
        "total_hours": 2.5,
        "steps_count": 2,
        "missing_or_invalid_hours": 1,
    }
