"""Повторяющиеся HTML-блоки Streamlit (метрики, заголовки панелей, чипы)."""
from __future__ import annotations

import streamlit as st


def render_metric_card(label: str, value: str, subtext: str = "") -> None:
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-sub">{subtext}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_panel_header(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="panel-title">{title}</div>
        <div class="panel-subtitle">{subtitle}</div>
        """,
        unsafe_allow_html=True,
    )


def render_chip_row(items: list[str]) -> None:
    if not items:
        return
    st.markdown(
        '<div class="chip-row">' + "".join(f'<span class="chip">{item}</span>' for item in items) + "</div>",
        unsafe_allow_html=True,
    )
