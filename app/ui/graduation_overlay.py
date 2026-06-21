"""Concept graduation ceremony overlay — skippable celebration + E30 stub API."""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.course_metrics import record_course_workflow_event
from app.gamification_service import record_concept_graduation_badge

MASTERY_CELEBRATION_THRESHOLD = 80.0

SESSION_SKIP_KEY = "graduation_celebration_skipped"


def mastery_qualifies_for_celebration(mastery_pct: float | None) -> bool:
    """US-19.3: показ поверхности при мастеринге ≥80 %."""
    if mastery_pct is None:
        return False
    try:
        return float(mastery_pct) >= MASTERY_CELEBRATION_THRESHOLD
    except (TypeError, ValueError):
        return False


def build_graduation_celebration_view_model(
    *,
    concept_title: str,
    mastery_pct: float | None,
    session_count: int | None = None,
    minutes_spent: float | None = None,
) -> dict[str, Any]:
    """Плоская модель для UI; при отсутствии метрик — деградация до простого успеха."""
    title = (concept_title or "").strip() or "тема"
    headline = graduation_headline(title)
    degraded = session_count is None and minutes_spent is None
    mastery_line: str
    if mastery_pct is None:
        mastery_line = "Итоговое мастерство: —"
    else:
        try:
            m = max(0.0, min(100.0, float(mastery_pct)))
            mastery_line = f"Итоговое мастерство: {m:.0f}%"
        except (TypeError, ValueError):
            mastery_line = "Итоговое мастерство: —"
            degraded = True
    lines: list[str] = [f"Тема: «{title}»", mastery_line]
    if session_count is not None:
        lines.append(f"Завершённых учебных сессий: {int(session_count)}")
    elif degraded:
        lines.append("Сессии: нет данных — показываем краткое поздравление.")
    else:
        lines.append("Завершённых учебных сессий: —")
    if minutes_spent is not None:
        try:
            lines.append(f"Время в теме: {float(minutes_spent):.1f} мин")
        except (TypeError, ValueError):
            lines.append("Время в теме: —")
            degraded = True
    ctas = ("Следующая тема", "Разобрать слабые места", "На главную")
    return {
        "headline": headline,
        "detail_lines": lines,
        "primary_cta_labels": list(ctas),
        "degraded_simple": degraded,
    }


def graduation_headline(concept_title: str) -> str:
    """Текст заголовка церемонии (юнит-тестируемый)."""
    name = (concept_title or "").strip() or "концепт"
    return f"Поздравляем: «{name}» зафиксирован как освоенный."


def log_concept_graduation_stub(scope: dict[str, Any] | None, *, concept_title: str = "") -> None:
    """Пишет workflow-событие для последующей аналитики (пока без реальной анимации)."""
    record_course_workflow_event(
        "concept_graduation_event",
        scope,
        payload={"stub": True, "concept_title": (concept_title or "").strip()},
    )


def render_skippable_graduation_celebration(
    *,
    concept_title: str = "",
    mastery_pct: float | None = None,
    session_count: int | None = None,
    minutes_spent: float | None = None,
) -> None:
    """
    Поверхность выпуска: бейдж в KV, пропуск celebration, три next-step CTA (кнопки-заглушки).
    """
    if not mastery_qualifies_for_celebration(mastery_pct):
        return
    record_concept_graduation_badge()
    if st.session_state.get(SESSION_SKIP_KEY):
        return
    vm = build_graduation_celebration_view_model(
        concept_title=concept_title,
        mastery_pct=mastery_pct,
        session_count=session_count,
        minutes_spent=minutes_spent,
    )
    st.success(vm["headline"])
    for line in vm["detail_lines"][1:]:
        st.caption(line)
    if vm["degraded_simple"]:
        st.caption("Расширенные метрики недоступны — продолжайте без лишних шагов.")
    if st.button("Пропустить celebration", key="graduation_celebration_skip"):
        st.session_state[SESSION_SKIP_KEY] = True
        st.rerun()
    c1, c2, c3 = st.columns(3)
    labels = vm["primary_cta_labels"]
    with c1:
        st.button(labels[0], key="graduation_cta_next_topic")
    with c2:
        st.button(labels[1], key="graduation_cta_weak")
    with c3:
        st.button(labels[2], key="graduation_cta_home")


def render_graduation_overlay_stub(*, concept_title: str = "Демо-концепт") -> None:
    """Минимальный overlay: текст + кнопка закрытия (Streamlit)."""
    st.success(graduation_headline(concept_title))
    st.caption("E30 B1: позже — 3s ceremony, Path Map animation.")
    if st.button("Закрыть overlay", key="graduation_overlay_close_stub"):
        st.session_state.pop("graduation_overlay_open", None)
        st.rerun()


__all__ = [
    "MASTERY_CELEBRATION_THRESHOLD",
    "SESSION_SKIP_KEY",
    "build_graduation_celebration_view_model",
    "graduation_headline",
    "log_concept_graduation_stub",
    "mastery_qualifies_for_celebration",
    "render_graduation_overlay_stub",
    "render_skippable_graduation_celebration",
]
