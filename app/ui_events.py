"""
События UI (онбординг, CTA, micro-quiz): backend SQLite + короткий лог в session_state для сайдбара.

Отдельно от ``app/metrics`` (pipeline / JSONL / dashboard DB), чтобы не смешивать схемы.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config import DATA_DIR
from app.event_tracking import track_event as _track_backend_event

logger = logging.getLogger(__name__)


def track_event(event_name: str, payload: dict[str, Any] | None = None) -> None:
    """Запись события в backend-хранилище и (если есть Streamlit) в session_state."""
    name = (event_name or "").strip() or "unknown"
    _track_backend_event(name, payload, data_dir=DATA_DIR)
    _append_streamlit_log(name)


def _append_streamlit_log(event_name: str) -> None:
    try:
        import streamlit as st

        if "ui_event_log" not in st.session_state:
            st.session_state["ui_event_log"] = []
        st.session_state["ui_event_log"].append(
            {
                "event": event_name,
                "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            }
        )
        st.session_state["ui_event_log"] = st.session_state["ui_event_log"][-50:]
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        pass


def track_cta_click(cta: str) -> None:
    track_event("cta_click", {"cta": cta})


def track_micro_quiz_started() -> None:
    track_event("micro_quiz_started", {})


def track_micro_quiz_completed(result: str) -> None:
    track_event("micro_quiz_completed", {"result": (result or "").strip()})


def track_resume_clicked() -> None:
    track_event("resume_clicked", {})


def track_due_review_started(topic: str) -> None:
    track_event("due_review_started", {"topic": topic})


def track_trust_panel_opened() -> None:
    track_event("trust_panel_opened", {})


__all__ = [
    "track_cta_click",
    "track_due_review_started",
    "track_event",
    "track_micro_quiz_completed",
    "track_micro_quiz_started",
    "track_resume_clicked",
    "track_trust_panel_opened",
]
