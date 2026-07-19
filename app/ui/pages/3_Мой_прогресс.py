"""Redirect: «Мой прогресс» → routed view «Прогресс обучения» (wave-progress-home P0-1)."""

import streamlit as st

from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

st.session_state[PENDING_CURRENT_VIEW_KEY] = "Прогресс обучения"
st.session_state["home_breadcrumb_origin"] = "Mission Control"
st.switch_page("main.py")
