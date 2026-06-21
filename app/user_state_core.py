
"""SQLite persistence for reading progress, bookmarks, and notes (local UX layer)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from app.user_state_db import (
    MAX_HISTORY_IN_SNAPSHOT,
    RESEARCH_PAYLOAD_VERSION,
    T,
    reset_schema_cache_for_tests,
    _ALLOWED_ARCHIVE_STATE_TABLES,
    _ALLOWED_SCHEMA_COLUMN_DEFS,
    _ALLOWED_SCHEMA_TABLES,
    _ALLOWED_SYNC_TABLES,
    _ARCHIVE_STATE_TABLES,
    _DB_PRAGMA_APPLIED,
    _DB_PRAGMA_LOCK,
    _DB_SCHEMA_APPLIED,
    _DB_SCHEMA_LOCK,
    _DB_WRITE_LOCK,
    _SYNC_TABLE_COLUMNS,
    _SYNC_TABLES_ORDER,
    _apply_connection_pragmas,
    _connect,
    _ensure_column,
    _ensure_schema,
    _ensure_allowed_column_def,
    _normalize_archive_state_table,
    _quote_allowed_identifier,
    _quote_archive_table,
    _quote_schema_table,
    _quote_sync_columns,
    _quote_sync_table,
    _utc_now_iso,
)

logger = logging.getLogger(__name__)


def _with_db(fn: Callable[[sqlite3.Connection], T], *, write: bool = False) -> T:
    if write:
        with _DB_WRITE_LOCK:
            conn = _connect()
            try:
                _ensure_schema(conn)
                return fn(conn)
            finally:
                conn.close()
    conn = _connect()
    try:
        _ensure_schema(conn)
        return fn(conn)
    finally:
        conn.close()


_LEARNER_STATE_GENERATION_KV_KEY = "learner_state_active_generation_id"
_LEARNER_STATE_INDEX_VERSION_KV_KEY = "learner_state_active_index_version"
_LEARNER_STATE_MIGRATED_AT_KV_KEY = "learner_state_lineage_migrated_at"


def _coerce_optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _read_kv_row(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_kv WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    value = row["value"]
    return str(value) if value is not None else None


def _upsert_kv_row(conn: sqlite3.Connection, key: str, value: str, updated_at: str) -> None:
    conn.execute(
        """
        INSERT INTO app_kv(key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, value, updated_at),
    )


def run_learner_state_lineage_sync() -> dict[str, Any]:
    """Синхронизировать quiz_mastery / spaced_repetition с активным generation_id из registry.

    Вызывается после активации индекса (eager path); иначе sync откладывается до следующего
    обращения к mastery / spaced repetition.
    """

    def _work(conn: sqlite3.Connection) -> dict[str, Any]:
        return sync_current_learner_state_lineage(conn)

    return _with_db(_work, write=True)


def get_learner_state_diagnostics(*, recent_limit: int = 8) -> dict[str, Any]:
    limit = max(1, min(int(recent_limit), 50))

    def _work(conn: sqlite3.Connection) -> dict[str, Any]:
        current = sync_current_learner_state_lineage(conn)
        marker_generation_id = str(_read_kv_row(conn, _LEARNER_STATE_GENERATION_KV_KEY) or "").strip() or None
        marker_index_version = _coerce_optional_int(_read_kv_row(conn, _LEARNER_STATE_INDEX_VERSION_KV_KEY))
        migrated_at = str(_read_kv_row(conn, _LEARNER_STATE_MIGRATED_AT_KV_KEY) or "").strip() or None

        live_quiz_results = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM quiz_results
            WHERE (? IS NULL OR generation_id = ?)
            """,
            (current.get("generation_id"), current.get("generation_id")),
        ).fetchone()
        live_spaced = conn.execute("SELECT COUNT(*) AS n FROM spaced_repetition").fetchone()
        live_mastery = conn.execute("SELECT COUNT(*) AS n FROM quiz_mastery").fetchone()
        archived_spaced = conn.execute(
            "SELECT COUNT(*) AS n FROM spaced_repetition_archive"
        ).fetchone()
        archived_mastery = conn.execute(
            "SELECT COUNT(*) AS n FROM quiz_mastery_archive"
        ).fetchone()

        reason_rows = conn.execute(
            """
            SELECT archived_reason, COUNT(*) AS n FROM (
                SELECT archived_reason FROM spaced_repetition_archive
                UNION ALL
                SELECT archived_reason FROM quiz_mastery_archive
            )
            GROUP BY archived_reason
            ORDER BY n DESC, archived_reason ASC
            """
        ).fetchall()
        archive_reasons = {
            str(row["archived_reason"] or "").strip(): int(row["n"] or 0)
            for row in reason_rows
            if str(row["archived_reason"] or "").strip()
        }

        recent_rows = conn.execute(
            """
            SELECT * FROM (
                SELECT
                    'spaced_repetition' AS state_table,
                    concept,
                    source_generation_id,
                    source_index_version,
                    target_generation_id,
                    target_index_version,
                    archived_at,
                    archived_reason
                FROM spaced_repetition_archive
                UNION ALL
                SELECT
                    'quiz_mastery' AS state_table,
                    concept,
                    source_generation_id,
                    source_index_version,
                    target_generation_id,
                    target_index_version,
                    archived_at,
                    archived_reason
                FROM quiz_mastery_archive
            )
            ORDER BY archived_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        recent_archive = [dict(row) for row in recent_rows]
        log_rows = conn.execute(
            """
            SELECT
                id,
                event_type,
                source_generation_id,
                source_index_version,
                target_generation_id,
                target_index_version,
                migrated_at,
                archived_counts_json,
                stamped_counts_json,
                live_counts_json,
                diagnostics_json
            FROM learner_profile_migration_log
            ORDER BY migrated_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        migration_log: list[dict[str, Any]] = []
        for row in log_rows:
            item = dict(row)
            for raw_key, parsed_key in (
                ("archived_counts_json", "archived_counts"),
                ("stamped_counts_json", "stamped_counts"),
                ("live_counts_json", "live_counts"),
                ("diagnostics_json", "diagnostics"),
            ):
                try:
                    item[parsed_key] = json.loads(str(item.pop(raw_key) or "{}"))
                except json.JSONDecodeError:
                    item[parsed_key] = {}
            migration_log.append(item)
        archive_total = int(archived_spaced["n"] or 0) + int(archived_mastery["n"] or 0)
        return {
            "current_lineage": {
                "generation_id": current.get("generation_id"),
                "index_version": _coerce_optional_int(current.get("index_version")),
            },
            "synced_lineage": {
                "generation_id": marker_generation_id,
                "index_version": marker_index_version,
                "migrated_at": migrated_at,
            },
            "live_counts": {
                "quiz_results": int(live_quiz_results["n"] or 0),
                "spaced_repetition": int(live_spaced["n"] or 0),
                "quiz_mastery": int(live_mastery["n"] or 0),
            },
            "archive_counts": {
                "spaced_repetition": int(archived_spaced["n"] or 0),
                "quiz_mastery": int(archived_mastery["n"] or 0),
                "total": archive_total,
            },
            "archive_reasons": archive_reasons,
            "recent_archive": recent_archive,
            "recent_migration_log": migration_log,
            "has_archived_state": archive_total > 0,
        }

    return _with_db(_work)


def list_learner_profile_migration_log(*, limit: int = 50) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit), 500))

    def _work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT
                id,
                event_type,
                source_generation_id,
                source_index_version,
                target_generation_id,
                target_index_version,
                migrated_at,
                archived_counts_json,
                stamped_counts_json,
                live_counts_json,
                diagnostics_json
            FROM learner_profile_migration_log
            ORDER BY migrated_at DESC, id DESC
            LIMIT ?
            """,
            (lim,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for raw_key, parsed_key in (
                ("archived_counts_json", "archived_counts"),
                ("stamped_counts_json", "stamped_counts"),
                ("live_counts_json", "live_counts"),
                ("diagnostics_json", "diagnostics"),
            ):
                try:
                    item[parsed_key] = json.loads(str(item.pop(raw_key) or "{}"))
                except json.JSONDecodeError:
                    item[parsed_key] = {}
            out.append(item)
        return out

    return _with_db(_work)


def topic_resource_id(topic_id: str) -> str:
    return f"topic:{topic_id}"


def document_resource_id(relative_path: str) -> str:
    return f"doc:{relative_path}"


def qa_resource_id(question: str) -> str:
    h = hashlib.sha256((question or "").encode("utf-8")).hexdigest()[:20]
    return f"qa:{h}"


def learning_plan_resource_id(topic_id: str) -> str:
    return f"plan:{topic_id}"


def learning_plan_steps_from_markdown(plan_md: str) -> list[str]:
    """Split a markdown learning plan into coarse steps (numbered blocks or paragraphs)."""
    raw = (plan_md or "").strip()
    if not raw:
        return []
    lines = raw.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    for line in lines:
        if re.match(r"^\s*\d+\.\s+", line) and current:
            chunks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("\n".join(current).strip())
    cleaned = [c for c in chunks if c]
    if len(cleaned) <= 1:
        paras = [p.strip() for p in raw.split("\n\n") if p.strip()]
        return paras[:20] if paras else ([raw] if raw else [])
    return cleaned[:40]








































LEARNER_GOAL_SNAPSHOT_SCHEMA_VERSION = 1
_MAX_LGS_STR = 512
























# Метка последней Streamlit-сессии (UTC ISO) для US-7.2 gap detection.
STREAMLIT_LAST_ACTIVE_ISO_KEY = "streamlit_last_active_iso"


def get_kv(key: str, default: str | None = None) -> str | None:
    """Простой key-value слой для UI-настроек (без Streamlit)."""

    k = (key or "").strip()
    if not k or len(k) > 128:
        return default

    def _work(conn: sqlite3.Connection) -> str | None:
        row = conn.execute("SELECT value FROM app_kv WHERE key = ?", (k,)).fetchone()
        if not row:
            return default
        v = row["value"]
        return str(v) if v is not None else default

    return _with_db(_work)


def set_kv(key: str, value: str) -> None:
    k = (key or "").strip()
    if not k or len(k) > 128:
        return
    val = str(value) if value is not None else ""
    ts = _utc_now_iso()

    def _work(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO app_kv(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (k, val, ts),
        )
        conn.commit()

    _with_db(_work, write=True)


_SSR_STEERING_KV_KEY = "smart_study_steering_v1"
_VALID_SSR_STEERING = frozenset({"review_first", "new_topic", "gentle"})


def get_smart_study_steering_preference() -> str:
    """US-20.10: локальный «руль» Smart Study Router (пустая строка = базовая политика)."""

    v = (get_kv(_SSR_STEERING_KV_KEY) or "").strip().lower()
    if v in _VALID_SSR_STEERING:
        return v
    return ""


def set_smart_study_steering_preference(pref: str) -> None:
    s = (pref or "").strip().lower()
    if s not in _VALID_SSR_STEERING:
        return
    set_kv(_SSR_STEERING_KV_KEY, s)


def clear_smart_study_steering_preference() -> None:
    set_kv(_SSR_STEERING_KV_KEY, "")


_PREFERRED_STYLES = frozenset({"balanced", "examples", "theory", "practice"})
_WEEKLY_GOAL_KEYS = ("new_topics", "reviews", "quizzes")
_DEFAULT_WEEKLY_TARGETS: dict[str, int] = {"new_topics": 2, "reviews": 5, "quizzes": 3}
_DEFAULT_TUTOR_LEARNER_PROFILE: dict[str, Any] = {
    "sessions_count": 0,
    "preferred_style": "balanced",
    "last_route": "standard",
    "last_focus_topic": "general",
    "weak_concepts": [],
    "due_review_count": 0,
    "recent_topics": [],
}


def _iso_week_id() -> str:
    d = datetime.now(timezone.utc).date()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def get_preferred_style() -> str:
    """Стиль обучения для промпта тьютора: balanced | examples | theory | practice."""

    v = (get_kv("tutor_preferred_style") or "balanced").strip().lower()
    if v in _PREFERRED_STYLES:
        return v
    return "balanced"


def set_preferred_style(style: str) -> None:
    s = (style or "balanced").strip().lower()
    if s not in _PREFERRED_STYLES:
        s = "balanced"
    set_kv("tutor_preferred_style", s)
















SYNC_BUNDLE_VERSION = 1








# ─────────────────────────────────────────────────────────────
# Flashcard CRUD
# ─────────────────────────────────────────────────────────────

FLASHCARD_MASTERED_INTERVAL_DAYS = 21
_FLASHCARD_TAG_SEPARATORS_RE = re.compile(r"[,;|\n\r]+")






































from app import user_state_archive as _user_state_archive
from app import user_state_lineage as _user_state_lineage

get_current_learner_state_lineage = _user_state_lineage.get_current_learner_state_lineage
sync_current_learner_state_lineage = _user_state_lineage.sync_current_learner_state_lineage
_active_concept_ids_for_lineage = _user_state_lineage._active_concept_ids_for_lineage
_facade_override = _user_state_lineage._facade_override

list_archived_learner_state = _user_state_archive.list_archived_learner_state
restore_archived_learner_state = _user_state_archive.restore_archived_learner_state
purge_archived_learner_state = _user_state_archive.purge_archived_learner_state

__all__ = [name for name in globals() if not name.startswith("__")]
