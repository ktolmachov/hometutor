"""Append-only session tape writer (JSONL under DATA_DIR/sessions/)."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import DATA_DIR, get_settings

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SESSIONS_DIR = DATA_DIR / "sessions"

FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "answer",
        "answer_text",
        "api_key",
        "back",
        "body",
        "chunk",
        "front",
        "question",
        "question_text",
        "raw_text",
        "text",
    }
)

EVENT_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "session_started": ("entry_surface",),
    "session_ended": ("reason",),
    "mission_loaded": ("status", "variant"),
    "question_asked": ("question_hash", "char_length", "surface"),
    "retrieval_completed": ("source_count", "retrieval_mode", "latency_ms"),
    "answer_surfaced": ("confidence", "source_count", "total_answer_ms"),
    "quiz_attempt": ("quiz_kind", "topic", "correct", "difficulty_band"),
    "route_offered": ("surface", "primary_nav", "hint_kind"),
    "route_selected": ("surface", "primary_nav", "hint_kind", "accepted"),
    "learning_action_started": ("surface", "primary_nav", "topic_hint"),
    "surface_breached_soft": (
        "surface",
        "variant",
        "target_ms",
        "soft_ms",
        "hard_ms",
        "actual_ms",
        "degraded",
        "degrade_reason",
        "ladder_step",
    ),
    "surface_breached_hard": (
        "surface",
        "variant",
        "target_ms",
        "soft_ms",
        "hard_ms",
        "actual_ms",
        "degraded",
        "degrade_reason",
        "ladder_step",
    ),
    "budget_completed": (
        "surface",
        "variant",
        "target_ms",
        "soft_ms",
        "hard_ms",
        "actual_ms",
        "degraded",
        "degrade_reason",
        "ladder_step",
    ),
    "e2e_graduation": (
        "llm_model",
        "llm_source",
        "fallback_used",
    ),
}

RESERVED_NOT_EMITTED = frozenset({"card_created", "dwell_ms"})

_started_sessions: set[str] = set()
_last_started_session_id: str | None = None


def reset_session_started_cache_for_tests() -> None:
    """Clear in-process session_started dedup (tests only)."""
    global _last_started_session_id
    _started_sessions.clear()
    _last_started_session_id = None


def sanitize_session_id(session_id: str) -> str:
    """Return safe filename token; hash when path separators or traversal detected."""
    raw = (session_id or "").strip()
    if not raw:
        raise ValueError("session_id must be non-empty")
    if any(token in raw for token in ("/", "\\", "..")):
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw


def offline_payload_tag() -> dict[str, bool]:
    """Tag payload when offline/E2E modes are active (Architect resolution #7)."""
    settings = get_settings()
    if settings.home_rag_e2e_offline or settings.home_rag_micro_quiz_offline:
        return {"offline": True}
    return {}


def _strip_forbidden_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_forbidden_keys(item)
            for key, item in value.items()
            if key not in FORBIDDEN_PAYLOAD_KEYS
        }
    if isinstance(value, list):
        return [_strip_forbidden_keys(item) for item in value]
    return value


def _validate_payload(event_type: str, payload: dict[str, Any]) -> None:
    if event_type in RESERVED_NOT_EMITTED:
        raise ValueError(f"event type {event_type!r} is reserved and must not be emitted in MVP")
    required = EVENT_REQUIRED_FIELDS.get(event_type)
    if required is None:
        raise ValueError(f"unknown event type: {event_type!r}")
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError(f"event {event_type!r} missing required payload fields: {missing}")


def _tape_path(session_id: str) -> Path:
    safe_id = sanitize_session_id(session_id)
    return SESSIONS_DIR / f"{safe_id}.jsonl"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_event(
    session_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    course_id: str | None = None,
    surface: str | None = None,
    sessions_dir: Path | None = None,
) -> None:
    """Append one tape event; non-blocking on I/O failure."""
    clean_payload = _strip_forbidden_keys(dict(payload))
    clean_payload.update(offline_payload_tag())
    _validate_payload(event_type, clean_payload)

    row: dict[str, Any] = {
        "ts": _utc_now_iso(),
        "event": event_type,
        "session_id": session_id,
        "schema_version": SCHEMA_VERSION,
        "payload": clean_payload,
    }
    if course_id is not None:
        row["course_id"] = course_id
    if surface is not None:
        row["surface"] = surface

    path = (sessions_dir or SESSIONS_DIR) / f"{sanitize_session_id(session_id)}.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            handle.flush()
    except OSError as exc:  # noqa: BLE001 - tape must never block caller on disk failure
        logger.warning("session_tape_append_failed session_id=%s event=%s: %s", session_id, event_type, exc)


def ensure_session_started(
    session_id: str,
    *,
    entry_surface: str,
    course_id: str | None = None,
    surface: str | None = None,
    sessions_dir: Path | None = None,
) -> None:
    """Emit session_started once per session_id per process."""
    global _last_started_session_id
    if session_id in _started_sessions:
        return
    if _last_started_session_id and _last_started_session_id != session_id:
        end_session(
            _last_started_session_id,
            reason="superseded_by_new_session",
            course_id=course_id,
            sessions_dir=sessions_dir,
        )
    _started_sessions.add(session_id)
    _last_started_session_id = session_id
    append_event(
        session_id,
        "session_started",
        {"entry_surface": entry_surface},
        course_id=course_id,
        surface=surface,
        sessions_dir=sessions_dir,
    )


def end_session(
    session_id: str,
    *,
    reason: str,
    course_id: str | None = None,
    sessions_dir: Path | None = None,
) -> None:
    """Append session_ended and drop process dedup entry."""
    append_event(
        session_id,
        "session_ended",
        {"reason": reason},
        course_id=course_id,
        sessions_dir=sessions_dir,
    )
    _started_sessions.discard(session_id)
