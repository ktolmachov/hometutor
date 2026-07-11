from __future__ import annotations
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Any
import re
import hashlib

from app.user_state_core import *

def upsert_reading_status(
    *,
    resource_type: str,
    resource_id: str,
    step_index: int | None = None,
    step_label: str | None = None,
    progress: float | None = None,
    display_title: str | None = None,
    index_version: str | None = None,
) -> None:
    ts = _utc_now_iso()

    def _work(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO reading_status(
                resource_type, resource_id, step_index, step_label, progress,
                display_title, index_version, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(resource_type, resource_id) DO UPDATE SET
                step_index = excluded.step_index,
                step_label = excluded.step_label,
                progress = excluded.progress,
                display_title = excluded.display_title,
                index_version = excluded.index_version,
                updated_at = excluded.updated_at
            """,
            (
                resource_type,
                resource_id,
                step_index,
                step_label,
                progress,
                display_title,
                index_version,
                ts,
            ),
        )
        conn.commit()

    _with_db(_work, write=True)


def get_latest_resume() -> dict[str, Any] | None:
    def _work(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT resource_type, resource_id, step_index, step_label, progress,
                   display_title, index_version, updated_at
            FROM reading_status
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        return dict(row)

    return _with_db(_work)


def get_latest_learning_plan_resume() -> dict[str, Any] | None:
    """Latest reading_status row where resource_type == 'learning_plan', or None."""

    def _work(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT resource_type, resource_id, step_index, step_label, progress,
                   display_title, index_version, updated_at
            FROM reading_status
            WHERE resource_type = 'learning_plan'
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ).fetchone()
        return dict(row) if row else None

    return _with_db(_work)


def get_topic_progress(topic_id: str) -> float | None:
    rid = topic_resource_id(topic_id)

    def _work(conn: sqlite3.Connection) -> float | None:
        row = conn.execute(
            "SELECT progress FROM reading_status WHERE resource_type = ? AND resource_id = ?",
            ("topic", rid),
        ).fetchone()
        if not row or row["progress"] is None:
            return None
        return float(row["progress"])

    return _with_db(_work)


def get_reading_status(resource_type: str, resource_id: str) -> dict[str, Any] | None:
    def _work(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = conn.execute(
            """
            SELECT resource_type, resource_id, step_index, step_label, progress,
                   display_title, index_version, updated_at
            FROM reading_status
            WHERE resource_type = ? AND resource_id = ?
            LIMIT 1
            """,
            (resource_type, resource_id),
        ).fetchone()
        return dict(row) if row else None

    return _with_db(_work)


def list_topic_reading_rows(*, limit: int = 200) -> list[dict[str, Any]]:
    """Краткий список прогресса по темам (`resource_type='topic'`) для дашборда."""

    def _work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT resource_id, progress, display_title, updated_at
            FROM reading_status
            WHERE resource_type = 'topic'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            rid = str(d.get("resource_id") or "")
            tid = rid[6:] if rid.startswith("topic:") else rid
            d["topic_id"] = tid
            out.append(d)
        return out

    return _with_db(_work)


def get_topic_states(topic_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not topic_ids:
        return {}
    rids = [topic_resource_id(t) for t in topic_ids]
    placeholders = ",".join("?" * len(rids))

    def _work(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {tid: {"progress": None, "bookmarked": False} for tid in topic_ids}
        rid_to_tid = {topic_resource_id(t): t for t in topic_ids}
        rows = conn.execute(
            f"""
            SELECT resource_id, progress FROM reading_status
            WHERE resource_type = 'topic' AND resource_id IN ({placeholders})
            """,
            rids,
        ).fetchall()
        for row in rows:
            tid = rid_to_tid.get(row["resource_id"])
            if tid is not None and row["progress"] is not None:
                out[tid]["progress"] = float(row["progress"])
        bmarks = conn.execute(
            f"""
            SELECT resource_id FROM annotations
            WHERE kind = 'bookmark' AND resource_type = 'topic'
            AND resource_id IN ({placeholders})
            """,
            rids,
        ).fetchall()
        for row in bmarks:
            tid = rid_to_tid.get(row["resource_id"])
            if tid is not None:
                out[tid]["bookmarked"] = True
        return out

    return _with_db(_work)


def has_bookmark(resource_type: str, resource_id: str) -> bool:
    def _work(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            """
            SELECT 1 FROM annotations
            WHERE resource_type = ? AND resource_id = ? AND kind = 'bookmark'
            LIMIT 1
            """,
            (resource_type, resource_id),
        ).fetchone()
        return row is not None

    return _with_db(_work)


def toggle_bookmark(resource_type: str, resource_id: str) -> bool:
    def _work(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            """
            SELECT id FROM annotations
            WHERE resource_type = ? AND resource_id = ? AND kind = 'bookmark'
            """,
            (resource_type, resource_id),
        ).fetchone()
        if row:
            conn.execute("DELETE FROM annotations WHERE id = ?", (row["id"],))
            conn.commit()
            return False
        conn.execute(
            """
            INSERT INTO annotations(resource_type, resource_id, kind, body, created_at)
            VALUES (?, ?, 'bookmark', '', ?)
            """,
            (resource_type, resource_id, _utc_now_iso()),
        )
        conn.commit()
        return True

    return _with_db(_work, write=True)


def add_note(resource_type: str, resource_id: str, body: str) -> int:
    def _work(conn: sqlite3.Connection) -> int:
        cur = conn.execute(
            """
            INSERT INTO annotations(resource_type, resource_id, kind, body, created_at)
            VALUES (?, ?, 'note', ?, ?)
            """,
            (resource_type, resource_id, (body or "").strip(), _utc_now_iso()),
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    return _with_db(_work, write=True)


def delete_annotation(annotation_id: int) -> None:
    def _work(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
        conn.commit()

    return _with_db(_work, write=True)


def list_annotations(*, limit: int = 50) -> list[dict[str, Any]]:
    def _work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT id, resource_type, resource_id, kind, body, created_at
            FROM annotations
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    return _with_db(_work)


def count_reading_at_least_progress(threshold: float = 0.85) -> int:
    """Число записей reading_status с progress >= threshold (для бейджей геймификации)."""

    t = float(threshold)
    t = max(0.0, min(1.0, t))

    def _work(conn: sqlite3.Connection) -> int:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM reading_status
            WHERE progress IS NOT NULL AND progress >= ?
            """,
            (t,),
        ).fetchone()
        return int(row["n"] or 0) if row else 0

    return _with_db(_work)


def format_resource_label(resource_type: str, resource_id: str) -> str:
    if resource_id.startswith("topic:"):
        return f"тема {resource_id.split(':', 1)[1]}"
    if resource_id.startswith("doc:"):
        return resource_id.split(":", 1)[1]
    if resource_id.startswith("plan:"):
        return f"план {resource_id.split(':', 1)[1]}"
    if resource_id.startswith("qa:"):
        return f"ответ ({resource_id})"
    return f"{resource_type}:{resource_id}"

