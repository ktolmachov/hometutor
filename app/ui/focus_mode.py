"""Focus mode (Pomodoro + distraction lock) helpers for Course Cockpit."""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.course_metrics import record_course_workflow_event

POMODORO_FOCUS_MIN = 25
POMODORO_BREAK_MIN = 5
DEEP_WORK_CYCLES = 4


def deep_work_badge(cycles_completed: int) -> str:
    """Human-friendly deep-work status text."""
    cycles = max(0, int(cycles_completed))
    if cycles >= DEEP_WORK_CYCLES:
        return "Deep work session - 100 min"
    return f"Pomodoro cycle {cycles}/{DEEP_WORK_CYCLES}"


def build_focus_session_payload(
    *,
    cycles_completed: int,
    interrupted: bool,
    break_started: bool = False,
) -> dict[str, Any]:
    """Payload for `pomodoro_session` metric event."""
    cycles = max(0, int(cycles_completed))
    return {
        "focus_minutes": POMODORO_FOCUS_MIN,
        "break_minutes": POMODORO_BREAK_MIN,
        "cycles_completed": cycles,
        "deep_work_achieved": cycles >= DEEP_WORK_CYCLES and not bool(interrupted),
        "streak_shield": cycles >= DEEP_WORK_CYCLES and not bool(interrupted),
        "interrupted": bool(interrupted),
        "break_started": bool(break_started),
    }


def log_pomodoro_session(
    scope: dict[str, Any] | None,
    *,
    cycles_completed: int,
    interrupted: bool,
    break_started: bool = False,
) -> None:
    """Emit `pomodoro_session` event in course workflow metrics."""
    record_course_workflow_event(
        "pomodoro_session",
        scope,
        payload=build_focus_session_payload(
            cycles_completed=cycles_completed,
            interrupted=interrupted,
            break_started=break_started,
        ),
    )


def render_focus_mode_stub(*, cycles_completed: int = 0) -> None:
    """Minimal Focus mode UI slice for E30 D2."""
    st.info("Focus 25 активирован: distraction-lock режим (stub).")
    st.caption("E30 D2: позже — полноэкранный cockpit lock + таймер 25/5.")
    st.caption(deep_work_badge(cycles_completed))
    if st.button("Выход из Focus", key="focus_mode_exit_stub"):
        st.session_state.pop("course_focus_mode", None)
        st.rerun()


__all__ = [
    "POMODORO_FOCUS_MIN",
    "POMODORO_BREAK_MIN",
    "DEEP_WORK_CYCLES",
    "deep_work_badge",
    "build_focus_session_payload",
    "log_pomodoro_session",
    "render_focus_mode_stub",
]
