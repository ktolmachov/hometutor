"""Вкладка «Быстрый ответ» (Q&A по базе)."""
from __future__ import annotations

import streamlit as st

from app.ui.continuity_bridge import (
    qa_fast_answer_panel_subtitle_ru,
    qa_fast_answer_top_caption_ru,
)
from app.ui.query_tab_answer_section import render_query_answer_section
from app.ui.query_tab_ask_panel import render_query_ask_panel
from app.ui.query_tab_poll import poll_reindex_status_for_query_tab
from app.ui.query_tab_sidebar import render_query_status_sidebar
from app.ui.tutor_mastery_forecast_panel import render_tutor_orchestration_snapshot_expander
from app.ui.widgets import render_panel_header


def render_query_tab(
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
    render_tutor_orchestration_snapshot_expander(key_prefix="query_tab", show_focus_concept=True)
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
    render_query_answer_section()
    st.markdown("</div>", unsafe_allow_html=True)


# Back-compat для unit-тестов (исторические имена с префиксом _)
from app.ui.query_tab_helpers import (  # noqa: E402
    answer_latency_caption as _answer_latency_caption,
    first_answer_examples as _first_answer_examples,
    infer_topic_label_from_last_answer as _infer_topic_label_from_last_answer,
    summarize_answer_for_handoff as _summarize_answer_for_handoff,
)
