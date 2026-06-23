"""Виджет Personalized Learner Model 19.5 для Streamlit (прогресс, тьютор)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import streamlit as st

from app.learner_model_service import get_personalized_learner_profile

# US-8.2 — точная формулировка из doc/user_stories/us-8.2.md
US_8_2_REINDEX_BADGE_LABEL_RU = "Профиль обновлён после переиндексации"


def _parse_iso_datetime_for_badge(raw: object | None) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    s = str(raw).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def format_reindex_badge_date_display(raw_ts: object | None) -> str:
    """Дата для бейджа US-8.2: единый формат UTC (дд.мм.гггг, чч:мм UTC)."""
    dt = _parse_iso_datetime_for_badge(raw_ts)
    if dt is None:
        return "не указана"
    utc = dt.astimezone(timezone.utc)
    return utc.strftime("%d.%m.%Y, %H:%M UTC")


def reindex_profile_badge_parts(
    *,
    state_migration: dict[str, Any] | None,
    index_context: dict[str, Any] | None,
) -> tuple[str, str] | None:
    """
    US-8.2: показывать бейдж только после rehydrate mastery из истории (смена generation / индекс).

    Возвращает (заголовок, строка даты) или None.
    """
    sm = state_migration if isinstance(state_migration, dict) else None
    if not sm or sm.get("history_rehydrated") is not True:
        return None
    ix = index_context if isinstance(index_context, dict) else {}
    raw_ts = ix.get("activated_at") or sm.get("history_rehydrated_row_timestamp")
    date_display = format_reindex_badge_date_display(raw_ts)
    return (US_8_2_REINDEX_BADGE_LABEL_RU, date_display)


def render_us_8_2_reindex_badge(
    *,
    state_migration: dict[str, Any] | None,
    index_context: dict[str, Any] | None,
) -> None:
    """US-8.2: единая точка отрисовки бейджа (learner panel, Progress dashboard)."""
    parts = reindex_profile_badge_parts(
        state_migration=state_migration,
        index_context=index_context,
    )
    if not parts:
        return
    title, date_display = parts
    st.info(f"**{title}** · {date_display}", icon="🔄")

_EMOTION_RU = {
    "frustrated": "напряжение / трудно",
    "engaged": "вовлечённость",
    "confident": "уверенность",
    "bored": "скука",
    "neutral": "нейтрально",
}


def render_personalized_learner_panel(
    *,
    session_id: str | None,
    variant: Literal["full", "compact", "sidebar"] = "full",
) -> None:
    """
    Показывает cognitive_load, emotional_state, optimal_depth и опционально полный JSON.

    ``session_id`` — текущая сессия тьютора (из ``st.session_state['tutor_session_id']``), иначе None.
    """
    plm = get_personalized_learner_profile("local", session_id=session_id)
    render_us_8_2_reindex_badge(
        state_migration=plm.state_migration if isinstance(plm.state_migration, dict) else None,
        index_context=plm.index_context if isinstance(plm.index_context, dict) else None,
    )

    if variant == "sidebar":
        st.caption("🧠 Профиль (AI) · 19.5")
        _cl = float(plm.cognitive_load or 0.0)
        st.caption(f"Нагрузка **{_cl:.2f}**")
        st.progress(min(1.0, max(0.0, _cl)))
        _em = str(plm.emotional_state or "neutral")
        st.caption(f"Настроение: **{_EMOTION_RU.get(_em, _em)}**")
        st.caption(f"Глубина: **{plm.optimal_depth or 'intermediate'}**")
        with st.expander("JSON (отладка)", expanded=False):
            st.json(plm.model_dump(mode="json"))
        return

    if variant == "compact":
        with st.expander("Профиль обучения (AI) · нагрузка и глубина", expanded=False):
            p1, p2, p3 = st.columns(3)
            with p1:
                _cl = float(plm.cognitive_load or 0.0)
                st.caption("Когнитивная нагрузка (0–1)")
                st.progress(min(1.0, max(0.0, _cl)))
                st.caption(f"**{_cl:.2f}**")
            with p2:
                _em = str(plm.emotional_state or "neutral")
                st.caption("Эмоциональный фон")
                st.markdown(f"**{_EMOTION_RU.get(_em, _em)}**")
            with p3:
                st.caption("Глубина (optimal_depth)")
                st.markdown(f"**{plm.optimal_depth or 'intermediate'}**")
            st.caption(
                "Модель 19.5 · учитывается история этой сессии чата. Подробнее: «Мой прогресс» или docs/user_guide.md."
            )
            with st.expander("JSON профиля (отладка)", expanded=False):
                st.json(plm.model_dump(mode="json"))
        return

    st.subheader("Профиль обучения (AI)")
    p1, p2, p3 = st.columns(3)
    with p1:
        _cl = float(plm.cognitive_load or 0.0)
        st.metric("Когнитивная нагрузка", f"{_cl:.2f}", help="0–1: выше — сильнее нагрузка по эвристикам сессии.")
        st.progress(min(1.0, max(0.0, _cl)))
    with p2:
        _em = str(plm.emotional_state or "neutral")
        st.metric("Эмоциональный фон", _EMOTION_RU.get(_em, _em))
    with p3:
        st.metric("Глубина (optimal_depth)", str(plm.optimal_depth or "intermediate"))
    st.caption(
        "Оценки из Personalized Learner Model 19.5 (оркестратор тьютора). "
        "Учитывается текущая сессия тьютора, если вы уже открывали чат в этой вкладке браузера."
    )
    with st.expander("Отладка: полный JSON профиля", expanded=False):
        st.json(plm.model_dump(mode="json"))


__all__ = [
    "US_8_2_REINDEX_BADGE_LABEL_RU",
    "format_reindex_badge_date_display",
    "reindex_profile_badge_parts",
    "render_us_8_2_reindex_badge",
    "render_personalized_learner_panel",
]
