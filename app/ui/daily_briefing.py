"""Morning / evening briefing overlays — stub (E30 B2)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.course_metrics import record_course_workflow_event


def briefing_title(period: str) -> str:
    p = (period or "").strip().lower()
    if p == "evening":
        return "Вечерний debrief"
    return "Утренний briefing"


def log_briefing_stub(scope: dict[str, Any] | None, *, period: str = "morning") -> None:
    record_course_workflow_event(
        "daily_briefing_stub",
        scope,
        payload={"period": (period or "morning").strip().lower()},
    )


def render_daily_briefing_stub(*, period: str = "morning") -> None:
    st.info(briefing_title(period))
    st.caption("E30 B2: позже — morning brief / evening debrief, gap-inbox.")
    if st.button("Закрыть", key=f"daily_briefing_close_{period}"):
        st.session_state.pop("daily_briefing_open", None)
        st.rerun()


__all__ = [
    "briefing_title",
    "log_briefing_stub",
    "render_daily_briefing_stub",
]
