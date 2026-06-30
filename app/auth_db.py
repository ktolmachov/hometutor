"""SQLite-хранилище аутентификации: пользователи, сессии (выданные токены), аудит-лог.

Отдельная ГЛОБАЛЬНАЯ база (`Settings.auth_db`), не путать с per-user `user_state.db`
(app/user_state_db.py). Контекст текущего пользователя (app/auth_context.py) на эту БД
не влияет — здесь хранится сам реестр пользователей.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar

from app.config import get_settings

T = TypeVar("T")

logger = logging.getLogger(__name__)

_WRITE_LOCK = threading.Lock()
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_APPLIED: set[str] = set()


def reset_schema_cache_for_tests() -> None:
    """Сбросить кэш применённой схемы (для тестов с tmp_path БД)."""
    with _SCHEMA_LOCK:
        _SCHEMA_APPLIED.clear()


def _resolve_db_path() -> str:
    raw = (get_settings().auth_db or "").strip()
    if not raw:
        raw = str(Path(__file__).resolve().parent.parent / "data" / "auth.db")
    return raw


def _connect() -> sqlite3.Connection:
    db_path = _resolve_db_path()
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.OperationalError as exc:  # pragma: no cover - extremely rare
        logger.warning("auth_db pragma failed: %s", exc)
    _ensure_schema(conn, db_path)
    return conn


def _ensure_schema(conn: sqlite3.Connection, db_path: str) -> None:
    with _SCHEMA_LOCK:
        if db_path in _SCHEMA_APPLIED:
            return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            TEXT PRIMARY KEY,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name  TEXT,
            created_at    TEXT NOT NULL,
            last_login_at TEXT
        );
        CREATE TABLE IF NOT EXISTS auth_sessions (
            id         TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            issued_at  TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            revoked    INTEGER NOT NULL DEFAULT 0,
            user_agent TEXT
        );
        CREATE TABLE IF NOT EXISTS auth_audit_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    TEXT REFERENCES users(id) ON DELETE SET NULL,
            event      TEXT NOT NULL,
            ip         TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_auth_audit_user ON auth_audit_log(user_id);
        """
    )
    conn.commit()
    with _SCHEMA_LOCK:
        _SCHEMA_APPLIED.add(db_path)


def _with_db(fn: Callable[[sqlite3.Connection], T], *, write: bool = False) -> T:
    if write:
        with _WRITE_LOCK:
            conn = _connect()
            try:
                return fn(conn)
            finally:
                conn.close()
    conn = _connect()
    try:
        return fn(conn)
    finally:
        conn.close()


def create_user(user_id: str, email: str, password_hash: str, display_name: str | None, created_at: str) -> None:
    def _do(conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, display_name, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, email.lower(), password_hash, display_name, created_at),
        )
        conn.commit()

    _with_db(_do, write=True)


def get_user_by_email(email: str) -> dict[str, Any] | None:
    def _do(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
        return dict(row) if row else None

    return _with_db(_do)


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    def _do(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    return _with_db(_do)


def touch_last_login(user_id: str, when_iso: str) -> None:
    def _do(conn: sqlite3.Connection) -> None:
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (when_iso, user_id))
        conn.commit()

    _with_db(_do, write=True)


def record_session(
    session_id: str, user_id: str, issued_at: str, expires_at: str, user_agent: str | None = None
) -> None:
    def _do(conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO auth_sessions (id, user_id, issued_at, expires_at, user_agent) VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, issued_at, expires_at, user_agent),
        )
        conn.commit()

    _with_db(_do, write=True)


def revoke_session(session_id: str) -> None:
    def _do(conn: sqlite3.Connection) -> None:
        conn.execute("UPDATE auth_sessions SET revoked = 1 WHERE id = ?", (session_id,))
        conn.commit()

    _with_db(_do, write=True)


def is_session_revoked(session_id: str) -> bool:
    """True только если сессия найдена И помечена revoked.

    Неизвестный session_id (например, БД пересоздана) трактуется как НЕ отозванный —
    подделать валидную подпись JWT без знания jwt_secret всё равно невозможно,
    так что это не открывает новую дыру, а сохраняет fail-open для устаревших токенов.
    """
    if not session_id:
        return False

    def _do(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT revoked FROM auth_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return bool(row and row["revoked"])

    return _with_db(_do)


def log_event(user_id: str | None, event: str, created_at: str, ip: str | None = None) -> None:
    def _do(conn: sqlite3.Connection) -> None:
        conn.execute(
            "INSERT INTO auth_audit_log (user_id, event, ip, created_at) VALUES (?, ?, ?, ?)",
            (user_id, event, ip, created_at),
        )
        conn.commit()

    _with_db(_do, write=True)
