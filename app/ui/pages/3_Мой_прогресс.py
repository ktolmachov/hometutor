"""Redirect: «Мой прогресс» → routed view «Прогресс обучения» (wave-progress-home P0-1)."""

import streamlit as st

st.session_state["_pending_current_view"] = "Прогресс обучения"
st.session_state["home_breadcrumb_origin"] = "Mission Control"
st.switch_page("main.py")
