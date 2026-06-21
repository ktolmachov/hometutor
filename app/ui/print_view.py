"""Режим «Чистый вид» для печати/чтения конспекта или плана."""
from __future__ import annotations

import streamlit as st

from app.ui.longform import render_longform_block
from app.ui.source_cards import render_source_cards
from app.ui.widgets import render_chip_row, render_panel_header


def open_print_view(
    *,
    title: str,
    subtitle: str,
    body_md: str,
    export_md: str,
    documents: list[str] | None = None,
    sources: list[dict] | None = None,
) -> None:
    st.session_state["print_view_payload"] = {
        "title": title,
        "subtitle": subtitle,
        "body_md": body_md,
        "export_md": export_md,
        "documents": documents or [],
        "sources": sources or [],
    }
    st.session_state["current_view"] = "Чистый вид"


def render_print_view() -> None:
    payload = st.session_state.get("print_view_payload")
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    if not payload:
        render_panel_header("Чистый вид", "Откройте конспект или план обучения и нажмите «Печать/чистый вид».")
        st.info("Здесь появится отдельный longform-материал без лишних боковых панелей.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    top_actions = st.columns([1, 1, 3], gap="small")
    with top_actions[0]:
        if st.button("Назад к темам", key="print_back_topics", width='stretch', type="secondary"):
            st.session_state["current_view"] = "Темы"
            st.rerun()
    with top_actions[1]:
        st.download_button(
            label="Скачать Markdown",
            data=payload.get("export_md", ""),
            file_name="study_material.md",
            mime="text/markdown",
            key="print_download_md",
            width='stretch',
        )

    render_panel_header(payload.get("title", "Чистый вид"), payload.get("subtitle", "Готовый longform-материал для чтения или печати."))
    if payload.get("documents"):
        st.caption("Материалы в основе этого документа")
        render_chip_row(payload.get("documents") or [])
    render_longform_block(payload.get("body_md", ""), markdown=True)
    if payload.get("sources"):
        st.markdown("---")
        st.markdown("#### Источники")
        render_source_cards(payload.get("sources") or [], prefix="print_src")
    st.markdown("</div>", unsafe_allow_html=True)
