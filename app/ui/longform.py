"""Longform-блок ответа с учётом reading_mode (оболочка HTML)."""
from __future__ import annotations

import streamlit as st


def reading_shell_start() -> str:
    return '<div class="reading-shell">' if st.session_state.get("reading_mode") else '<div class="answer-shell">'


def render_longform_block(text: str, *, markdown: bool = False) -> None:
    st.markdown(reading_shell_start(), unsafe_allow_html=True)
    if markdown:
        st.markdown(text)
    else:
        st.write(text)
    st.markdown("</div>", unsafe_allow_html=True)
