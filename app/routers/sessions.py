"""HTTP API для persistent chat-сессий (SQLite session store v2)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from app.session_store import session_store

router = APIRouter(tags=["sessions"])


@router.get("/sessions")
def list_sessions(limit: int = Query(20, ge=1, le=500)):
    return session_store.list_sessions(limit=limit)


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    rec = session_store.get_record(session_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="session not found")
    return rec


@router.patch("/sessions/{session_id}/metadata")
def patch_session_metadata(session_id: str, body: dict[str, Any] = Body(default_factory=dict)):
    merged = session_store.patch_metadata(session_id, body)
    if merged is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "metadata": merged}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    session_store.delete(session_id)
    return {"status": "deleted", "session_id": session_id}
