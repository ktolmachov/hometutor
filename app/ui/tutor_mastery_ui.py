"""Визуализация mastery в чате тьютора; панель прогноза — ``tutor_mastery_forecast_panel``."""
from __future__ import annotations

import streamlit as st

from app.ui.tutor_mastery_forecast_panel import render_tutor_mastery_forecast_panel


def _tutor_mastery_visual(level: str) -> tuple[int, str, str]:
    lv = (level or "intermediate").strip().lower()
    mapping = {
        "beginner": (34, "#b7791f", "Recognition"),
        "intermediate": (67, "#2b6cb0", "Recall"),
        "advanced": (100, "#2f855a", "Transfer"),
    }
    return mapping.get(lv, mapping["intermediate"])


def render_tutor_mastery_microbar(current_level: str, next_level: str | None = None) -> None:
    cur_pct, cur_color, cur_label = _tutor_mastery_visual(current_level)
    nxt = (next_level or "").strip().lower()
    next_pct = cur_pct
    if nxt in ("beginner", "intermediate", "advanced"):
        next_pct, _, _ = _tutor_mastery_visual(nxt)
    progress_pct = max(cur_pct, next_pct)
    progress_ratio = max(0.0, min(1.0, progress_pct / 100.0))
    delta = next_pct - cur_pct
    delta_label = ""
    if delta > 0:
        delta_label = f" · рост до {next_pct}%"
    elif delta < 0:
        delta_label = f" · откат до {next_pct}%"

    st.markdown(
        f"""
        <div style="margin:0.35rem 0 0.6rem 0;">
            <div style="display:flex;justify-content:space-between;gap:0.5rem;font-size:0.84rem;">
                <span><strong>Mastery:</strong> {current_level}</span>
                <span style="color:{cur_color};font-weight:700;">{cur_label}{delta_label}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.progress(progress_ratio, text=f"Текущий прогресс понимания: {progress_pct}%")


__all__ = [
    "render_tutor_mastery_forecast_panel",
    "render_tutor_mastery_microbar",
]
