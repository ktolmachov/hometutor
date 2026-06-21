"""Concept Recovery Ladder contract (US-20.1): overlay, resume blob, persistence helpers."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.smart_study_recommendation import (
    SmartStudyRecommendation,
    SmartStudySecondaryAction,
    _quiz_feedback_failed,
)
from app.smart_study_scoring import _SSR_ROUTE_PEDAGOGY_WEAK_CONCEPT_RU

_RECOVERY_LADDER_MAX_STEP = 4
_VARIANT_SUCCESS_STATUSES = frozenset({"correct", "ok", "good", "right"})


def normalize_concept_anchor(raw: Any) -> str:
    """Normalized concept anchor for mismatch checks (trim, lower, max 240)."""
    return str(raw or "").strip().lower()[:240]


def anchors_match(a: Any, b: Any) -> bool:
    """True when both anchors normalize to the same non-empty string."""
    na = normalize_concept_anchor(a)
    nb = normalize_concept_anchor(b)
    if not na or not nb:
        return False
    return na == nb


def normalize_concept_recovery_ladder_step(raw: Any, *, default: int = 1) -> int:
    """Приводит шаг лестницы восстановления к диапазону 1–4 для quiz_failed SSR."""
    if raw is None:
        return int(default)
    try:
        s = int(raw)
    except (TypeError, ValueError):
        return int(default)
    return max(1, min(_RECOVERY_LADDER_MAX_STEP, s))


def concept_recovery_resume_v1(
    step: int,
    *,
    concept_anchor: str = "",
    scope_id: str | None = None,
) -> dict[str, Any]:
    """JSON-serialize friendly blob для сохранения шага между сессиями (Streamlit/UI)."""
    blob: dict[str, Any] = {
        "v": 1,
        "step": normalize_concept_recovery_ladder_step(step, default=1),
        "anchor": str(concept_anchor or "").strip()[:240],
    }
    if scope_id is not None:
        sid = str(scope_id).strip()[:120]
        if sid:
            blob["scope_id"] = sid
    return blob


def ladder_step_from_resume_v1(blob: dict[str, Any] | None, *, default: int = 1) -> int:
    """Извлекает шаг из ``concept_recovery_resume_v1`` или default."""
    if not isinstance(blob, dict):
        return int(default)
    if int(blob.get("v") or 0) != 1:
        return int(default)
    return normalize_concept_recovery_ladder_step(blob.get("step"), default=default)


def advance_concept_recovery_ladder_step(step: int, *, delta: int = 1) -> int:
    """Product step advance helper (sp2 navigation consumer)."""
    return normalize_concept_recovery_ladder_step(int(step) + int(delta))


def _recovery_ladder_secondaries(step: int) -> tuple[SmartStudySecondaryAction, ...]:
    """Вторичные действия лестницы (короткие «почему дальше» в label_ru).

    Префиксы «Открыть / Попросить / Создать» совпадают со stable secondaries SSR,
    чтобы кнопки оставались узнаваемыми для E2E и скринридеров.
    """
    qa_ex = SmartStudySecondaryAction(
        "qa_sources",
        "Открыть выдержки и разобранный пример (шаг 2 лестницы восстановления)",
    )
    tutor_full = SmartStudySecondaryAction(
        "tutor_simpler",
        "Попросить связный разбор ошибки у тьютора (шаг 3 лестницы восстановления)",
    )
    quiz_var = SmartStudySecondaryAction(
        "quiz_nav",
        "Открыть интерактивный quiz для закрепления (шаг 4 лестницы восстановления)",
    )
    fc_lock = SmartStudySecondaryAction(
        "fc_create",
        "Создать карточку-якорь после успешной проверки",
    )
    prog = SmartStudySecondaryAction(
        "progress_go",
        "Открыть экран прогресса (обход конфликта с очередями повторений)",
    )

    if step <= 1:
        return (qa_ex, tutor_full, quiz_var, prog)
    if step == 2:
        return (tutor_full, quiz_var, fc_lock, prog)
    if step == 3:
        return (quiz_var, fc_lock, qa_ex, tutor_full)
    return (quiz_var, fc_lock, qa_ex, prog)


def apply_concept_recovery_ladder_overlay(
    rec: SmartStudyRecommendation,
    *,
    quiz_feedback_status: str | None,
    concept_recovery_ladder_step: int | None,
    concept_recovery_ladder_enabled: bool = True,
    tutor_topic: str | None,
) -> SmartStudyRecommendation:
    # Правило vs source_coverage guard (Analyst Escalations / US-20.1 Outcome 1):
    # если guard уже перевёл primary в qa_continue («сверка с источниками»), не
    # переписываем заголовки/why_now/route_pedagogy guard-ветки — только
    # secondaries суффиксами лестницы + audit для UI/what-if/trace.
    if (
        not concept_recovery_ladder_enabled
        or not _quiz_feedback_failed(quiz_feedback_status)
        or rec.hint_kind != "quiz_failed"
    ):
        return rec

    audit_ru = str(rec.ml_audit_ru or "")
    guard_keeps_primary = (
        rec.primary_nav == "qa_continue" and "source_coverage_route_guard=1" in audit_ru
    )
    if rec.primary_nav != "quiz_recovery_tutor" and not guard_keeps_primary:
        return rec

    step = normalize_concept_recovery_ladder_step(concept_recovery_ladder_step, default=1)
    audit = (audit_ru.strip() + f" recovery_ladder_step={step} recovery_ladder_v=1".strip()).strip()

    if guard_keeps_primary:
        guard_audit = (audit + " recovery_ladder_guard_keeps_primary=1").strip()
        return replace(
            rec,
            secondaries=_recovery_ladder_secondaries(step),
            ml_audit_ru=guard_audit,
        )

    topic = str(tutor_topic or "").strip()
    if step <= 1:
        return replace(
            rec,
            primary_nav="qa_continue",
            primary_label_ru="Короткая подсказка по ошибке",
            why_now_ru=(
                "Лестница восстановления, шаг 1: локальный сигнал quiz_failed сохранён, но сразу тащить вас "
                "в полный диалог тьютора — туго; сначала откройте быстрый ответ или цитату с мягкой наводкой без "
                "длинной сессии, чтобы не закрепить угадайку."
            ),
            route_pedagogy_ru=_SSR_ROUTE_PEDAGOGY_WEAK_CONCEPT_RU,
            secondaries=_recovery_ladder_secondaries(1),
            ml_audit_ru=audit,
        )
    if step == 2:
        return replace(
            rec,
            primary_nav="qa_continue",
            primary_label_ru="Выдержка с разобранным примером",
            why_now_ru=(
                "Шаг 2 лестницы восстановления: опираемся на готовые выдержки и разобранный шаблон задачи перед "
                "живым диалогом; так проще синхронизировать модель ошибки из мини-проверки."
            ),
            route_pedagogy_ru=_SSR_ROUTE_PEDAGOGY_WEAK_CONCEPT_RU,
            secondaries=_recovery_ladder_secondaries(2),
            ml_audit_ru=audit,
        )
    if step == 3:
        return replace(
            rec,
            primary_nav="quiz_recovery_tutor",
            primary_label_ru="Разбор ошибки с тьютором",
            why_now_ru=(
                "Шаг 3 лестницы восстановления: после подсказки и статического разбора — короткая диалоговая "
                "сессия закрепляет слабое место перед новой попыткой мини-проверки."
            ),
            route_pedagogy_ru=_SSR_ROUTE_PEDAGOGY_WEAK_CONCEPT_RU,
            secondaries=_recovery_ladder_secondaries(3),
            ml_audit_ru=audit,
        )

    concept = topic or "текущую тему"
    return replace(
        rec,
        primary_nav="tutor_weak_gap",
        primary_label_ru="Похожая задача — проверить перенос",
        why_now_ru=(
            f"Шаг 4 лестницы восстановления: проверить перенос на вариант близкой задачи по «{concept}» перед "
            "финальной интерактивной попыткой; после успеха лестницу нужно явно обнулить."
        ),
        route_pedagogy_ru=_SSR_ROUTE_PEDAGOGY_WEAK_CONCEPT_RU,
        secondaries=_recovery_ladder_secondaries(4),
        ml_audit_ru=audit,
    )


def invalidate_concept_recovery_ladder_on_scope_change(
    blob: dict[str, Any] | None,
    *,
    active_scope_id: str | None,
) -> dict[str, Any] | None:
    """Returns None when stored scope_id differs from active scope (caller clears ladder)."""
    if not isinstance(blob, dict) or not blob:
        return None
    stored = str(blob.get("scope_id") or "").strip()
    active = str(active_scope_id or "").strip()
    if stored and active and stored != active:
        return None
    return dict(blob)


def reconcile_concept_recovery_ladder_anchor(
    blob: dict[str, Any] | None,
    *,
    current_anchor: str,
    scope_id: str | None = None,
) -> tuple[int, dict[str, Any] | None]:
    """Hard reset to step 1 on anchor mismatch; returns (resolved_step, blob_to_persist)."""
    current = normalize_concept_anchor(current_anchor)
    if not isinstance(blob, dict) or not blob:
        if current:
            return 1, concept_recovery_resume_v1(1, concept_anchor=current_anchor, scope_id=scope_id)
        return 1, None

    stored = normalize_concept_anchor(blob.get("anchor"))
    step = ladder_step_from_resume_v1(blob)
    if stored and current and stored != current:
        return 1, concept_recovery_resume_v1(1, concept_anchor=current_anchor, scope_id=scope_id)
    return step, dict(blob)


def should_clear_ladder_on_variant_quiz_success(
    *,
    quiz_feedback_status: str | None,
    quiz_concept: str | None,
    ladder_blob: dict[str, Any] | None,
    ladder_step: int | None = None,
    last_ssr_primary: str | None = None,
) -> bool:
    """Predicate for variant-quiz success reset (sp2 UI hook consumer)."""
    status = str(quiz_feedback_status or "").strip().lower()
    if status not in _VARIANT_SUCCESS_STATUSES:
        return False
    if not isinstance(ladder_blob, dict) or not ladder_blob:
        return False
    if not anchors_match(quiz_concept, ladder_blob.get("anchor")):
        return False
    step = (
        normalize_concept_recovery_ladder_step(ladder_step)
        if ladder_step is not None
        else ladder_step_from_resume_v1(ladder_blob)
    )
    if step >= 4:
        return True
    primary = str(last_ssr_primary or "").strip()
    return primary in ("tutor_weak_gap", "quiz_recovery_tutor") and step >= 3


def clear_concept_recovery_ladder_session() -> dict[str, Any]:
    """Session-state patch to reset ladder mirror (sp2 consumer)."""
    return {
        "concept_recovery_ladder_step": 1,
        "concept_recovery_resume_v1": None,
    }


__all__ = [
    "advance_concept_recovery_ladder_step",
    "anchors_match",
    "apply_concept_recovery_ladder_overlay",
    "clear_concept_recovery_ladder_session",
    "concept_recovery_resume_v1",
    "invalidate_concept_recovery_ladder_on_scope_change",
    "ladder_step_from_resume_v1",
    "normalize_concept_anchor",
    "normalize_concept_recovery_ladder_step",
    "reconcile_concept_recovery_ladder_anchor",
    "should_clear_ladder_on_variant_quiz_success",
]
