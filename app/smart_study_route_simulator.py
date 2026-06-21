"""Local Route Simulator — what-if preview for Smart Study Router alternatives.

Pure deterministic module. No DB writes, no cloud API calls, no side effects.
Given the current SmartStudyRecommendation and a secondary action_id,
produces a SimulatedRoute with counterfactual primary label, reason, or limitation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.smart_study_recommendation import (
    SmartStudyPrimaryNav,
    SmartStudyRecommendation,
)


@dataclass(frozen=True)
class SimulatedRoute:
    """Deterministic what-if simulation result for a secondary SSR action."""

    counterfactual_primary_label_ru: str = ""
    reason_ru: str = ""
    limitation_reason: str = ""
    signals_summary: dict[str, Any] = field(default_factory=dict)


_KNOWN_SECONDARY_MAP: dict[str, tuple[str, SmartStudyPrimaryNav]] = {
    "qa_sources": ("Свериться с источниками", "qa_continue"),
    "tutor_simpler": ("Короткий разговор с тьютором", "safe_tutor_5min"),
    "quiz_nav": ("Пройти интерактивный quiz", "quiz_recovery_tutor"),
    "progress_go": ("Открыть экран прогресса обучения", "flashcards_review"),
    "fc_create": ("Создать flashcard-карточку", "flashcards_review"),
}

_LIMITATION_UNKNOWN_SECONDARY = (
    "Нет данных для моделирования этого маршрута."
)

_LADDER_STEP_AUDIT_RE = re.compile(r"recovery_ladder_step=(\d+)")


def _recovery_ladder_step_from_audit(ml_audit_ru: str | None) -> int | None:
    """Парсит шаг из ml_audit строки SSR (совпадает с overlay smart_study_router)."""
    m = _LADDER_STEP_AUDIT_RE.search(str(ml_audit_ru or ""))
    if not m:
        return None
    k = int(m.group(1))
    return k if 1 <= k <= 4 else None


def _recovery_ladder_why_hint_ru(step: int, secondary_action_id: str) -> str:
    """Согласование what-if текста с подписями ``_recovery_ladder_secondaries``."""
    # Локальный import: симулятор не тянет тяжёлый модуль роутера на уровень пакета.
    from app.smart_study_recovery_ladder import _recovery_ladder_secondaries

    for sec in _recovery_ladder_secondaries(step):
        if sec.action_id == secondary_action_id:
            return f"Подсказка лестницы (шаг {step}): {sec.label_ru}"
    return f"Подсказка лестницы восстановления, шаг {step}."


def _enrich_reason_with_recovery_ladder(
    rec: SmartStudyRecommendation,
    secondary_action_id: str,
    reason_ru: str,
) -> str:
    if str(rec.hint_kind) != "quiz_failed":
        return reason_ru
    step = _recovery_ladder_step_from_audit(rec.ml_audit_ru)
    if step is None:
        return reason_ru
    head = _recovery_ladder_why_hint_ru(step, secondary_action_id)
    return f"{head}\n\n{reason_ru}"


_ALREADY_PRIMARY_REASON = "Этот маршрут уже является основным."

_WHY_NOW_TRUNCATE = 60


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def _build_signals_summary(rec: SmartStudyRecommendation) -> dict[str, Any]:
    return {
        "hint_kind": str(rec.hint_kind),
        "primary_nav": str(rec.primary_nav),
        "why_now_preview": _truncate(rec.why_now_ru, _WHY_NOW_TRUNCATE),
    }


def simulate_what_if(
    rec: SmartStudyRecommendation,
    secondary_action_id: str,
) -> SimulatedRoute:
    """Produce a what-if SimulatedRoute for a given secondary action.

    Args:
        rec: Current SSR recommendation (frozen dataclass, not mutated).
        secondary_action_id: One of the known action_ids from
            SmartStudySecondaryAction (e.g. 'qa_sources', 'tutor_simpler').

    Returns:
        SimulatedRoute with counterfactual label, reason, or limitation.
        Never raises; always returns a valid SimulatedRoute.
    """
    signals = _build_signals_summary(rec)

    # Unknown secondary → limitation.
    if secondary_action_id not in _KNOWN_SECONDARY_MAP:
        return SimulatedRoute(
            limitation_reason=_LIMITATION_UNKNOWN_SECONDARY,
            signals_summary=signals,
        )

    cf_label, cf_nav = _KNOWN_SECONDARY_MAP[secondary_action_id]

    # Safe default surface: узких очередных сигналов мало, но UX what-if нужен без «пустого» блока.
    if str(rec.hint_kind) == "safe_default":
        if str(rec.primary_nav) == cf_nav:
            return SimulatedRoute(
                counterfactual_primary_label_ru=cf_label,
                reason_ru=_enrich_reason_with_recovery_ladder(
                    rec,
                    secondary_action_id,
                    _ALREADY_PRIMARY_REASON,
                ),
                signals_summary=signals,
            )
        return SimulatedRoute(
            counterfactual_primary_label_ru=cf_label,
            reason_ru=_enrich_reason_with_recovery_ladder(
                rec,
                secondary_action_id,
                (
                    "Сейчас маршрут обобщённый (мало узких локальных сигналов очередей). "
                    "При переходе в выбранный режим главный шаг временно изменится без точного "
                    "прогноза относительной приоритизации карточек и SM‑2."
                ),
            ),
            signals_summary=signals,
        )

    # Already the current primary.
    if str(rec.primary_nav) == cf_nav:
        return SimulatedRoute(
            counterfactual_primary_label_ru=cf_label,
            reason_ru=_enrich_reason_with_recovery_ladder(
                rec,
                secondary_action_id,
                _ALREADY_PRIMARY_REASON,
            ),
            signals_summary=signals,
        )

    # Build reason based on current hint_kind.
    hk = str(rec.hint_kind)
    if secondary_action_id == "qa_sources":
        reason = (
            f"Сейчас сигнал «{hk}» указывает на другой приоритет, "
            f"но при выборе режима источников маршрут сместится "
            f"к проверке фактов по индексу."
        )
    elif secondary_action_id == "tutor_simpler":
        reason = (
            f"Несмотря на сигнал «{hk}», если переключиться в свободный "
            f"чат тьютора, рекомендация изменится на короткое объяснение "
            f"без привязки к текущей очереди."
        )
    elif secondary_action_id == "quiz_nav":
        reason = (
            f"Вместо следования сигналу «{hk}», переход в интерактивный "
            f"quiz переключит фокус на проверку знаний."
        )
    elif secondary_action_id in ("progress_go", "fc_create"):
        reason = (
            f"Вместо текущего маршрута по сигналу «{hk}», "
            f"режим повторения и прогресса предложит обзор "
            f"учебной статистики и карточек."
        )
    else:
        reason = (
            f"При выборе альтернативного режима, маршрут сменится "
            f"с учётом текущих локальных сигналов."
        )

    return SimulatedRoute(
        counterfactual_primary_label_ru=cf_label,
        reason_ru=_enrich_reason_with_recovery_ladder(rec, secondary_action_id, reason),
        signals_summary=signals,
    )


__all__ = [
    "SimulatedRoute",
    "simulate_what_if",
]
