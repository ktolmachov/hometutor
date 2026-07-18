"""Persistence for interactive tutorial progress."""

from __future__ import annotations

import json
from typing import Any

from app import user_state

_TUTORIAL_PROGRESS_KV_PREFIX = "tutorial_progress_v1:"
_FALLBACK_USER_ID = "local"


def _progress_key(user_id: str | None) -> str:
    uid = str(user_id or "").strip() or _FALLBACK_USER_ID
    return f"{_TUTORIAL_PROGRESS_KV_PREFIX}{uid}"


def save_tutorial_progress(
    user_id: str | None,
    chapter_id: str,
    step_index: int,
    completed_chapters: list[str],
) -> None:
    payload = {
        "chapter_id": str(chapter_id or "").strip(),
        "step_index": max(0, int(step_index or 0)),
        "completed_chapters": sorted(
            {str(ch).strip() for ch in (completed_chapters or []) if str(ch).strip()}
        ),
    }
    user_state.set_kv(_progress_key(user_id), json.dumps(payload, ensure_ascii=False))


def load_tutorial_progress(user_id: str | None) -> dict[str, Any] | None:
    raw = user_state.get_kv(_progress_key(user_id))
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    chapter_id = str(payload.get("chapter_id") or "").strip()
    try:
        step_index = max(0, int(payload.get("step_index") or 0))
    except (TypeError, ValueError):
        step_index = 0
    completed = payload.get("completed_chapters")
    if not isinstance(completed, list):
        completed = []
    completed_clean = [str(ch).strip() for ch in completed if str(ch).strip()]
    return {
        "chapter_id": chapter_id,
        "step_index": step_index,
        "completed_chapters": completed_clean,
    }


_ACTIVATION_PROGRESS_KV_PREFIX = "activation_progress_v1:"


def _activation_key(user_id: str | None) -> str:
    uid = str(user_id or "").strip() or _FALLBACK_USER_ID
    return f"{_ACTIVATION_PROGRESS_KV_PREFIX}{uid}"


def save_activation_progress(
    user_id: str | None,
    *,
    step_index: int,
    completed_ids: list[str],
    active: bool,
    skipped: bool = False,
) -> None:
    payload = {
        "step_index": max(0, int(step_index or 0)),
        "completed_ids": sorted({str(x).strip() for x in (completed_ids or []) if str(x).strip()}),
        "active": bool(active),
        "skipped": bool(skipped),
    }
    user_state.set_kv(_activation_key(user_id), json.dumps(payload, ensure_ascii=False))


def load_activation_progress(user_id: str | None) -> dict[str, Any] | None:
    raw = user_state.get_kv(_activation_key(user_id))
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        step_index = max(0, int(payload.get("step_index") or 0))
    except (TypeError, ValueError):
        step_index = 0
    completed = payload.get("completed_ids")
    if not isinstance(completed, list):
        completed = []
    return {
        "step_index": step_index,
        "completed_ids": [str(x).strip() for x in completed if str(x).strip()],
        "active": bool(payload.get("active")),
        "skipped": bool(payload.get("skipped")),
    }

