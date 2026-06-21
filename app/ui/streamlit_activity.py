"""Метка активности Streamlit-сессии (KV) для US-7.2 — разрыв между визитами."""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from app.user_state import STREAMLIT_LAST_ACTIVE_ISO_KEY, get_kv, set_kv


def touch_streamlit_session() -> None:
    """Один раз за сессию браузера: записать текущее время, сохранить предыдущую метку в session_state."""
    if st.session_state.get("_streamlit_activity_once_v1"):
        return
    st.session_state["_streamlit_activity_once_v1"] = True
    prev = get_kv(STREAMLIT_LAST_ACTIVE_ISO_KEY)
    st.session_state["_streamlit_prev_active_iso_v1"] = prev
    set_kv(STREAMLIT_LAST_ACTIVE_ISO_KEY, datetime.now(timezone.utc).isoformat())


def gap_days_from_iso(prev_iso: str | None) -> float | None:
    """Сутки между сейчас и меткой ISO; None если строка пустая или не парсится."""
    if not prev_iso:
        return None
    try:
        p = datetime.fromisoformat(str(prev_iso).replace("Z", "+00:00"))
        if p.tzinfo is None:
            p = p.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0.0, (now - p).total_seconds() / 86400.0)
    except (TypeError, ValueError):
        return None


def days_since_previous_session_start() -> float | None:
    """Сутки с прошлой записи активности (до текущего захода); None если не было."""
    return gap_days_from_iso(st.session_state.get("_streamlit_prev_active_iso_v1"))
