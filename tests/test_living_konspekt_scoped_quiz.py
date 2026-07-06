from app.living_konspekt_scoped_quiz import build_living_konspekt_quiz_context
from app.ui.living_konspekt_next_steps import course_coverage_summary


def test_living_konspekt_quiz_context_uses_only_selected_rows() -> None:
    rows = [
        {
            "heading_text": "Выбранный фрагмент",
            "text": "Агенты используют инструменты через строгие схемы вызова.",
            "source_rel": "course/lesson-1.txt",
            "line_start": 10,
            "line_end": 14,
        }
    ]

    context = build_living_konspekt_quiz_context(rows)

    assert "Выбранный фрагмент" in context
    assert "course/lesson-1.txt:10-14" in context
    assert "строгие схемы вызова" in context
    assert "retrieval" not in context.lower()


def test_course_coverage_summary_counts_sources_present_in_workbench() -> None:
    rows = [
        {"source_rel": "course/lesson-1.txt", "heading_text": "A"},
        {"source_rel": "course/lesson-3.txt", "heading_text": "C"},
    ]
    scope = {
        "active": True,
        "title": "Курс",
        "source_paths": ["course/lesson-1.txt", "course/lesson-2.txt", "course/lesson-3.txt"],
    }

    summary = course_coverage_summary(rows, scope)

    assert summary is not None
    assert summary["covered"] == 2
    assert summary["total"] == 3
    assert summary["missing_paths"] == ["course/lesson-2.txt"]
