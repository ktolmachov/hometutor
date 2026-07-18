"""Learning-readiness passport for the current Living Konspekt workbench.

The core builder is deterministic and side-effect free. The facade enriches rows
with best-effort local signals for UI surfaces.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

LOW_MASTERY_THRESHOLD = 60

STATUS_RAW = "raw"
STATUS_IN_PROGRESS = "in_progress"
STATUS_READY = "ready"

NEXT_ADD_FIRST_SECTION = "add_first_section"
NEXT_READ_FIRST_UNREAD = "read_first_unread"
NEXT_ADD_PERSONAL_NOTE = "add_personal_note"
NEXT_RESOLVE_OPEN_QUESTION = "resolve_open_question"
NEXT_MARK_UNDERSTANDING = "mark_understanding"
NEXT_REVIEW_READY = "review_ready"


def build_konspekt_learning_passport(
    rows: list[dict[str, Any]],
    *,
    mastery_levels: dict[str, str] | None = None,
    rubric_by_md: dict[str, dict[str, Any] | None] | None = None,
    stale_by_md: dict[str, str | None] | None = None,
    grade_by_md: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    """Build a pure learning-readiness summary for Living Konspekt rows."""
    clean_rows = [row for row in rows if isinstance(row, dict)]
    md_paths = _unique_values(row.get("konspekt_md_abs") for row in clean_rows)
    concepts = _unique_values(row.get("concept") for row in clean_rows)

    counts = {
        "sections": len(clean_rows),
        "consumed": sum(1 for row in clean_rows if row.get("read_at") or row.get("listened_at")),
        "read": sum(1 for row in clean_rows if row.get("read_at")),
        "listened": sum(1 for row in clean_rows if row.get("listened_at")),
        "personal_notes": sum(1 for row in clean_rows if _has_text(row.get("note"))),
        "understood": sum(1 for row in clean_rows if str(row.get("knowledge_status") or "") == "understood"),
        "unsure": sum(1 for row in clean_rows if str(row.get("knowledge_status") or "") == "unsure"),
        "unclear": sum(1 for row in clean_rows if str(row.get("knowledge_status") or "") == "unclear"),
        "open_questions": sum(1 for row in clean_rows if _has_text(row.get("open_question"))),
        "documents": len(md_paths),
        "concepts": len(concepts),
    }

    has_work = any(
        row.get("read_at")
        or row.get("listened_at")
        or _has_text(row.get("note"))
        or row.get("knowledge_status")
        or _has_text(row.get("open_question"))
        for row in clean_rows
    )
    all_understood = bool(clean_rows) and counts["understood"] == len(clean_rows)
    if not clean_rows or not has_work:
        status = STATUS_RAW
    elif all_understood:
        status = STATUS_READY
    else:
        status = STATUS_IN_PROGRESS

    next_step = _next_step(status, counts)
    quality = _quality_payload(md_paths, rubric_by_md or {}, grade_by_md or {})
    novelty = _novelty_payload(concepts, mastery_levels)
    has_stale_sources = any((stale_by_md or {}).get(md) == "stale" for md in md_paths)

    return {
        "status": status,
        "next_step": next_step,
        "counts": counts,
        "flags": {
            "has_work": has_work,
            "has_open_questions": counts["open_questions"] > 0,
            "has_personal_notes": counts["personal_notes"] > 0,
            "has_quality_rubric": quality["rubric_count"] > 0,
            "has_stale_sources": has_stale_sources,
            "all_understood": all_understood,
        },
        "quality": quality,
        "novelty": novelty,
    }


def build_konspekt_learning_passport_for_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the UI passport with best-effort disk and learner-state enrichment."""
    clean_rows = [row for row in rows if isinstance(row, dict)]
    md_paths = _unique_values(row.get("konspekt_md_abs") for row in clean_rows)
    rubric_by_md: dict[str, dict[str, Any] | None] = {}
    stale_by_md: dict[str, str | None] = {}
    grade_by_md: dict[str, str | None] = {}

    for md_abs in md_paths:
        rubric_by_md[md_abs] = _rubric_for_md(md_abs)
        grade_by_md[md_abs] = _grade_for_md(md_abs)
        stale_by_md[md_abs] = _staleness_for_md(md_abs)

    try:
        from app.quiz_adaptive import get_all_mastery_levels

        mastery_levels = get_all_mastery_levels()
    except Exception:  # noqa: BLE001 - novelty degrades to unknown when learner mastery is unavailable
        mastery_levels = None

    return build_konspekt_learning_passport(
        clean_rows,
        mastery_levels=mastery_levels,
        rubric_by_md=rubric_by_md,
        stale_by_md=stale_by_md,
        grade_by_md=grade_by_md,
    )


def _next_step(status: str, counts: dict[str, int]) -> str:
    if status == STATUS_READY:
        return NEXT_REVIEW_READY
    if counts["sections"] <= 0:
        return NEXT_ADD_FIRST_SECTION
    if counts["consumed"] < counts["sections"]:
        return NEXT_READ_FIRST_UNREAD
    if counts["personal_notes"] <= 0:
        return NEXT_ADD_PERSONAL_NOTE
    if counts["open_questions"] > 0:
        return NEXT_RESOLVE_OPEN_QUESTION
    return NEXT_MARK_UNDERSTANDING


def _quality_payload(
    md_paths: list[str],
    rubric_by_md: dict[str, dict[str, Any] | None],
    grade_by_md: dict[str, str | None],
) -> dict[str, Any]:
    rubric_avgs: list[float] = []
    for md in md_paths:
        rubric = rubric_by_md.get(md)
        if not isinstance(rubric, dict):
            continue
        avg = rubric.get("average")
        if isinstance(avg, (int, float)):
            rubric_avgs.append(float(avg))
    grades = [grade for grade in (grade_by_md.get(md) for md in md_paths) if _has_text(grade)]
    return {
        "rubric_average": round(sum(rubric_avgs) / len(rubric_avgs), 1) if rubric_avgs else None,
        "rubric_count": len(rubric_avgs),
        "konspekt_grades": grades,
    }


def _novelty_payload(concepts: list[str], mastery_levels: dict[str, str] | None) -> dict[str, Any]:
    if mastery_levels is None:
        return {
            "unknown": True,
            "low_mastery_concepts": 0,
            "concepts": len(concepts),
            "pct": None,
        }
    from app.quiz_adaptive import mastery_percent_for_level

    low = sum(
        1
        for concept in concepts
        if mastery_percent_for_level(mastery_levels.get(concept, "recognition")) < LOW_MASTERY_THRESHOLD
    )
    return {
        "unknown": False,
        "low_mastery_concepts": low,
        "concepts": len(concepts),
        "pct": round(low / len(concepts) * 100) if concepts else None,
    }


def _rubric_for_md(md_abs: str) -> dict[str, Any] | None:
    try:
        from app.konspekt_discovery import get_konspekt_quality_rubric

        return get_konspekt_quality_rubric(md_abs)
    except Exception:  # noqa: BLE001 - passport facade must degrade per broken local file and keep UI rendering
        return None


def _grade_for_md(md_abs: str) -> str | None:
    try:
        from app.section_index import _cached_parse_sections, get_konspekt_grade

        return get_konspekt_grade(_cached_parse_sections(Path(md_abs)))
    except Exception:  # noqa: BLE001 - passport facade must degrade per broken local file and keep UI rendering
        return None


def _staleness_for_md(md_abs: str) -> str | None:
    try:
        from app.konspekt_discovery import konspekt_source_staleness, scan_konspekts

        md_path = Path(md_abs)
        md_resolved = md_path.resolve()
        km = next(
            (item for item in scan_konspekts(md_path.parent) if item.path.resolve() == md_resolved),
            None,
        )
        # Unknown staleness is not stale: files without type:konspekt/source hash
        # simply do not contribute to the stale flag in P0.
        return konspekt_source_staleness(km) if km is not None else None
    except Exception:  # noqa: BLE001 - passport facade must degrade per broken local file and keep UI rendering
        return None


def _unique_values(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _has_text(value: Any) -> bool:
    return bool(str(value or "").strip())


__all__ = [
    "LOW_MASTERY_THRESHOLD",
    "NEXT_ADD_FIRST_SECTION",
    "NEXT_ADD_PERSONAL_NOTE",
    "NEXT_MARK_UNDERSTANDING",
    "NEXT_READ_FIRST_UNREAD",
    "NEXT_RESOLVE_OPEN_QUESTION",
    "NEXT_REVIEW_READY",
    "STATUS_IN_PROGRESS",
    "STATUS_RAW",
    "STATUS_READY",
    "build_konspekt_learning_passport",
    "build_konspekt_learning_passport_for_rows",
]
