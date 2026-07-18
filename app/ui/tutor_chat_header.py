"""Header and metadata components for tutor chat UI."""

from __future__ import annotations

import streamlit as st

from app.ui.widgets import render_panel_header as _render_panel_header
from app.ui.continuity_bridge import e24_active_goal_line_ru as _e24_active_goal_line_ru


def render_tutor_chat_styles() -> None:
    """Render CSS styles for tutor chat (W9: motion respects reduced-motion)."""
    st.markdown(
        """
        <style>
        @keyframes tutorFadeIn {
            from { opacity: 0; transform: translateY(4px); }
            to { opacity: 1; transform: translateY(0); }
        }
        div[data-testid="stChatMessage"] {
            animation: tutorFadeIn var(--motion-default, 180ms) var(--ease-standard, ease);
        }
        @media (prefers-reduced-motion: reduce) {
            div[data-testid="stChatMessage"] {
                animation: none !important;
                transform: none !important;
            }
        }
        .tutor-nba-card {
            border: 1px solid rgba(36, 59, 44, 0.15);
            border-radius: 16px;
            padding: 0.85rem 1rem;
            background: rgba(255, 255, 255, 0.75);
            margin: 0.5rem 0 1rem 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_tutor_chat_intro(*, has_assistant_reply: bool = False) -> None:
    """Intro panel; collapses after first successful assistant reply (W9)."""
    _render_panel_header(
        "Чат с тьютором",
        "Объяснение, пример, мини-проверка и следующий шаг в одном потоке.",
    )

    from app.knowledge_service import get_active_knowledge_graph
    from app.learner_state_scope import due_reviews_summary_for_kg, filter_due_reviews_for_kg

    _kg = get_active_knowledge_graph()
    _sr = due_reviews_summary_for_kg(_kg, preview_limit=7)
    if _sr.get("count"):
        _title = f"Пора повторить: {_sr['count']} тем по расписанию"
        _overflow = str(_sr.get("overflow_caption") or "").strip()
        if _overflow:
            _title = f"{_title} · {_overflow}"
        with st.expander(_title, expanded=False):
            for d in filter_due_reviews_for_kg(_kg, limit=7):
                c = str(d.get("concept") or "").strip()
                if c:
                    st.caption(f"· {c}")
            if _overflow:
                st.caption(_overflow)
            elif _sr.get("hint"):
                st.caption(str(_sr["hint"]))

    # W9: after first reply, onboarding chrome is not a permanent banner.
    intro_body = (
        "Если разбираете домашнее задание, оставайтесь в этом же чате: попросите «подсказку», "
        "«дай план», «разбери ошибку» или «полное решение». Под ответом: "
        "«Объясни проще», «Дай пример», «Проверь меня», «Следующий шаг»."
    )
    if has_assistant_reply:
        with st.expander("Как пользоваться чатом", expanded=False):
            st.caption(intro_body)
    else:
        st.info(intro_body)


def render_tutor_active_goal() -> None:
    """Render current learning goal and tutor transparency/decision."""
    goal_lg = st.session_state.get("learning_goal")
    if goal_lg:
        _glab = {
            "understand_topic": "Понять тему",
            "exam_prep": "Подготовка к экзамену",
            "solve_homework": "Разобрать задание",
        }
        st.caption(f"Сценарий: **{_glab.get(goal_lg, goal_lg)}**")
    
    _e24_ag = _e24_active_goal_line_ru(
        current_topic=st.session_state.get("current_topic"),
        tutor_goal_desired_outcome=st.session_state.get("tutor_goal_desired_outcome"),
        tutor_goal_subtopic=st.session_state.get("tutor_goal_subtopic"),
        tutor_goal_target_level=st.session_state.get("tutor_goal_target_level"),
        tutor_goal_time_budget_min=st.session_state.get("tutor_goal_time_budget_min"),
    )
    if _e24_ag:
        st.caption(_e24_ag)

    from app.ui.tutor_mastery_forecast_panel import (
        render_tutor_transparency_badge,
        tutor_orchestration_decision_one_liner as _orch_decision_line
    )
    from app.tutor_learner_contract import load_orchestration_state as _load_orch_state

    render_tutor_transparency_badge()
    _orch_cap = _orch_decision_line(_load_orch_state())
    if _orch_cap:
        st.caption(_orch_cap)
