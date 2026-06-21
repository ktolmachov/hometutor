"""Подключение темы: `app/ui_theme.css` лежит рядом с пакетом `app/`."""
from pathlib import Path

import streamlit as st


def inject_styles() -> None:
    app_dir = Path(__file__).resolve().parent.parent
    css_path = app_dir / "ui_theme.css"
    css = css_path.read_text(encoding="utf-8")
    st.markdown(f"<style>\n{css}\n</style>", unsafe_allow_html=True)
