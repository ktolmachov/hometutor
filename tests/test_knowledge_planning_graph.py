"""B1: graph-backed learning plan — prerequisite snippet, order validator, prompt block."""

from __future__ import annotations

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
    assert _reorder_validator(steps, dp_plan) is True


def test_reorder_validator_warns_on_contradiction() -> None:
    """Order contradiction detected → returns False (warning goes to stderr, visible in logs)."""
    steps = [
        LearningPlanStep(index="1", title="Скалярное произведение"),
        LearningPlanStep(index="2", title="Векторы"),
    ]
    dp_plan = [
        {"topic": "Векторы"},
        {"topic": "Скалярное произведение"},
    ]
    result = _reorder_validator(steps, dp_plan)
    assert result is False


def test_reorder_validator_no_warning_when_topics_not_in_graph() -> None:
    steps = [
        LearningPlanStep(index="1", title="Custom topic A"),
        LearningPlanStep(index="2", title="Custom topic B"),
    ]
    dp_plan = [
        {"topic": "Unrelated"},
    ]
    assert _reorder_validator(steps, dp_plan) is True


def test_reorder_validator_empty_dp_plan_passes() -> None:
    steps = [LearningPlanStep(index="1", title="Векторы")]
    assert _reorder_validator(steps, []) is True
