"""SQLite persistence for reading progress, bookmarks, and notes (local UX layer)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from app.auth_context import get_current_user_id
from app.config import get_settings

logger = logging.getLogger(__name__)

# Serialize Python-side write transactions across threads. Reads are not gated:
# WAL mode lets concurrent readers proceed without blocking, and serializing
# writes here avoids `database is locked` races when multiple threads issue
# write transactions through short-lived connections.
_DB_WRITE_LOCK = threading.Lock()
# Track which DB paths already had connection-time PRAGMAs applied so we only
# pay the cost (and avoid log noise) once per process per file.
_DB_PRAGMA_LOCK = threading.Lock()
_DB_PRAGMA_APPLIED: set[str] = set()
# Track which DB paths already had the full schema applied. Keyed by DB path so
# that test fixtures using tmp DBs still get their schema on first access.
_DB_SCHEMA_LOCK = threading.Lock()
_DB_SCHEMA_APPLIED: set[str] = set()


def reset_schema_cache_for_tests() -> None:
    """Clear schema-applied cache. Call in test fixtures that create fresh DBs."""
    with _DB_SCHEMA_LOCK:
        _DB_SCHEMA_APPLIED.clear()


# Snapshot of Streamlit learning workspace (research session)
RESEARCH_PAYLOAD_VERSION = 1
MAX_HISTORY_IN_SNAPSHOT = 20

T = TypeVar("T")

_SYNC_TABLE_COLUMNS: dict[str, frozenset[str]] = {
    "reading_status": frozenset(
        {
            "id",
            "resource_type",
            "resource_id",
            "step_index",
            "step_label",
            "progress",
            "display_title",
            "index_version",
            "updated_at",
        }
    ),
    "annotations": frozenset(
        {"id", "resource_type", "resource_id", "kind", "body", "created_at"}
    ),
    "research_sessions": frozenset(
        {"id", "name", "payload_json", "index_version", "created_at", "updated_at"}
    ),
    "quiz_results": frozenset(
        {
            "id",
            "concept",
            "level",
            "score",
            "timestamp",
            "attempt_number",
            "generation_id",
            "index_version",
        }
    ),
    "spaced_repetition": frozenset(
        {
            "concept",
            "easiness",
            "interval_days",
            "repetitions",
            "next_review",
            "last_review",
            "generation_id",
            "index_version",
        }
    ),
    "spaced_repetition_archive": frozenset(
        {
            "id",
            "concept",
            "easiness",
            "interval_days",
            "repetitions",
            "next_review",
            "last_review",
            "source_generation_id",
            "source_index_version",
            "target_generation_id",
            "target_index_version",
            "archived_at",
            "archived_reason",
        }
    ),
    "quiz_mastery": frozenset(
        {
            "concept",
            "current_level",
            "success_streak",
            "last_updated",
            "generation_id",
            "index_version",
        }
    ),
    "quiz_mastery_archive": frozenset(
        {
            "id",
            "concept",
            "current_level",
            "success_streak",
            "last_updated",
            "source_generation_id",
            "source_index_version",
            "target_generation_id",
            "target_index_version",
            "archived_at",
            "archived_reason",
        }
    ),
    "learner_profile_migration_log": frozenset(
        {
            "id",
            "event_type",
            "source_generation_id",
            "source_index_version",
            "target_generation_id",
            "target_index_version",
            "migrated_at",
            "archived_counts_json",
            "stamped_counts_json",
            "live_counts_json",
            "diagnostics_json",
        }
    ),
    "micro_quiz_events": frozenset(
        {"id", "topic", "feedback_json", "next_step_json", "created_at"}
    ),
    "tutor_learning_resume": frozenset(
        {
            "id",
            "session_id",
            "topic",
            "mastery_level",
            "last_action_kind",
            "last_action_label",
            "quiz_feedback_json",
            "recommended_next_json",
            "due_reviews_count",
            "updated_at",
            "index_version",
        }
    ),
    "learner_goal_snapshot": frozenset(
        {
            "id",
            "schema_version",
            "topic",
            "subtopic",
            "target_level",
            "desired_outcome",
            "time_budget_min",
            "preferred_style",
            "learning_goal",
            "updated_at",
        }
    ),
    "flashcard_review_log": frozenset(
        {
            "id",
            "card_id",
            "deck_id",
            "quality",
            "easiness_before",
            "easiness_after",
            "interval_before",
            "interval_after",
            "repetitions",
            "reviewed_at",
        }
    ),
    "app_kv": frozenset({"key", "value", "updated_at"}),
}
_SYNC_TABLES_ORDER: tuple[str, ...] = tuple(_SYNC_TABLE_COLUMNS)
_ALLOWED_SYNC_TABLES = frozenset(_SYNC_TABLES_ORDER)
_ALLOWED_SCHEMA_TABLES = _ALLOWED_SYNC_TABLES | frozenset(
    {"flashcard_decks", "flashcards", "ssr_recommendation_feedback", "ssr_route_impressions"}
)
_ALLOWED_SCHEMA_COLUMN_DEFS = frozenset(
    {
        "generation_id TEXT",
        "index_version INTEGER",
    }
)

_ARCHIVE_STATE_TABLES = ("spaced_repetition", "quiz_mastery")
_ALLOWED_ARCHIVE_STATE_TABLES = frozenset(_ARCHIVE_STATE_TABLES)


def _normalize_archive_state_table(state_table: str | None) -> str | None:
    raw = str(state_table or "").strip().lower()
    if not raw:
        return None
    if raw not in _ARCHIVE_STATE_TABLES:
        raise ValueError(f"unsupported state_table: {state_table!r}")
    return raw


def _quote_allowed_identifier(value: str, allowed: frozenset[str], *, kind: str) -> str:
    name = str(value or "").strip()
    if name not in allowed:
        raise ValueError(f"unsupported {kind}: {value!r}")
    return f'"{name}"'


def _quote_sync_table(table: str) -> str:
    return _quote_allowed_identifier(table, _ALLOWED_SYNC_TABLES, kind="sync table")


def _quote_schema_table(table: str) -> str:
    return _quote_allowed_identifier(table, _ALLOWED_SCHEMA_TABLES, kind="schema table")


def _ensure_allowed_column_def(column_def: str) -> str:
    value = str(column_def or "").strip()
    if value not in _ALLOWED_SCHEMA_COLUMN_DEFS:
        raise ValueError(f"unsupported schema column definition: {column_def!r}")
    return value


def _quote_archive_table(state_table: str) -> str:
    archive_table = f"{_normalize_archive_state_table(state_table)}_archive"
    return _quote_sync_table(archive_table)


def _quote_sync_columns(table: str, columns: list[str]) -> list[str]:
    allowed = _SYNC_TABLE_COLUMNS.get(table)
    if allowed is None:
        raise ValueError(f"unsupported sync table: {table!r}")
    return [
        _quote_allowed_identifier(column, allowed, kind=f"{table} column")
        for column in columns
    ]


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()




def _apply_connection_pragmas(conn: sqlite3.Connection, db_path: str) -> None:
    """Enable WAL once per DB path and relaxed sync on every connection.

    `journal_mode=WAL` is persisted in the DB file, so we only execute it the
    first time we touch a given path in this process. `synchronous` is a
    per-connection PRAGMA, so it must be applied on every fresh connection.
    """
    try:
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError as exc:  # pragma: no cover - extremely rare
        logger.warning("user_state synchronous pragma failed: %s", exc)
    with _DB_PRAGMA_LOCK:
        if db_path in _DB_PRAGMA_APPLIED:
            return
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as exc:
            logger.warning("user_state journal_mode pragma failed: %s", exc)
        _DB_PRAGMA_APPLIED.add(db_path)


def _resolve_state_db_path() -> str:
    """Путь к state-БД: базовый файл, либо per-user поддиректория при активном auth-контексте.

    uid=None (auth выключен / фоновые задачи / тесты без логина) → старый путь, без изменений
    поведения. uid задан → `<base_dir>/users/<uid>/<base_name>`, физическая изоляция прогресса
    между пользователями без переписывания схемы таблиц (см. docs/compliance_upgrade_plan.md §A3).
    """
    raw = (get_settings().user_state_db or "").strip() or str(
        Path(__file__).resolve().parent.parent / "data" / "user_state.db"
    )
    base = Path(raw)
    uid = (get_current_user_id() or "").strip()
    if uid and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", uid):
        return str(base.parent / "users" / uid / base.name)
    return str(base)


def _connect() -> sqlite3.Connection:
    db_path = _resolve_state_db_path()
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _apply_connection_pragmas(conn, db_path)
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column_def: str) -> None:
    table_sql = _quote_schema_table(table)
    column_sql = _ensure_allowed_column_def(column_def)
    try:
        conn.execute(f"ALTER TABLE {table_sql} ADD COLUMN {column_sql}")
    except sqlite3.OperationalError:
        pass


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create missing tables. Schema is applied once per DB path per process."""
    db_path = str(conn.execute("PRAGMA database_list").fetchone()[2])
    with _DB_SCHEMA_LOCK:
        if db_path in _DB_SCHEMA_APPLIED:
            return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS reading_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            step_index INTEGER,
            step_label TEXT,
            progress REAL,
            display_title TEXT,
            index_version TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(resource_type, resource_id)
        );

        CREATE TABLE IF NOT EXISTS annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            body TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_reading_updated ON reading_status(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_annotations_created ON annotations(created_at DESC);

        CREATE TABLE IF NOT EXISTS research_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            index_version TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_research_updated ON research_sessions(updated_at DESC);

        CREATE TABLE IF NOT EXISTS quiz_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept TEXT,
            level TEXT,
            score REAL NOT NULL,
            timestamp TEXT NOT NULL,
            attempt_number INTEGER DEFAULT 1,
            generation_id TEXT,
            index_version INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_quiz_results_ts ON quiz_results(timestamp DESC);

        CREATE TABLE IF NOT EXISTS spaced_repetition (
            concept TEXT PRIMARY KEY,
            easiness REAL NOT NULL DEFAULT 2.5,
            interval_days INTEGER NOT NULL DEFAULT 1,
            repetitions INTEGER NOT NULL DEFAULT 0,
            next_review TEXT,
            last_review TEXT,
            generation_id TEXT,
            index_version INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_spaced_next ON spaced_repetition(next_review);

        CREATE TABLE IF NOT EXISTS quiz_mastery (
            concept TEXT PRIMARY KEY,
            current_level TEXT NOT NULL DEFAULT 'recognition',
            success_streak INTEGER NOT NULL DEFAULT 0,
            last_updated TEXT NOT NULL,
            generation_id TEXT,
            index_version INTEGER
        );

        CREATE TABLE IF NOT EXISTS spaced_repetition_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept TEXT NOT NULL,
            easiness REAL NOT NULL,
            interval_days INTEGER NOT NULL,
            repetitions INTEGER NOT NULL,
            next_review TEXT,
            last_review TEXT,
            source_generation_id TEXT,
            source_index_version INTEGER,
            target_generation_id TEXT,
            target_index_version INTEGER,
            archived_at TEXT NOT NULL,
            archived_reason TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_spaced_archive_concept
        ON spaced_repetition_archive(concept, archived_at DESC);

        CREATE TABLE IF NOT EXISTS quiz_mastery_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concept TEXT NOT NULL,
            current_level TEXT NOT NULL,
            success_streak INTEGER NOT NULL,
            last_updated TEXT NOT NULL,
            source_generation_id TEXT,
            source_index_version INTEGER,
            target_generation_id TEXT,
            target_index_version INTEGER,
            archived_at TEXT NOT NULL,
            archived_reason TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_quiz_mastery_archive_concept
        ON quiz_mastery_archive(concept, archived_at DESC);

        CREATE TABLE IF NOT EXISTS learner_profile_migration_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            source_generation_id TEXT,
            source_index_version INTEGER,
            target_generation_id TEXT,
            target_index_version INTEGER,
            migrated_at TEXT NOT NULL,
            archived_counts_json TEXT NOT NULL,
            stamped_counts_json TEXT NOT NULL,
            live_counts_json TEXT NOT NULL,
            diagnostics_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_learner_profile_migration_log_at
        ON learner_profile_migration_log(migrated_at DESC);
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ann_one_bookmark
        ON annotations(resource_type, resource_id) WHERE kind = 'bookmark'
        """
    )
    conn.commit()
    _ensure_column(conn, "quiz_results", "generation_id TEXT")
    _ensure_column(conn, "quiz_results", "index_version INTEGER")
    _ensure_column(conn, "spaced_repetition", "generation_id TEXT")
    _ensure_column(conn, "spaced_repetition", "index_version INTEGER")
    _ensure_column(conn, "quiz_mastery", "generation_id TEXT")
    _ensure_column(conn, "quiz_mastery", "index_version INTEGER")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS micro_quiz_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            feedback_json TEXT NOT NULL,
            next_step_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tutor_learning_resume (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            session_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            mastery_level TEXT NOT NULL DEFAULT 'intermediate',
            last_action_kind TEXT NOT NULL,
            last_action_label TEXT,
            quiz_feedback_json TEXT,
            recommended_next_json TEXT,
            due_reviews_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            index_version TEXT
        )
        """
    )
    try:
        conn.execute("ALTER TABLE tutor_learning_resume ADD COLUMN index_version TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS learner_goal_snapshot (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            schema_version INTEGER NOT NULL DEFAULT 1,
            topic TEXT NOT NULL DEFAULT 'general',
            subtopic TEXT,
            target_level TEXT,
            desired_outcome TEXT,
            time_budget_min INTEGER,
            preferred_style TEXT NOT NULL DEFAULT 'balanced',
            learning_goal TEXT NOT NULL DEFAULT 'understand_topic',
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS flashcard_decks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            source_type TEXT    NOT NULL DEFAULT 'document',
            source_id   TEXT,
            card_count  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_fc_decks_updated ON flashcard_decks(updated_at DESC)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS flashcards (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_id       INTEGER NOT NULL REFERENCES flashcard_decks(id) ON DELETE CASCADE,
            front         TEXT    NOT NULL,
            back          TEXT    NOT NULL,
            tags          TEXT,
            easiness      REAL    NOT NULL DEFAULT 2.5,
            interval_days INTEGER NOT NULL DEFAULT 0,
            repetitions   INTEGER NOT NULL DEFAULT 0,
            next_review   TEXT,
            last_review   TEXT,
            created_at    TEXT    NOT NULL,
            updated_at    TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fc_deck    ON flashcards(deck_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fc_review  ON flashcards(next_review)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fc_deck_review ON flashcards(deck_id, next_review)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS flashcard_review_log (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id          INTEGER NOT NULL,
            deck_id          INTEGER NOT NULL,
            quality          INTEGER NOT NULL,
            easiness_before  REAL    NOT NULL,
            easiness_after   REAL    NOT NULL,
            interval_before  INTEGER NOT NULL,
            interval_after   INTEGER NOT NULL,
            repetitions      INTEGER NOT NULL,
            reviewed_at      TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fcrl_card ON flashcard_review_log(card_id, reviewed_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fcrl_ts   ON flashcard_review_log(reviewed_at DESC)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_kv (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ssr_recommendation_feedback (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            action                 TEXT    NOT NULL,
            hint_kind              TEXT    NOT NULL,
            primary_nav            TEXT    NOT NULL,
            weak_concept_sha256    TEXT,
            why_now_len            INTEGER NOT NULL DEFAULT 0,
            explanation_outcome    TEXT,
            latency_ms             REAL,
            session_key_prefix     TEXT,
            created_at             TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ssr_rec_fb_created
        ON ssr_recommendation_feedback(created_at DESC)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ssr_route_impressions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            hint_kind           TEXT    NOT NULL,
            primary_nav         TEXT    NOT NULL,
            session_key_prefix  TEXT,
            created_at          TEXT    NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ssr_route_impr_created
        ON ssr_route_impressions(created_at DESC)
        """
    )
    conn.commit()
    with _DB_SCHEMA_LOCK:
        _DB_SCHEMA_APPLIED.add(db_path)
