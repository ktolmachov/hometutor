from __future__ import annotations

from app.konspekt_learning_passport import (
    LOW_MASTERY_THRESHOLD,
    build_konspekt_learning_passport,
    build_konspekt_learning_passport_for_rows,
)


def test_passport_status_progression() -> None:
    assert build_konspekt_learning_passport([])["status"] == "raw"

    assert build_konspekt_learning_passport([
        {"row_key": "r1", "heading_text": "A"}
    ])["status"] == "raw"

    assert build_konspekt_learning_passport([
        {"row_key": "r1", "heading_text": "A", "read_at": "2026-07-18T10:00:00Z"}
    ])["status"] == "in_progress"

    assert build_konspekt_learning_passport([
        {"row_key": "r1", "heading_text": "A", "knowledge_status": "understood"}
    ])["status"] == "ready"


def test_status_boundary_cases() -> None:
    assert build_konspekt_learning_passport([
        {"row_key": "r1", "knowledge_status": "unsure"}
    ])["status"] == "in_progress"

    assert build_konspekt_learning_passport([
        {"row_key": "r1", "knowledge_status": "understood"},
        {"row_key": "r2", "knowledge_status": "unsure"},
    ])["status"] == "in_progress"

    passport = build_konspekt_learning_passport([
        {"row_key": "r1", "knowledge_status": "understood", "open_question": "Почему так?"}
    ])
    assert passport["status"] == "ready"
    assert passport["next_step"] == "review_ready"
    assert passport["flags"]["has_open_questions"] is True


def test_next_step_matrix() -> None:
    assert build_konspekt_learning_passport([])["next_step"] == "add_first_section"
    assert build_konspekt_learning_passport([
        {"row_key": "r1"}
    ])["next_step"] == "read_first_unread"
    assert build_konspekt_learning_passport([
        {"row_key": "r1", "read_at": "2026-07-18T10:00:00Z"}
    ])["next_step"] == "add_personal_note"
    assert build_konspekt_learning_passport([
        {
            "row_key": "r1",
            "read_at": "2026-07-18T10:00:00Z",
            "note": "моя мысль",
            "open_question": "Q?",
        }
    ])["next_step"] == "resolve_open_question"
    assert build_konspekt_learning_passport([
        {"row_key": "r1", "read_at": "2026-07-18T10:00:00Z", "note": "моя мысль"}
    ])["next_step"] == "mark_understanding"
    assert build_konspekt_learning_passport([
        {"row_key": "r1", "knowledge_status": "understood"}
    ])["next_step"] == "review_ready"


def test_consumed_read_listened_overlap() -> None:
    passport = build_konspekt_learning_passport([
        {"row_key": "r1", "read_at": "r"},
        {"row_key": "r2", "listened_at": "l"},
        {"row_key": "r3", "read_at": "r", "listened_at": "l"},
        {"row_key": "r4"},
    ])
    assert passport["counts"]["read"] == 2
    assert passport["counts"]["listened"] == 2
    assert passport["counts"]["consumed"] == 3


def test_novelty_unknown_keeps_concept_count() -> None:
    passport = build_konspekt_learning_passport([
        {"row_key": "r1", "concept": "A"},
        {"row_key": "r2", "concept": "A"},
        {"row_key": "r3", "concept": "B"},
    ])
    assert passport["novelty"] == {
        "unknown": True,
        "low_mastery_concepts": 0,
        "concepts": 2,
        "pct": None,
    }


def test_novelty_threshold_uses_sixty_percent() -> None:
    # Current quiz_adaptive mapping: recognition=44 (<60), recall=68 (>=60).
    passport = build_konspekt_learning_passport(
        [
            {"row_key": "r1", "concept": "A"},
            {"row_key": "r2", "concept": "B"},
        ],
        mastery_levels={"A": "recognition", "B": "recall"},
    )
    assert LOW_MASTERY_THRESHOLD == 60
    assert passport["novelty"]["unknown"] is False
    assert passport["novelty"]["low_mastery_concepts"] == 1
    assert passport["novelty"]["pct"] == 50


def test_quality_rubric_average_of_document_averages() -> None:
    passport = build_konspekt_learning_passport(
        [
            {"row_key": "r1", "konspekt_md_abs": "a.md"},
            {"row_key": "r2", "konspekt_md_abs": "b.md"},
        ],
        rubric_by_md={
            "a.md": {"average": 4.0, "count": 5},
            "b.md": {"average": 2.0, "count": 2},
        },
        grade_by_md={"a.md": "богатый", "b.md": "богатый + рубрика"},
    )
    assert passport["quality"]["rubric_average"] == 3.0
    assert passport["quality"]["rubric_count"] == 2
    assert passport["quality"]["konspekt_grades"] == ["богатый", "богатый + рубрика"]
    assert passport["flags"]["has_quality_rubric"] is True


def test_unknown_staleness_is_not_stale() -> None:
    passport = build_konspekt_learning_passport(
        [{"row_key": "r1", "konspekt_md_abs": "a.md"}],
        stale_by_md={"a.md": None},
    )
    assert passport["flags"]["has_stale_sources"] is False


def test_facade_passes_mastery_levels_into_novelty(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.quiz_adaptive.get_all_mastery_levels",
        lambda: {"A": "recognition"},
    )

    passport = build_konspekt_learning_passport_for_rows([
        {"row_key": "r1", "concept": "A"}
    ])

    assert passport["novelty"]["unknown"] is False
    assert passport["novelty"]["concepts"] == 1


def test_facade_degrades_on_broken_local_file(monkeypatch) -> None:
    monkeypatch.setattr("app.quiz_adaptive.get_all_mastery_levels", lambda: {})

    passport = build_konspekt_learning_passport_for_rows([
        {"row_key": "r1", "konspekt_md_abs": "Z:/missing/nope.md"}
    ])

    assert passport["quality"]["rubric_average"] is None
    assert passport["quality"]["konspekt_grades"] == []
    assert passport["flags"]["has_stale_sources"] is False
