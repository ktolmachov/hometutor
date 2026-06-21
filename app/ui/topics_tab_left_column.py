"""Левая колонка карты тем (P5c split)."""

from __future__ import annotations

import streamlit as st

from app.ui.widgets import render_chip_row


def render_topics_left_column(
    *,
    filtered_topics: list,
    selected_topic: dict,
    topic_states: dict,
) -> None:
    st.write("**Карта тем**")
    for idx, topic in enumerate(filtered_topics):
        is_active = topic["topic_id"] == st.session_state["active_topic_id"]
        tid = topic.get("topic_id")
        marked = bool(tid and topic_states.get(tid, {}).get("bookmarked"))
        mark = "🔖 " if marked else ""
        button_label = f"{mark}{'●' if is_active else '○'} {topic['topic_name']} ({topic['document_count']})"
        pick_key = f"topic_pick_{idx}_{topic.get('topic_id', 'none')}"
        if st.button(button_label, key=pick_key, width="stretch", type="secondary"):
            st.session_state["active_topic_id"] = topic["topic_id"]
            st.rerun()
    st.markdown("---")
    st.markdown(
        f"""
        <div class="topic-card">
            <div class="panel-title">{selected_topic['topic_name']}</div>
            <div class="panel-subtitle">{selected_topic['document_count']} документов в теме</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_chip_row(selected_topic.get("key_concepts") or [])
    sp = topic_states.get(selected_topic["topic_id"], {})
    prog = sp.get("progress")
    if prog is not None:
        st.progress(min(1.0, max(0.0, float(prog))))
        st.caption(f"Сохранённый прогресс: **{round(float(prog) * 100)}%**")
