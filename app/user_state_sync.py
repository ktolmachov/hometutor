from __future__ import annotations
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Any
import re
import hashlib

_log = logging.getLogger(__name__)
_SYNC_EXPORT_ROW_LIMIT = 10_000

from app.user_state_core import *
from app.user_state_core import _quote_sync_columns, _quote_sync_table

def export_full_sync_bundle() -> dict[str, Any]:
    """
    Локальный снимок прогресса: SQLite (user_state) + ``quiz_ui_stats.json``.
    Для переноса между устройствами без облака (файл, USB, мессенджер).
    """
    from app.quiz_stats import load_quiz_ui_stats

    def _work(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
        tables: dict[str, list[dict[str, Any]]] = {}
        for name in _SYNC_TABLES_ORDER:
            table_sql = _quote_sync_table(name)
            rows = conn.execute(
                f"SELECT * FROM {table_sql} LIMIT ?", (_SYNC_EXPORT_ROW_LIMIT,)
            ).fetchall()
            if len(rows) == _SYNC_EXPORT_ROW_LIMIT:
                _log.warning("export_full_sync_bundle: table %r hit row cap %d", name, _SYNC_EXPORT_ROW_LIMIT)
            tables[name] = [dict(r) for r in rows]
        return tables

    tables = _with_db(_work)
    return {
        "sync_version": SYNC_BUNDLE_VERSION,
        "exported_at": _utc_now_iso(),
        "tables": tables,
        "quiz_ui_stats": load_quiz_ui_stats(),
        "learner_state_diagnostics": get_learner_state_diagnostics(),
    }


def preview_full_sync_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """
    US-10.2: валидация снимка без записи в БД — sync_version, счётчики строк по таблицам.
    """
    ver = int(bundle.get("sync_version") or 0)
    if ver != SYNC_BUNDLE_VERSION:
        raise ValueError(f"unsupported sync_version: {ver!r}")

    tables_in = bundle.get("tables")
    if not isinstance(tables_in, dict):
        raise ValueError("bundle.tables must be a dict")

    counts: dict[str, int] = {}
    total_rows = 0
    for name in _SYNC_TABLES_ORDER:
        rows = tables_in.get(name)
        n = len(rows) if isinstance(rows, list) else 0
        counts[name] = n
        total_rows += n
    qs = bundle.get("quiz_ui_stats")
    quiz_keys = len(qs) if isinstance(qs, dict) else 0
    return {
        "sync_version": ver,
        "exported_at": bundle.get("exported_at"),
        "table_row_counts": counts,
        "total_rows": total_rows,
        "quiz_ui_stats_field_count": quiz_keys,
    }


def import_full_sync_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """
    Полная замена данных из ``export_full_sync_bundle`` (осторожно: перезаписывает локальный прогресс).
    """
    ver = int(bundle.get("sync_version") or 0)
    if ver != SYNC_BUNDLE_VERSION:
        raise ValueError(f"unsupported sync_version: {ver!r}")

    tables_in = bundle.get("tables")
    if not isinstance(tables_in, dict):
        raise ValueError("bundle.tables must be a dict")

    def _work(conn: sqlite3.Connection) -> int:
        total_ins = 0
        for name in _SYNC_TABLES_ORDER:
            table_sql = _quote_sync_table(name)
            conn.execute(f"DELETE FROM {table_sql}")
        for name in _SYNC_TABLES_ORDER:
            rows = tables_in.get(name)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict) or not row:
                    continue
                cols = [str(k) for k in row.keys()]
                quoted_cols = _quote_sync_columns(name, cols)
                placeholders = ",".join(["?"] * len(cols))
                table_sql = _quote_sync_table(name)
                columns_sql = ",".join(quoted_cols)
                sql = (
                    f"INSERT INTO {table_sql} ({columns_sql}) "
                    f"VALUES ({placeholders})"
                )
                conn.execute(sql, tuple(row[c] for c in cols))
                total_ins += 1
        conn.commit()
        return total_ins

    n = _with_db(_work, write=True)
    qs = bundle.get("quiz_ui_stats")
    if isinstance(qs, dict):
        from app.quiz_stats import save_quiz_ui_stats_raw

        save_quiz_ui_stats_raw(qs)
    return {"rows_inserted": n, "sync_version": SYNC_BUNDLE_VERSION}

