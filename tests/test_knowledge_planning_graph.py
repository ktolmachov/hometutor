"""B1: graph-backed learning plan — prerequisite snippet, order validator, prompt block."""

from __future__ import annotations

from types import SimpleNamespace

import app.knowledge_planning as kp
from app.knowledge_planning import (
    _dynamic_plan_prompt_block,
    _graph_prerequisite_snippet,
    _reorder_validator,
)
from app.learning_plan_state import LearningPlanStep


def test_prerequisite_snippet_empty_when_no_concepts() -> None:
    assert _graph_prerequisite_snippet([]) == ""


def test_prerequisite_snippet_empty_when_non_existent_concepts() -> None:
    assert _graph_prerequisite_snippet(["nonexistent_concept_xyz"]) == ""


def test_dynamic_plan_block_empty_when_disabled() -> None:
    assert _dynamic_plan_prompt_block(None) == ""
    assert _dynamic_plan_prompt_block({"enabled": False}) == ""


def test_dynamic_plan_block_includes_mandatory_header() -> None:
    dp = {
        "enabled": True,
        "plan": [
            {"topic": "Векторы", "type": "new", "reason": "основы", "estimated_hours": 2.0},
        ],
        "mastery_percentage": 30.0,
        "next_review_count": 5,
    }
    block = _dynamic_plan_prompt_block(dp)
    assert "ОБЯЗАТЕЛЬНЫЙ ПОРЯДОК" in block
    assert "НЕ МЕНЯЙ ЕГО" in block
    assert "Векторы" in block
    assert "30.0%" in block or "30%" in block


def test_reorder_validator_passes_when_order_matches() -> None:
    steps = [
        LearningPlanStep(index="1", title="Векторы"),
        LearningPlanStep(index="2", title="Скалярное произведение"),
    ]
    dp_plan = [
        {"topic": "Векторы"},
        {"topic": "Скалярное произведение"},
    ]
    ok, msg = _reorder_validator(steps, dp_plan)
    assert ok is True
    assert msg == ""


def test_reorder_validator_warns_on_contradiction() -> None:
    """Order contradiction detected → returns (False, warning text)."""
    steps = [
        LearningPlanStep(index="1", title="Скалярное произведение"),
        LearningPlanStep(index="2", title="Векторы"),
    ]
    dp_plan = [
        {"topic": "Векторы"},
        {"topic": "Скалярное произведение"},
    ]
    ok, msg = _reorder_validator(steps, dp_plan)
    assert ok is False
    assert "нарушает карту знаний" in msg
    assert "Векторы" in msg
    assert "Скалярное произведение" in msg


def test_reorder_validator_no_warning_when_topics_not_in_graph() -> None:
    steps = [
        LearningPlanStep(index="1", title="Custom topic A"),
        LearningPlanStep(index="2", title="Custom topic B"),
    ]
    dp_plan = [
        {"topic": "Unrelated"},
    ]
    ok, msg = _reorder_validator(steps, dp_plan)
    assert ok is True
    assert msg == ""


def test_reorder_validator_empty_dp_plan_passes() -> None:
    steps = [LearningPlanStep(index="1", title="Векторы")]
    ok, msg = _reorder_validator(steps, [])
    assert ok is True
    assert msg == ""


def test_build_learning_plan_exposes_order_warning(monkeypatch) -> None:
    plan_text = """
| # | Тема | Документ(ы) | Ключевые концепции | Практика | Проверка результата | Зависимости | Время (ч) |
|---|---|---|---|---|---|---|---|
| 1 | Скалярное произведение | dot.md | угол | практика | проверка | Векторы | 1 |
| 2 | Векторы | intro.md | координаты | практика | проверка | нет | 1 |
""".strip()

    monkeypatch.setattr(
        kp,
        "_select_documents_for_synthesis",
        lambda **kwargs: (
            "Линейная алгебра",
            [
                {
                    "relative_path": "intro.md",
                    "summary": "summary",
                    "key_concepts": ["Векторы", "Скалярное произведение"],
                    "difficulty": "medium",
                }
            ],
        ),
    )
    monkeypatch.setattr(
        kp,
        "_fetch_chunks_for_documents",
        lambda *args, **kwargs: ([{"source": "intro.md"}], {"intro.md": ["chunk"]}),
    )
    monkeypatch.setattr(kp, "compute_source_coverage", lambda **kwargs: {})
    monkeypatch.setattr(
        kp.plan_service,
        "generate",
        lambda params: {
            "enabled": True,
            "plan": [{"topic": "Векторы"}, {"topic": "Скалярное произведение"}],
        },
    )
    monkeypatch.setattr(kp, "complete_with_resilience", lambda llm, prompt, stage: SimpleNamespace(text=plan_text))

    result = kp.build_learning_plan(
        topic="Линейная алгебра",
        goal="Изучить",
        level="intermediate",
        time_budget_hours=4,
        user_progress=True,
        services={"llm": object()},
    )

    assert result["plan_order_warning"] is not None
    assert "нарушает карту знаний" in result["plan_order_warning"]
