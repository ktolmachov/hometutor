"""Session persistence helpers for query answers.

This module owns the small bridge between ``query_service`` answer payloads and
``SessionStore`` history records. It intentionally has no dependency on
``query_service`` so the answer orchestration can stay thin.
"""

from __future__ import annotations

import importlib
from typing import Any

from app.guardrails import redact_sensitive_text
from app.models import Message


def compact_sources_for_session(
    sources: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Compact source metadata for message storage without large chunk text."""
    if not sources:
        return []
    out: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        text = (source.get("text") or "").strip()
        out.append(
            {
                "relative_path": source.get("relative_path"),
                "file_name": source.get("file_name"),
                "page": source.get("page"),
                "score": source.get("score"),
                "text": (text[:800] + "…") if len(text) > 800 else text if text else None,
            }
        )
    return out


def persist_chat_session(
    *,
    session_id: str | None,
    user_question: str,
    assistant_answer: str,
    confidence: float,
    assistant_metadata: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Append a completed QA/tutor exchange to SQLite-backed session history."""
    if not session_id or not str(session_id).strip():
        return None

    sid = str(session_id).strip()
    session_store_module = importlib.import_module("app.session_store")
    history = list(session_store_module.session_store.get(sid))
    history.append(
        Message(role="user", content=redact_sensitive_text(str(user_question)))
    )
    meta: dict[str, Any] = {"confidence": confidence}
    if assistant_metadata:
        meta.update(assistant_metadata)
    if sources is not None:
        meta["sources"] = compact_sources_for_session(sources)
    history.append(
        Message(
            role="assistant",
            content=redact_sensitive_text(str(assistant_answer)),
            metadata=meta,
        )
    )
    return session_store_module.session_store.save(sid, history)


__all__ = ["compact_sources_for_session", "persist_chat_session"]
