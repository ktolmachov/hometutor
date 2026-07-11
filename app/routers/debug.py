"""Debug-only API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import session_tape
from app.config import get_settings
from app.session_replay import iter_events

router = APIRouter()


@router.get("/debug/session-tape/{session_id}")
def get_session_tape_debug_replay(session_id: str) -> dict:
    """Return replayable session tape events when explicitly enabled."""
    if not get_settings().session_tape_debug_replay_enabled:
        raise HTTPException(status_code=404, detail="Not found")

    return {
        "session_id": session_id,
        "events": list(iter_events(session_id, sessions_dir=session_tape.SESSIONS_DIR)),
    }
