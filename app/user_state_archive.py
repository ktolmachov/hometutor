from __future__ import annotations

import sqlite3
from typing import Any

from app.user_state_db import (
    _ALLOWED_ARCHIVE_STATE_TABLES,
    _ARCHIVE_STATE_TABLES,
    _normalize_archive_state_table,
    _quote_allowed_identifier,
    _quote_archive_table,
)


def _archive_rows_for_filters(
    conn: sqlite3.Connection,
    *,
    source_generation_id: str | None = None,
    target_generation_id: str | None = None,
    archived_reason: str | None = None,
    state_table: str | None = None,
    limit: int = 100,
) -> tuple[int, list[dict[str, Any]]]:
    tables = [_normalize_archive_state_table(state_table)] if state_table else list(_ARCHIVE_STATE_TABLES)
    lim = max(1, min(int(limit), 500))
    filters: list[tuple[str, Any]] = []
    if str(source_generation_id or "").strip():
        filters.append(("source_generation_id = ?", str(source_generation_id).strip()))
    if str(target_generation_id or "").strip():
        filters.append(("target_generation_id = ?", str(target_generation_id).strip()))
    if str(archived_reason or "").strip():
        filters.append(("archived_reason = ?", str(archived_reason).strip()))

    total = 0
    select_sql_parts: list[str] = []
    select_params: list[Any] = []
    for table in tables:
        archive_table_sql = _quote_archive_table(table)
        where_sql = " AND ".join(["1=1"] + [item[0] for item in filters])
        params = [item[1] for item in filters]
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {archive_table_sql} WHERE {where_sql}",
            params,
        ).fetchone()
        total += int(row["n"] or 0) if row else 0
        select_sql_parts.append(
            f"""
            SELECT
                '{table}' AS state_table,
                concept,
                source_generation_id,
                source_index_version,
                target_generation_id,
                target_index_version,
                archived_at,
                archived_reason
            FROM {archive_table_sql}
            WHERE {where_sql}
            """
        )
        select_params.extend(params)

    if not select_sql_parts:
        return 0, []
    rows = conn.execute(
        f"""
        SELECT * FROM (
            {' UNION ALL '.join(select_sql_parts)}
        )
        ORDER BY archived_at DESC
        LIMIT ?
        """,
        (*select_params, lim),
    ).fetchall()
    return total, [dict(row) for row in rows]


def list_archived_learner_state(
    *,
    source_generation_id: str | None = None,
    target_generation_id: str | None = None,
    archived_reason: str | None = None,
    state_table: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    from app.user_state_core import _with_db, sync_current_learner_state_lineage

    def _work(conn: sqlite3.Connection) -> dict[str, Any]:
        sync_current_learner_state_lineage(conn)
        total, items = _archive_rows_for_filters(
            conn,
            source_generation_id=source_generation_id,
            target_generation_id=target_generation_id,
            archived_reason=archived_reason,
            state_table=state_table,
            limit=limit,
        )
        return {
            "total": total,
            "items": items,
            "filters": {
                "source_generation_id": str(source_generation_id or "").strip() or None,
                "target_generation_id": str(target_generation_id or "").strip() or None,
                "archived_reason": str(archived_reason or "").strip() or None,
                "state_table": _normalize_archive_state_table(state_table),
                "limit": max(1, min(int(limit), 500)),
            },
        }

    return _with_db(_work)


def restore_archived_learner_state(
    *,
    source_generation_id: str,
    state_table: str | None = None,
    limit: int = 100,
    overwrite: bool = False,
) -> dict[str, Any]:
    from app.user_state_core import (
        _coerce_optional_int,
        _with_db,
        sync_current_learner_state_lineage,
    )
    from app.user_state_lineage import _active_concept_ids_for_lineage, _facade_override

    source_gid = str(source_generation_id or "").strip()
    if not source_gid:
        raise ValueError("source_generation_id is required")
    norm_state_table = _normalize_archive_state_table(state_table)

    def _restore_spaced_repetition(
        conn: sqlite3.Connection,
        row: dict[str, Any],
        *,
        current_generation_id: str,
        current_index_version: int | None,
    ) -> None:
        raw = conn.execute(
            """
            SELECT concept, easiness, interval_days, repetitions, next_review, last_review
            FROM spaced_repetition_archive
            WHERE concept = ? AND source_generation_id = ? AND archived_at = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (row["concept"], source_gid, row["archived_at"]),
        ).fetchone()
        if not raw:
            return
        rr = dict(raw)
        conn.execute(
            """
            INSERT INTO spaced_repetition(
                concept, easiness, interval_days, repetitions, next_review, last_review,
                generation_id, index_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(concept) DO UPDATE SET
                easiness = excluded.easiness,
                interval_days = excluded.interval_days,
                repetitions = excluded.repetitions,
                next_review = excluded.next_review,
                last_review = excluded.last_review,
                generation_id = excluded.generation_id,
                index_version = excluded.index_version
            """,
            (
                rr["concept"],
                float(rr["easiness"] or 0.0),
                int(rr["interval_days"] or 1),
                int(rr["repetitions"] or 0),
                rr["next_review"],
                rr["last_review"],
                current_generation_id,
                current_index_version,
            ),
        )

    def _restore_quiz_mastery(
        conn: sqlite3.Connection,
        row: dict[str, Any],
        *,
        current_generation_id: str,
        current_index_version: int | None,
    ) -> None:
        raw = conn.execute(
            """
            SELECT concept, current_level, success_streak, last_updated
            FROM quiz_mastery_archive
            WHERE concept = ? AND source_generation_id = ? AND archived_at = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (row["concept"], source_gid, row["archived_at"]),
        ).fetchone()
        if not raw:
            return
        rr = dict(raw)
        conn.execute(
            """
            INSERT INTO quiz_mastery(
                concept, current_level, success_streak, last_updated, generation_id, index_version
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(concept) DO UPDATE SET
                current_level = excluded.current_level,
                success_streak = excluded.success_streak,
                last_updated = excluded.last_updated,
                generation_id = excluded.generation_id,
                index_version = excluded.index_version
            """,
            (
                rr["concept"],
                rr["current_level"],
                int(rr["success_streak"] or 0),
                rr["last_updated"],
                current_generation_id,
                current_index_version,
            ),
        )

    def _work(conn: sqlite3.Connection) -> dict[str, Any]:
        lineage = sync_current_learner_state_lineage(conn)
        current_generation_id = str(lineage.get("generation_id") or "").strip()
        current_index_version = _coerce_optional_int(lineage.get("index_version"))
        if not current_generation_id:
            raise ValueError("current generation_id is unavailable")
        active_concepts_fn = _facade_override(
            "_active_concept_ids_for_lineage",
            _active_concept_ids_for_lineage,
        )
        active_concepts = active_concepts_fn()
        _, items = _archive_rows_for_filters(
            conn,
            source_generation_id=source_gid,
            state_table=norm_state_table,
            limit=limit,
        )
        restored_by_table = {name: 0 for name in _ARCHIVE_STATE_TABLES}
        skipped_existing = 0
        skipped_inactive = 0
        seen: set[tuple[str, str]] = set()
        restored_items: list[dict[str, Any]] = []
        for row in items:
            table = str(row.get("state_table") or "").strip()
            concept = str(row.get("concept") or "").strip()
            if not table or not concept:
                continue
            key = (table, concept)
            if key in seen:
                continue
            seen.add(key)
            if active_concepts and concept not in active_concepts:
                skipped_inactive += 1
                continue
            table_sql = _quote_allowed_identifier(
                table,
                _ALLOWED_ARCHIVE_STATE_TABLES,
                kind="state table",
            )
            live_exists = conn.execute(
                f"SELECT 1 FROM {table_sql} WHERE concept = ? LIMIT 1",
                (concept,),
            ).fetchone()
            if live_exists and not overwrite:
                skipped_existing += 1
                continue
            if table == "spaced_repetition":
                _restore_spaced_repetition(
                    conn,
                    row,
                    current_generation_id=current_generation_id,
                    current_index_version=current_index_version,
                )
            elif table == "quiz_mastery":
                _restore_quiz_mastery(
                    conn,
                    row,
                    current_generation_id=current_generation_id,
                    current_index_version=current_index_version,
                )
            else:
                continue
            restored_by_table[table] += 1
            restored_items.append(
                {
                    "state_table": table,
                    "concept": concept,
                    "restored_into_generation_id": current_generation_id,
                    "restored_into_index_version": current_index_version,
                }
            )
        conn.commit()
        restored_total = sum(restored_by_table.values())
        return {
            "source_generation_id": source_gid,
            "restored_total": restored_total,
            "restored_by_table": restored_by_table,
            "skipped_existing": skipped_existing,
            "skipped_inactive": skipped_inactive,
            "overwrite": bool(overwrite),
            "target_lineage": {
                "generation_id": current_generation_id,
                "index_version": current_index_version,
            },
            "items": restored_items,
        }

    return _with_db(_work, write=True)


def purge_archived_learner_state(
    *,
    source_generation_id: str | None = None,
    target_generation_id: str | None = None,
    archived_reason: str | None = None,
    state_table: str | None = None,
    allow_all: bool = False,
) -> dict[str, Any]:
    from app.user_state_core import _with_db, sync_current_learner_state_lineage

    norm_state_table = _normalize_archive_state_table(state_table)
    filters_present = any(
        str(value or "").strip()
        for value in (source_generation_id, target_generation_id, archived_reason)
    ) or bool(norm_state_table)
    if not filters_present and not allow_all:
        raise ValueError("purge requires at least one filter or allow_all=True")

    def _work(conn: sqlite3.Connection) -> dict[str, Any]:
        sync_current_learner_state_lineage(conn)
        tables = [norm_state_table] if norm_state_table else list(_ARCHIVE_STATE_TABLES)
        deleted_by_table = {name: 0 for name in _ARCHIVE_STATE_TABLES}
        for table in tables:
            archive_table_sql = _quote_archive_table(table)
            clauses = ["1=1"]
            params: list[Any] = []
            if str(source_generation_id or "").strip():
                clauses.append("source_generation_id = ?")
                params.append(str(source_generation_id).strip())
            if str(target_generation_id or "").strip():
                clauses.append("target_generation_id = ?")
                params.append(str(target_generation_id).strip())
            if str(archived_reason or "").strip():
                clauses.append("archived_reason = ?")
                params.append(str(archived_reason).strip())
            cur = conn.execute(
                f"DELETE FROM {archive_table_sql} WHERE {' AND '.join(clauses)}",
                params,
            )
            deleted_by_table[table] = int(cur.rowcount or 0)
        conn.commit()
        return {
            "deleted_total": sum(deleted_by_table.values()),
            "deleted_by_table": deleted_by_table,
            "filters": {
                "source_generation_id": str(source_generation_id or "").strip() or None,
                "target_generation_id": str(target_generation_id or "").strip() or None,
                "archived_reason": str(archived_reason or "").strip() or None,
                "state_table": norm_state_table,
                "allow_all": bool(allow_all),
            },
        }

    return _with_db(_work, write=True)








