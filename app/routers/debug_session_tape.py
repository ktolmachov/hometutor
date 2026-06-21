from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.session_replay import iter_events

router = APIRouter(tags=["debug"])


@router.get("/debug/session-tape/{session_id}")
def debug_session_tape(session_id: str) -> dict[str, Any]:
    """Replay session tape events (dev-only; gated by settings flag)."""
    if not get_settings().session_tape_debug_replay_enabled:
        raise HTTPException(status_code=404, detail="Session tape debug replay is disabled")
    events = list(iter_events(session_id))
    return {"session_id": session_id, "events": events}
