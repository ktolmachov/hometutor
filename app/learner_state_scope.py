"""Helpers for scoping learner state to the active knowledge graph."""

from __future__ import annotations

from typing import Any

from app.due_queue_display import due_queue_overflow_caption, is_soft_recovery_overflow
from app.knowledge_graph import JsonKnowledgeGraph
from app.quiz_adaptive import get_all_mastery_levels, get_weak_concepts, list_quiz_mastery_state
from app.spaced_repetition import get_due_reviews

_MAX_DUE_SCAN = 5000


def active_concept_ids(kg: JsonKnowledgeGraph) -> set[str]:
    return {
        str(concept_id).strip()
        for concept_id, node in kg.get_concepts().items()
        if isinstance(node, dict) and str(concept_id).strip()
    }


def filter_mastery_levels_for_kg(
    mastery_levels: dict[str, str],
    kg: JsonKnowledgeGraph,
) -> dict[str, str]:
    active = active_concept_ids(kg)
    if not active:
        return dict(mastery_levels or {})
    return {
        concept: level
        for concept, level in (mastery_levels or {}).items()
        if str(concept).strip() in active
    }


def get_mastery_levels_for_kg(kg: JsonKnowledgeGraph) -> dict[str, str]:
    return filter_mastery_levels_for_kg(get_all_mastery_levels(), kg)


def filter_quiz_rows_for_kg(
    rows: list[dict[str, Any]],
    kg: JsonKnowledgeGraph,
) -> list[dict[str, Any]]:
    active = active_concept_ids(kg)
    if not active:
        return list(rows or [])
    return [
        row
        for row in (rows or [])
        if str((row or {}).get("concept") or "").strip() in active
    ]


def get_quiz_mastery_rows_for_kg(kg: JsonKnowledgeGraph) -> list[dict[str, Any]]:
    return filter_quiz_rows_for_kg(list_quiz_mastery_state(), kg)


def filter_due_reviews_for_kg(
    kg: JsonKnowledgeGraph,
    *,
    limit: int = 200,
    scan_limit: int = _MAX_DUE_SCAN,
) -> list[dict[str, Any]]:
    active = active_concept_ids(kg)
    raw_limit = max(limit, scan_limit)
    rows = get_due_reviews(limit=raw_limit)
    if not active:
        return rows[:limit]
    out: list[dict[str, Any]] = []
    for row in rows:
        concept = str((row or {}).get("concept") or "").strip()
        if concept and concept in active:
            out.append(row)
        if len(out) >= limit:
            break
    return out


def count_due_reviews_for_kg(
    kg: JsonKnowledgeGraph,
    *,
    scan_limit: int = _MAX_DUE_SCAN,
) -> int:
    return len(filter_due_reviews_for_kg(kg, limit=scan_limit, scan_limit=scan_limit))


def due_priority_by_concept_for_kg(
    kg: JsonKnowledgeGraph,
    *,
    limit: int = 200,
    scan_limit: int = _MAX_DUE_SCAN,
) -> dict[str, float]:
    due = filter_due_reviews_for_kg(kg, limit=limit, scan_limit=scan_limit)
    out: dict[str, float] = {}
    for i, row in enumerate(due):
        concept = str((row or {}).get("concept") or "").strip()
        if concept and concept not in out:
            out[concept] = max(0.0, 1.0 - i * 0.02)
    return out


def due_reviews_summary_for_kg(
    kg: JsonKnowledgeGraph,
    *,
    preview_limit: int = 7,
    scan_limit: int = _MAX_DUE_SCAN,
) -> dict[str, Any]:
    total = count_due_reviews_for_kg(kg, scan_limit=scan_limit)
    empty = {
        "count": 0,
        "hint": None,
        "preview_concepts": [],
        "deferred_count": 0,
        "overflow_caption": "",
        "overflow_mode": False,
    }
    if total == 0:
        return empty
    due = filter_due_reviews_for_kg(kg, limit=preview_limit, scan_limit=scan_limit)
    names = [str(d.get("concept") or "") for d in due if str(d.get("concept") or "").strip()]
    shown = len(names)
    deferred_count = max(0, total - shown)
    overflow_caption = due_queue_overflow_caption(total, shown)
    overflow_mode = is_soft_recovery_overflow(total)
    hint = None
    if names:
        hint = f"Пора повторить {total} концепций: {names[0]}"
        if overflow_caption:
            hint = f"{hint} · {overflow_caption}"
    return {
        "count": total,
        "hint": hint,
        "preview_concepts": names,
        "deferred_count": deferred_count,
        "overflow_caption": overflow_caption,
        "overflow_mode": overflow_mode,
    }


def weak_concepts_for_kg(
    kg: JsonKnowledgeGraph,
    *,
    threshold: int = 60,
    limit: int = 12,
) -> list[str]:
    active = active_concept_ids(kg)
    weak = get_weak_concepts(threshold=threshold, limit=max(limit, 50))
    if not active:
        return weak[:limit]
    out = [concept for concept in weak if str(concept).strip() in active]
    return out[:limit]


__all__ = [
    "active_concept_ids",
    "count_due_reviews_for_kg",
    "due_reviews_summary_for_kg",
    "due_priority_by_concept_for_kg",
    "filter_due_reviews_for_kg",
    "filter_mastery_levels_for_kg",
    "filter_quiz_rows_for_kg",
    "get_mastery_levels_for_kg",
    "get_quiz_mastery_rows_for_kg",
    "weak_concepts_for_kg",
]
