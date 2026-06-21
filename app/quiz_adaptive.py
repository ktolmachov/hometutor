"""
Адаптивная сложность inline quiz: recognition → recall → transfer (P1).

Состояние в ``quiz_mastery`` (user_state.db); обновление после оценки ответа
(``evaluate_inline_quiz_answer``), опирается на ``quiz_results`` косвенно через порог score.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.user_state import _utc_now_iso, _with_db, sync_current_learner_state_lineage

LEVELS = ("recognition", "recall", "transfer")
SUCCESS_THRESHOLD = 0.7

# Согласовано с ``estimate_mastery_percent`` в ``quiz_service`` (мотивация / scoring).
LEVEL_TO_MASTERY_PCT: dict[str, int] = {
    "recognition": 44,
    "recall": 68,
    "transfer": 82,
}


def mastery_percent_for_level(level: str | None) -> int:
    lv = (level or "recognition").strip().lower()
    return LEVEL_TO_MASTERY_PCT.get(lv, 44)


def get_weak_concepts(*, threshold: int = 60, limit: int = 12) -> list[str]:
    """
    Концепты с оценкой освоения ниже порога (по ``quiz_mastery.current_level``).
    Сортировка: сначала самые слабые.
    """
    thr = max(0, min(100, int(threshold)))
    lim = max(1, min(50, int(limit)))
    rows: list[tuple[str, int]] = []
    for row in list_quiz_mastery_state():
        c = str(row.get("concept") or "").strip()
        if not c:
            continue
        lv = str(row.get("current_level") or "recognition").strip().lower()
        pct = mastery_percent_for_level(lv)
        if pct < thr:
            rows.append((c, pct))
    rows.sort(key=lambda x: x[1])
    out: list[str] = []
    for c, _ in rows:
        if c not in out:
            out.append(c)
        if len(out) >= lim:
            break
    return out


def _normalize_concept(concept: str) -> str:
    return (concept or "").strip() or "general"


def get_recommended_difficulty(concept: str) -> str:
    """Текущий целевой уровень для концепции (по таблице ``quiz_mastery``)."""

    c = _normalize_concept(concept)

    def _work(conn: sqlite3.Connection) -> str:
        lineage = sync_current_learner_state_lineage(conn)
        current_generation_id = str(lineage.get("generation_id") or "").strip()
        row = conn.execute(
            """
            SELECT current_level FROM quiz_mastery
            WHERE concept = ? AND (? IS NULL OR generation_id = ?)
            """,
            (c, current_generation_id or None, current_generation_id or None),
        ).fetchone()
        if not row:
            return "recognition"
        lv = str(row["current_level"] or "recognition").strip().lower()
        return lv if lv in LEVELS else "recognition"

    return _with_db(_work)


def update_mastery_after_score(
    concept: str,
    score: float,
    *,
    provenance: Any | None = None,
) -> dict[str, Any]:
    """
    После оценки quiz: при score >= SUCCESS_THRESHOLD засчитываем успех; иначе откат.

    Правила: 2 успеха подряд → уровень выше (recognition→recall→transfer), streak сбрасывается;
    неуспех → уровень на шаг ниже, streak=0.
    """
    from app.fact_source_binding import (
        provenance_to_dict,
        require_fact_provenance,
        set_last_mastery_provenance,
    )

    c = _normalize_concept(concept)
    success = float(score) >= SUCCESS_THRESHOLD
    validated_provenance = require_fact_provenance(
        provenance,
        operation="update_mastery_after_score",
    )

    def _work(conn: sqlite3.Connection) -> dict[str, Any]:
        lineage = sync_current_learner_state_lineage(conn)
        current_generation_id = str(lineage.get("generation_id") or "").strip() or None
        current_index_version = lineage.get("index_version")
        row = conn.execute(
            """
            SELECT current_level, success_streak FROM quiz_mastery WHERE concept = ?
            AND (? IS NULL OR generation_id = ?)
            """,
            (c, current_generation_id, current_generation_id),
        ).fetchone()
        if row:
            level = str(row["current_level"] or "recognition").strip().lower()
            if level not in LEVELS:
                level = "recognition"
            streak = int(row["success_streak"] or 0)
        else:
            level = "recognition"
            streak = 0

        new_level = level
        new_streak = streak

        if success:
            new_streak = streak + 1
            if new_streak >= 2:
                if level == "recognition":
                    new_level = "recall"
                elif level == "recall":
                    new_level = "transfer"
                else:
                    new_level = "transfer"
                new_streak = 0
        else:
            new_streak = 0
            if level == "transfer":
                new_level = "recall"
            elif level == "recall":
                new_level = "recognition"
            else:
                new_level = "recognition"

        ts = _utc_now_iso()
        conn.execute(
            """
            INSERT INTO quiz_mastery(
                concept, current_level, success_streak, last_updated, generation_id, index_version
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(concept) DO UPDATE SET
                current_level = excluded.current_level,
                success_streak = excluded.success_streak,
                last_updated = excluded.last_updated,
                generation_id = excluded.generation_id,
                index_version = excluded.index_version
            """,
            (c, new_level, new_streak, ts, current_generation_id, current_index_version),
        )
        conn.commit()
        result = {
            "concept": c,
            "current_level": new_level,
            "success_streak": new_streak,
            "success_threshold": SUCCESS_THRESHOLD,
            "last_attempt_success": success,
            "generation_id": current_generation_id,
            "index_version": current_index_version,
            "provenance": provenance_to_dict(validated_provenance),
        }
        return result

    out = _with_db(_work)
    set_last_mastery_provenance(validated_provenance)
    return out


def _normalize_level_cell(raw: str | None) -> str:
    lv = (raw or "recognition").strip().lower()
    return lv if lv in LEVELS else "recognition"


def list_quiz_mastery_state() -> list[dict[str, Any]]:
    """Все строки ``quiz_mastery`` (concept, current_level, success_streak, last_updated)."""

    def _work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        lineage = sync_current_learner_state_lineage(conn)
        current_generation_id = str(lineage.get("generation_id") or "").strip()
        where = ""
        params: list[Any] = []
        if current_generation_id:
            where = "WHERE generation_id = ?"
            params.append(current_generation_id)
        rows = conn.execute(
            f"""
            SELECT concept, current_level, success_streak, last_updated,
                   generation_id, index_version
            FROM quiz_mastery
            {where}
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    return _with_db(_work)


def _normalize_quiz_error_level(raw: str) -> str:
    x = (raw or "").strip().lower()
    if x == "application":
        return "transfer"
    return x


def mastery_label_from_vector_level(vector_level: str | None) -> str | None:
    """Подпись уровня для промпта: recognition→beginner, recall→intermediate, transfer→advanced."""
    vl = (vector_level or "").strip().lower()
    if vl not in LEVELS:
        return None
    return {"recognition": "beginner", "recall": "intermediate", "transfer": "advanced"}[vl]


def choose_micro_quiz_difficulty(
    mastery_level: str,
    recent_error_types: list[str] | None,
    *,
    vector_level: str | None = None,
) -> str:
    """
    Полоса сложности micro-quiz (easy / medium / hard) для промпта LLM.

    При ``vector_level`` из mastery vector (recognition / recall / transfer) — основной сигнал:
    recognition→easy, recall→medium, transfer→hard.
    Иначе — fallback по tutor bands (beginner / intermediate / advanced).

    Недавние слабые попытки (``recent_error_types``) смягчают полосу: ошибки на
    recognition-level → easy; ошибки на transfer — на шаг ниже.
    """
    recent_raw = [str(x).strip().lower() for x in (recent_error_types or []) if str(x).strip()]
    recent = [_normalize_quiz_error_level(x) for x in recent_raw]

    vl = (vector_level or "").strip().lower()
    use_vector = vl in LEVELS

    if use_vector:
        base = {"recognition": "easy", "recall": "medium", "transfer": "hard"}[vl]
    else:
        ml = (mastery_level or "intermediate").strip().lower()
        if ml == "beginner":
            base = "easy"
        elif ml == "advanced":
            base = "hard"
        else:
            base = "medium"

    if "recognition" in recent:
        return "easy"

    soften = {"hard": "medium", "medium": "easy", "easy": "easy"}
    if "transfer" in recent or "application" in recent_raw:
        return soften.get(base, base)

    if not use_vector:
        ml = (mastery_level or "intermediate").strip().lower()
        if ml == "advanced" and not recent:
            return "hard"
        if ml == "beginner":
            return "easy"

    return base


def diagnose_quiz_result(
    user_answer: str,
    correct_option: str,
    question_type: str,
) -> dict[str, str]:
    """
    Диагностика ответа на micro-quiz (буква A–D).
    question_type: recognition | recall | application (или recognition/recall/transfer из LLM).
    """
    ua = (user_answer or "").strip().upper()[:1]
    co = (correct_option or "").strip().upper()[:1]
    qt = (question_type or "application").strip().lower()
    if qt == "transfer":
        qt = "application"

    if ua and co and ua == co:
        return {
            "status": "correct",
            "message": "Отлично: верный ответ, концепция применена правильно.",
            "mastery_update": "+1",
        }

    error_map = {
        "recognition": "Похоже, перепутаны термины или варианты узнавания; идея может быть близка.",
        "recall": "Идея понятна, но формулировка или термин вспомнились не полностью.",
        "application": "Теория знакома, но перенос на пример или контекст пока слабее.",
    }
    msg = error_map.get(qt, "Есть пробел в понимании; стоит вернуться к определению или примеру.")
    rec = "Повтори пример из базы" if qt == "application" else "Прочитай определение ещё раз"
    return {
        "status": "incorrect",
        "message": msg,
        "mastery_update": "-1",
        "recommended_action": rec,
    }


def get_adaptive_difficulty(difficulty: str, concept_identifier: str) -> str:
    """
    Уровень для scoped-quiz: ``adaptive`` → рекомендация из ``quiz_mastery``,
    иначе явный ``recognition`` / ``recall`` / ``transfer``.
    """
    d = (difficulty or "adaptive").strip().lower()
    if d == "adaptive":
        return get_recommended_difficulty(concept_identifier)
    if d in LEVELS:
        return d
    return "recognition"


def get_all_mastery_levels() -> dict[str, str]:
    """Словарь ``concept_id -> current_level`` (recognition / recall / transfer)."""

    out: dict[str, str] = {}
    for row in list_quiz_mastery_state():
        c = str(row.get("concept") or "").strip()
        if not c:
            continue
        out[c] = _normalize_level_cell(str(row.get("current_level")))
    return out


__all__ = [
    "SUCCESS_THRESHOLD",
    "LEVEL_TO_MASTERY_PCT",
    "get_adaptive_difficulty",
    "choose_micro_quiz_difficulty",
    "mastery_label_from_vector_level",
    "diagnose_quiz_result",
    "get_all_mastery_levels",
    "get_recommended_difficulty",
    "get_weak_concepts",
    "LEVELS",
    "list_quiz_mastery_state",
    "mastery_percent_for_level",
    "update_mastery_after_score",
]
