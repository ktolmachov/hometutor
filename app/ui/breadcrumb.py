"""Small breadcrumb helpers for Mission Control navigation."""
from __future__ import annotations

import streamlit as st

from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

HOME_VIEW = "Mission Control"


def _go_home() -> None:
    st.session_state["current_view"] = HOME_VIEW
    st.session_state.pop("home_breadcrumb_origin", None)


def render_back_to_home() -> None:
    """Render a compact back link when a view was opened from Mission Control."""
    if st.session_state.get("home_breadcrumb_origin") != HOME_VIEW:
        return
    st.markdown('<div class="breadcrumb-back">', unsafe_allow_html=True)
    st.button(
        "← Mission Control",
        key="breadcrumb_back_to_mission_control",
        on_click=_go_home,
    )
    st.markdown("</div>", unsafe_allow_html=True)
