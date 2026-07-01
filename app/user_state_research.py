from __future__ import annotations
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Any
import re
import hashlib

from app.user_state_core import *

def normalize_research_payload(
    *,
    current_view: str,
    active_topic_id: str | None,
    last_studied_document: str | None,
    last_answer: Any,
    last_synthesis: Any,
    last_learning_plan: Any,
    history: list[Any],
    question_draft: str,
    topic_document_selections: dict[str, list[str]],
    workbench_sections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a JSON-serializable snapshot for `research_sessions` (Streamlit UI state).

    ``workbench_sections`` — «Живой конспект» корзина (rows из ``app.section_index.section_to_row``,
    все пути уже строки — JSON-safe как есть).
    """
    return {
        "version": RESEARCH_PAYLOAD_VERSION,
        "current_view": current_view,
        "active_topic_id": active_topic_id,
        "last_studied_document": (last_studied_document or "").strip() or None,
        "last_answer": last_answer,
        "last_synthesis": last_synthesis,
        "last_learning_plan": last_learning_plan,
        "history": history[:MAX_HISTORY_IN_SNAPSHOT] if history else [],
        "question_draft": (question_draft or "")[:5000],
        "topic_document_selections": topic_document_selections,
        "workbench_sections": workbench_sections or [],
    }


def save_research_session(
    name: str,
    payload: dict[str, Any],
    *,
    index_version: str | None = None,
) -> int:
    """Insert a new research session; returns row id."""

    def _work(conn: sqlite3.Connection) -> int:
        ts = _utc_now_iso()
        raw = json.dumps(payload, ensure_ascii=False)
        cur = conn.execute(
            """
            INSERT INTO research_sessions(name, payload_json, index_version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ((name or "").strip() or "Исследование", raw, index_version, ts, ts),
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    return _with_db(_work, write=True)


def list_research_sessions(
    *,
    limit: int = 30,
    current_index_version: str | None = None,
) -> list[dict[str, Any]]:
    """List sessions (metadata + is_stale). Payload not included."""

    def _work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT id, name, index_version, created_at, updated_at
            FROM research_sessions
            ORDER BY datetime(updated_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            iv = d.get("index_version")
            stale = bool(current_index_version) and bool(iv) and iv != current_index_version
            d["is_stale"] = stale
            out.append(d)
        return out

    return _with_db(_work)


def get_research_session(session_id: int) -> dict[str, Any] | None:
    """Return session row with parsed `payload` dict."""

    def _work(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT id, name, payload_json, index_version, created_at, updated_at
            FROM research_sessions WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["payload"] = json.loads(d["payload_json"])
        except (json.JSONDecodeError, TypeError):
            d["payload"] = {}
        del d["payload_json"]
        return d

    return _with_db(_work)


def delete_research_session(session_id: int) -> None:
    def _work(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM research_sessions WHERE id = ?", (session_id,))
        conn.commit()

    return _with_db(_work, write=True)

