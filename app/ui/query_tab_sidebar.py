"""Правая узкая колонка статуса ответа на вкладке Q&A (P5c split)."""

from __future__ import annotations

import streamlit as st

from app.ui.continuity_bridge import (
    qa_tab_empty_state_callout_html_ru,
    qa_tab_expert_pointer_caption_ru,
)
from app.ui.helpers import llm_source_badge_text, llm_source_privacy_notice
from app.ui.query_tab_helpers import answer_latency_caption


def render_query_status_sidebar() -> None:
    last = st.session_state.get("last_answer")
    if last:
        st.markdown('<div class="callout">', unsafe_allow_html=True)
        st.markdown("#### Текущее состояние ответа")
        debug = st.session_state.get("last_debug") or {}
        source_badge = llm_source_badge_text(debug)
        if source_badge:
            st.caption(source_badge)
        source_notice = llm_source_privacy_notice(debug)
        if source_notice:
            st.caption(source_notice)
        lat_top = answer_latency_caption(debug)
        if lat_top:
            st.caption(lat_top)
        st.caption(qa_tab_expert_pointer_caption_ru())
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.markdown(qa_tab_empty_state_callout_html_ru(), unsafe_allow_html=True)
