"""
Persistent session store для multi-turn: история в SQLite + in-memory LRU.

Потокобезопасность: RLock на кэш и операции записи; соединения не шарятся между потоками.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from app.config import DATA_DIR, get_settings
from app.models import Message

logger = logging.getLogger(__name__)

_SQLITE_TIMEOUT_SEC = 30.0


class SessionStore:
    """Хранение сообщений по session_id: SQLite + LRU в памяти."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        *,
        cache_maxsize: int = 50,
        retention_days: int = 30,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else DATA_DIR / "sessions.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_maxsize = max(1, cache_maxsize)
        self._retention_days = max(1, retention_days)

        self._memory_cache: OrderedDict[str, list[Message]] = OrderedDict()
        self._lock = threading.RLock()

        self._init_db()
        self._cleanup_old_sessions()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=_SQLITE_TIMEOUT_SEC,
            isolation_level=None,
        )
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    messages TEXT NOT NULL,
                    last_updated TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_session_metadata_column(conn)

    def _ensure_session_metadata_column(self, conn: sqlite3.Connection) -> None:
        cur = conn.execute("PRAGMA table_info(sessions)")
        cols = {row[1] for row in cur.fetchall()}
        if "session_metadata" not in cols:
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN session_metadata TEXT NOT NULL DEFAULT '{}'"
            )

    def _cleanup_old_sessions(self) -> None:
        cutoff = (datetime.now() - timedelta(days=self._retention_days)).isoformat()
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM sessions WHERE last_updated < ?", (cutoff,))

    def get(self, session_id: str) -> list[Message]:
        if not session_id:
            return []

        with self._lock:
            if session_id in self._memory_cache:
                self._memory_cache.move_to_end(session_id)
                return list(self._memory_cache[session_id])

            with self._connect() as conn:
                cursor = conn.execute(
                    "SELECT messages FROM sessions WHERE session_id = ?",
                    (session_id,),
                )
                row = cursor.fetchone()

            if not row:
                return []

            try:
                messages_data = json.loads(row[0])
            except json.JSONDecodeError as e:
                logger.warning(
                    "Corrupt session JSON for %s: %s", session_id, e, exc_info=False
                )
                return []

            messages = [Message(**msg) for msg in messages_data]
            self._memory_cache[session_id] = messages
            self._evict_cache_if_needed()
            return list(messages)

    def _evict_cache_if_needed(self) -> None:
        while len(self._memory_cache) > self._cache_maxsize:
            self._memory_cache.popitem(last=False)

    @staticmethod
    def _apply_session_history_cap(
        messages: list[Message], max_messages: int
    ) -> tuple[list[Message], bool]:
        if max_messages <= 0 or len(messages) <= max_messages:
            return messages, False
        return messages[-max_messages:], True

    @staticmethod
    def _last_user_preview_from_messages(messages: list[Message]) -> str:
        """Короткая строка последнего user-turn для UI списка сессий (E9.7)."""
        for m in reversed(messages or []):
            if getattr(m, "role", "") != "user":
                continue
            text = str(getattr(m, "content", "") or "").strip()
            if not text:
                continue
            line = " ".join(text.split())
            if len(line) > 160:
                line = line[:159].rstrip() + "…"
            return line
        return ""

    def save(
        self,
        session_id: str,
        messages: list[Message],
        *,
        merge_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Сохраняет историю; обрезка по ``session_history_max_messages``; merge JSON metadata."""
        if not session_id:
            return {}

        max_msg = int(get_settings().session_history_max_messages)
        trimmed, did_trim = self._apply_session_history_cap(messages, max_msg)
        payload = json.dumps([msg.__dict__ for msg in trimmed])
        now = datetime.now().isoformat()

        with self._lock:
            prev_meta: dict[str, Any] = {}
            created_for_insert = now
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT session_metadata, created_at FROM sessions WHERE session_id = ?",
                    (session_id,),
                )
                row = cur.fetchone()
                if row:
                    created_for_insert = row[1] or now
                    raw_meta = row[0]
                    if raw_meta:
                        try:
                            prev_meta = json.loads(raw_meta)
                        except json.JSONDecodeError:
                            prev_meta = {}

                merged_meta = {**prev_meta, **(merge_metadata or {})}
                merged_meta["stored_messages"] = len(trimmed)
                merged_meta["bounded_history_trimmed"] = did_trim
                merged_meta["turn_count"] = int(prev_meta.get("turn_count", 0)) + 1
                merged_meta["last_user_preview"] = self._last_user_preview_from_messages(trimmed)
                meta_json = json.dumps(merged_meta)

                conn.execute(
                    """
                    INSERT INTO sessions (session_id, messages, last_updated, created_at, session_metadata)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        messages = excluded.messages,
                        last_updated = excluded.last_updated,
                        session_metadata = excluded.session_metadata
                    """,
                    (session_id, payload, now, created_for_insert, meta_json),
                )

            self._memory_cache[session_id] = list(trimmed)
            self._memory_cache.move_to_end(session_id)
            self._evict_cache_if_needed()

        return {
            "session_history_stored": len(trimmed),
            "session_history_max": max_msg if max_msg > 0 else None,
            "session_history_trimmed": did_trim,
        }

    def get_metadata(self, session_id: str) -> dict[str, Any]:
        if not session_id:
            return {}
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT session_metadata FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cur.fetchone()
        if not row or not row[0]:
            return {}
        try:
            data = json.loads(row[0])
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def patch_metadata(self, session_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        """Частичное обновление session_metadata; сбрасывает LRU-кэш сообщений для id."""
        if not session_id:
            return None
        now = datetime.now().isoformat()
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT session_metadata FROM sessions WHERE session_id = ?",
                    (session_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                prev: dict[str, Any] = {}
                if row[0]:
                    try:
                        loaded = json.loads(row[0])
                        if isinstance(loaded, dict):
                            prev = loaded
                    except json.JSONDecodeError:
                        prev = {}
                if patch:
                    prev.update(patch)
                    conn.execute(
                        """
                        UPDATE sessions SET session_metadata = ?, last_updated = ?
                        WHERE session_id = ?
                        """,
                        (json.dumps(prev), now, session_id),
                    )
            self._memory_cache.pop(session_id, None)
        return prev

    def get_record(self, session_id: str) -> dict[str, Any] | None:
        """Полная запись сессии: сообщения + metadata + timestamps (для API)."""
        if not session_id:
            return None
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT messages, session_metadata, last_updated, created_at
                FROM sessions WHERE session_id = ?
                """,
                (session_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        try:
            messages_data = json.loads(row[0])
        except json.JSONDecodeError:
            logger.warning("Corrupt session JSON for %s", session_id, exc_info=False)
            return None
        messages = [Message(**msg) for msg in messages_data]
        meta: dict[str, Any] = {}
        if row[1]:
            try:
                loaded = json.loads(row[1])
                if isinstance(loaded, dict):
                    meta = loaded
            except json.JSONDecodeError:
                pass
        return {
            "session_id": session_id,
            "messages": [m.__dict__ for m in messages],
            "metadata": meta,
            "last_updated": row[2],
            "created_at": row[3],
        }

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        lim = max(1, min(limit, 500))
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT session_id, last_updated, created_at, session_metadata
                FROM sessions
                ORDER BY last_updated DESC
                LIMIT ?
                """,
                (lim,),
            )
            rows = cursor.fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            preview: str | None = None
            raw_meta = r[3] if len(r) > 3 else None
            if raw_meta:
                try:
                    loaded = json.loads(raw_meta)
                    if isinstance(loaded, dict):
                        pv = str(loaded.get("last_user_preview") or "").strip()
                        if pv:
                            preview = pv
                except json.JSONDecodeError:
                    pass
            out.append(
                {
                    "session_id": r[0],
                    "last_updated": r[1],
                    "created_at": r[2],
                    "last_user_preview": preview,
                }
            )
        return out

    def delete(self, session_id: str) -> None:
        if not session_id:
            return
        with self._lock:
            self._memory_cache.pop(session_id, None)
            with self._connect() as conn:
                conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


try:
    session_store = SessionStore()
except Exception as e:
    logger.warning("Failed to initialize SessionStore at module load time: %s", e)
    session_store = None

__all__ = ["session_store", "SessionStore"]
