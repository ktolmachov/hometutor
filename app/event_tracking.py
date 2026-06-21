"""
Backend-safe hooks for analytics-style events (micro-quiz completion, etc.).

Сервисный слой вызывает функции отсюда вместо ``app/ui_events`` — без зависимости UI-модулей.
Персистентность здесь — SQLite; Streamlit session_state-лог остаётся в UI-обёртке.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

logger = logging.getLogger(__name__)


def _db_path(data_dir: Path | None = None) -> str:
    p = (data_dir or DATA_DIR) / "ui_events.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def _connect(data_dir: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(data_dir), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ui_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name TEXT NOT NULL,
            ts TEXT NOT NULL,
            user_id TEXT NOT NULL DEFAULT 'local',
            payload_json TEXT
        )
        """
    )
    conn.commit()


def track_event(event_name: str, payload: dict[str, Any] | None = None, *, data_dir: Path | None = None) -> None:
    """Запись события в SQLite без зависимости от Streamlit/UI."""
    name = (event_name or "").strip() or "unknown"
    ts = datetime.now(timezone.utc).isoformat()
    try:
        conn = _connect(data_dir)
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO ui_events(event_name, ts, user_id, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (name, ts, "local", json.dumps(payload or {}, ensure_ascii=False)),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug("event_tracking.track_event failed: %s", e, exc_info=True)


def track_quiz_completed(result: str) -> None:
    """Зафиксировать завершение micro-quiz (тот же контракт, что ``track_micro_quiz_completed``)."""
    track_event("micro_quiz_completed", {"result": (result or "").strip()})


__all__ = ["track_event", "track_quiz_completed"]
