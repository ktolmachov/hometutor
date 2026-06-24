"""Thin Quick Answer wrapper for learner-safe routing/profile surfacing."""

from __future__ import annotations

import streamlit as st

from app.ui.continuity_bridge import (
    qa_fast_answer_panel_subtitle_ru,
    qa_fast_answer_top_caption_ru,
)
from app.ui.helpers import retrieval_route_summary, retrieval_route_summary_text
from app.ui.query_tab_answer_section import render_query_answer_section
from app.ui.query_tab_ask_panel import render_query_ask_panel
from app.ui.query_tab_poll import poll_reindex_status_for_query_tab
from app.ui.query_tab_sidebar import render_query_status_sidebar
from app.ui.tutor_mastery_forecast_panel import render_tutor_orchestration_snapshot_expander
from app.ui.widgets import render_panel_header


def _render_profile_copy() -> None:
    route = retrieval_route_summary(st.session_state.get("last_debug") or {})
    effective_label = str(route.get("effective_label") or "").strip()
    if effective_label:
        st.caption(
            f"Профиль ответа сейчас: {effective_label}. "
            "Это выбор маршрута поиска по материалам, а не подсказка следующего учебного шага."
        )
        return
    st.caption(
        "Профиль ответа относится к поиску по вашим материалам. "
        "Подсказка, с чего продолжить обучение, показывается отдельно."
    )


def _render_route_badge() -> None:
    summary = retrieval_route_summary_text(st.session_state.get("last_debug") or {})
    if not summary:
        return
    st.markdown(
        (
            '<div style="margin:0.6rem 0 0.9rem 0;padding:0.75rem 0.9rem;'
            'border:1px solid rgba(62, 109, 88, 0.18);border-radius:14px;'
            'background:rgba(62, 109, 88, 0.06);">'
            f"<strong>Почему этот маршрут.</strong> {summary.removeprefix('Почему этот маршрут: ').strip()}"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_quick_answer_tab(
    folder: str,
    folder_rel: str,
    file_name: str,
    relative_path: str,
    topic_quick: str,
    folder_quick: str,
) -> None:
    poll_reindex_status_for_query_tab()
    st.markdown('<div class="panel qa-mot3-handoff-source">', unsafe_allow_html=True)
    st.caption(qa_fast_answer_top_caption_ru())
    render_panel_header("Быстрый ответ", qa_fast_answer_panel_subtitle_ru())
    _render_profile_copy()
    render_tutor_orchestration_snapshot_expander(key_prefix="quick_answer", show_focus_concept=True)
    left, right = st.columns([1.5, 1], gap="large")
    with left:
        render_query_ask_panel(
            folder,
            folder_rel,
            file_name,
            relative_path,
            topic_quick,
            folder_quick,
        )
    with right:
        render_query_status_sidebar()
    _render_route_badge()
    render_query_answer_section()
    st.markdown("</div>", unsafe_allow_html=True)
