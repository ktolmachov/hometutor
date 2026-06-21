"""
Spaced repetition (SuperMemo-2) для концептов после quiz (P1).

Хранение в ``user_state.db``, таблица ``spaced_repetition`` — создаётся в ``user_state._ensure_schema``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings
from app.knowledge_graph import JsonKnowledgeGraph
from app.user_state import _with_db, sync_current_learner_state_lineage

DEFAULT_EASINESS = 2.5
DEFAULT_INTERVAL_DAYS = 1
DEFAULT_REPETITIONS = 0
_DEFAULT_DUE_QUEUE_LIMIT = 7


def apply_sm2(
    easiness: float,
    interval_days: int,
    repetitions: int,
    quality: int,
) -> tuple[float, int, int]:
    """SM-2: quality 0..5 (5 = без затруднений). Возвращает (new_ef, new_interval_days, new_repetitions)."""
    q = max(0, min(5, int(quality)))
    old_e = float(easiness)
    old_i = max(1, int(interval_days))
    old_r = max(0, int(repetitions))

    if q < 3:
        new_r = 0
        new_i = 1
    else:
        new_r = old_r + 1
        if new_r == 1:
            new_i = 1
        elif new_r == 2:
            new_i = 6
        else:
            new_i = max(1, round(old_i * old_e))

    new_e = max(1.3, old_e + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))
    return new_e, new_i, new_r


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_dt_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _days_overdue_from_row(row: dict[str, Any], *, now: datetime) -> int:
    next_review = _parse_dt_iso(row.get("next_review"))
    if next_review is None:
        return 0
    return max(0, int((now - next_review).days))


def _mastery_gap_from_row(row: dict[str, Any]) -> float:
    try:
        easiness = float(row.get("easiness") or DEFAULT_EASINESS)
    except (TypeError, ValueError):
        easiness = DEFAULT_EASINESS
    return max(0.1, round(3.0 - easiness, 4))


def _rank_due_row(row: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    ranked = dict(row)
    days_overdue = _days_overdue_from_row(ranked, now=now)
    mastery_gap = _mastery_gap_from_row(ranked)
    ranked["days_overdue"] = days_overdue
    ranked["mastery_gap"] = mastery_gap
    ranked["priority_score"] = round(days_overdue * mastery_gap, 4)
    return ranked


def _due_sort_key(row: dict[str, Any]) -> tuple[float, str, str]:
    concept = str(row.get("concept") or "").strip().casefold()
    next_review = str(row.get("next_review") or "")
    try:
        priority_score = float(row.get("priority_score") or 0.0)
    except (TypeError, ValueError):
        priority_score = 0.0
    return (-priority_score, next_review, concept)


def due_priority_reason(
    row: dict[str, Any],
    *,
    has_quiz_errors: bool = False,
    has_low_mastery_signal: bool = False,
) -> str:
    """Короткая user-facing причина приоритета due-концепта."""
    if has_quiz_errors:
        return "ошибки в quiz"
    if has_low_mastery_signal:
        return "низкий mastery"
    days_overdue = _days_overdue_from_row(row, now=_utc_now())
    if days_overdue > 0:
        return "давно не повторял"
    mastery_gap = _mastery_gap_from_row(row)
    if mastery_gap >= 1.2:
        return "низкий mastery"
    return "плановое повторение"


def record_quiz_score_for_spaced_repetition(
    concept: str,
    score_01: float,
    *,
    provenance: Any | None = None,
) -> dict[str, Any]:
    """
    Обновить SM-2 после оценки 0..1 (micro-quiz, согласовано с evaluate_inline_quiz_answer).
    quality = round(score * 5) в диапазоне 0..5.
    """
    c = (concept or "").strip() or "unknown"
    q = max(0, min(5, int(round(float(score_01) * 5))))
    return update_spaced_repetition(c, q, provenance=provenance)


def update_spaced_repetition(
    concept: str,
    quality: int,
    *,
    provenance: Any | None = None,
) -> dict[str, Any]:
    """Обновить SM-2 после оценки ответа (quality 0..5)."""
    from app.fact_source_binding import provenance_to_dict, require_fact_provenance

    c = (concept or "").strip() or "unknown"
    validated_provenance = require_fact_provenance(
        provenance,
        operation="update_spaced_repetition",
    )

    settings = get_settings()
    min_quality = max(0, min(5, int(settings.sr_min_quality)))
    max_interval_days = max(1, int(settings.sr_max_interval_days))
    effective_quality = max(min_quality, min(5, int(quality)))

    def _work(conn: sqlite3.Connection) -> dict[str, Any]:
        lineage = sync_current_learner_state_lineage(conn)
        current_generation_id = str(lineage.get("generation_id") or "").strip() or None
        current_index_version = lineage.get("index_version")
        row = conn.execute(
            """
            SELECT easiness, interval_days, repetitions
            FROM spaced_repetition WHERE concept = ? AND (? IS NULL OR generation_id = ?)
            """,
            (c, current_generation_id, current_generation_id),
        ).fetchone()
        if row:
            e = float(row["easiness"])
            i = int(row["interval_days"])
            r = int(row["repetitions"])
        else:
            e, i, r = DEFAULT_EASINESS, DEFAULT_INTERVAL_DAYS, DEFAULT_REPETITIONS

        ne, ni, nr = apply_sm2(e, i, r, effective_quality)
        ni = max(1, min(int(ni), max_interval_days))
        now = _utc_now()
        last_iso = now.isoformat()
        next_iso = (now + timedelta(days=ni)).isoformat()

        conn.execute(
            """
            INSERT INTO spaced_repetition(
                concept, easiness, interval_days, repetitions, next_review, last_review,
                generation_id, index_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(concept) DO UPDATE SET
                easiness = excluded.easiness,
                interval_days = excluded.interval_days,
                repetitions = excluded.repetitions,
                next_review = excluded.next_review,
                last_review = excluded.last_review,
                generation_id = excluded.generation_id,
                index_version = excluded.index_version
            """,
            (c, ne, ni, nr, next_iso, last_iso, current_generation_id, current_index_version),
        )
        conn.commit()
        return {
            "concept": c,
            "quality": effective_quality,
            "easiness": round(ne, 4),
            "interval_days": ni,
            "repetitions": nr,
            "next_review": next_iso,
            "last_review": last_iso,
            "generation_id": current_generation_id,
            "index_version": current_index_version,
            "provenance": provenance_to_dict(validated_provenance),
        }

    return _with_db(_work)


def count_due_reviews() -> int:
    """Число концептов с просроченным next_review (UTC)."""

    def _work(conn: sqlite3.Connection) -> int:
        lineage = sync_current_learner_state_lineage(conn)
        cutoff = _utc_now().isoformat()
        current_generation_id = str(lineage.get("generation_id") or "").strip()
        where = "next_review IS NOT NULL AND next_review <= ?"
        params: list[Any] = [cutoff]
        if current_generation_id:
            where += " AND generation_id = ?"
            params.append(current_generation_id)
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS n FROM spaced_repetition
            WHERE {where}
            """,
            params,
        ).fetchone()
        return int(row["n"]) if row else 0

    return _with_db(_work)


def get_due_reviews(*, limit: int = 200) -> list[dict[str, Any]]:
    """Концепты с ``next_review`` не позже текущего момента (UTC)."""
    cutoff = _utc_now().isoformat()

    def _work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        lineage = sync_current_learner_state_lineage(conn)
        current_generation_id = str(lineage.get("generation_id") or "").strip()
        where = "next_review IS NOT NULL AND next_review <= ?"
        params: list[Any] = [cutoff]
        if current_generation_id:
            where += " AND generation_id = ?"
            params.append(current_generation_id)
        rows = conn.execute(
            f"""
            SELECT concept, easiness, interval_days, repetitions, next_review, last_review,
                   generation_id, index_version
            FROM spaced_repetition
            WHERE {where}
            ORDER BY next_review ASC, concept COLLATE NOCASE ASC
            """,
            params,
        ).fetchall()
        now = _utc_now()
        ranked = [_rank_due_row(dict(r), now=now) for r in rows]
        ranked.sort(key=_due_sort_key)
        safe_limit = max(1, int(limit))
        return ranked[:safe_limit]

    return _with_db(_work)


def get_all_sr_concepts() -> list[dict[str, Any]]:
    """All SRS records for current learner: concept, easiness, interval_days, last_review.

    Used by the D3 knowledge-graph decay overlay (KG-06) to compute Ebbinghaus retention.
    Returns an empty list when the table is empty or the DB is unavailable.
    """

    def _work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        lineage = sync_current_learner_state_lineage(conn)
        gen_id = str(lineage.get("generation_id") or "").strip()
        where = "1=1"
        params: list[Any] = []
        if gen_id:
            where = "generation_id = ?"
            params.append(gen_id)
        rows = conn.execute(
            f"SELECT concept, easiness, interval_days, last_review "
            f"FROM spaced_repetition WHERE {where}",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    return _with_db(_work)


def due_priority_by_concept(*, limit: int = 200) -> dict[str, float]:
    """
    Приоритет «пора повторить» (0..1): раньше в очереди ``get_due_reviews`` — выше.
    Концепты без просроченного next_review в словарь не попадают.
    """
    due = get_due_reviews(limit=limit)
    out: dict[str, float] = {}
    for i, row in enumerate(due):
        c = str(row.get("concept") or "").strip()
        if not c or c in out:
            continue
        out[c] = max(0.0, 1.0 - i * 0.02)
    return out


def defer_overdue_reviews_for_recovery(
    kg: JsonKnowledgeGraph,
    *,
    keep_limit: int = 7,
    stagger_days: int = 5,
) -> int:
    """
    US-7.2: отложить просроченные повторения, кроме топ-keep_limit в текущем порядке очереди.
    next_review сдвигается вперёд на 1..stagger_days дней (по кругу).
    """
    from app.learner_state_scope import filter_due_reviews_for_kg

    keep_limit = max(1, min(int(keep_limit), 50))
    stagger_days = max(1, min(int(stagger_days), 14))
    due_all = filter_due_reviews_for_kg(kg, limit=500, scan_limit=500)
    if len(due_all) <= keep_limit:
        return 0
    rest = due_all[keep_limit:]
    concepts_defer = [str(r.get("concept") or "").strip() for r in rest if str(r.get("concept") or "").strip()]
    if not concepts_defer:
        return 0
    now = _utc_now()
    cutoff = now.isoformat()

    def _work(conn: sqlite3.Connection) -> int:
        _ = sync_current_learner_state_lineage(conn)
        n = 0
        for i, c in enumerate(concepts_defer):
            days_fwd = 1 + (i % stagger_days)
            next_iso = (now + timedelta(days=days_fwd)).isoformat()
            cur = conn.execute(
                """
                UPDATE spaced_repetition
                SET next_review = ?
                WHERE concept = ?
                  AND next_review IS NOT NULL
                  AND next_review <= ?
                """,
                (next_iso, c, cutoff),
            )
            n += int(cur.rowcount or 0)
        conn.commit()
        return n

    return _with_db(_work)


def due_reviews_summary_for_tutor(*, preview_limit: int = 5) -> dict[str, Any]:
    """Краткая сводка для tutor debug."""
    total = count_due_reviews()
    if total == 0:
        return {"count": 0, "hint": None, "preview_concepts": []}
    due = get_due_reviews(limit=max(1, min(int(preview_limit), _DEFAULT_DUE_QUEUE_LIMIT)))
    names = [str(d.get("concept") or "") for d in due]
    hint = (
        f"Пора повторить {total} концепций: {names[0]}"
        + (f" и ещё {total - 1}" if total > 1 else "")
    )
    return {"count": total, "hint": hint, "preview_concepts": names}


__all__ = [
    "apply_sm2",
    "count_due_reviews",
    "defer_overdue_reviews_for_recovery",
    "due_priority_reason",
    "due_priority_by_concept",
    "due_reviews_summary_for_tutor",
    "get_due_reviews",
    "record_quiz_score_for_spaced_repetition",
    "update_spaced_repetition",
]
