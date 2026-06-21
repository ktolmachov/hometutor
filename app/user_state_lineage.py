"""Learner state lineage: generation_id / index_version stamping and archive-on-rollover."""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from typing import Any

logger = logging.getLogger(__name__)


def _insert_learner_profile_migration_log(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    source_generation_id: str | None,
    source_index_version: int | None,
    target_generation_id: str | None,
    target_index_version: int | None,
    migrated_at: str,
    archived_counts: dict[str, int],
    stamped_counts: dict[str, int],
    live_counts: dict[str, int],
    diagnostics: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO learner_profile_migration_log(
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
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_type,
            source_generation_id,
            source_index_version,
            target_generation_id,
            target_index_version,
            migrated_at,
            json.dumps(archived_counts, ensure_ascii=False, sort_keys=True),
            json.dumps(stamped_counts, ensure_ascii=False, sort_keys=True),
            json.dumps(live_counts, ensure_ascii=False, sort_keys=True),
            json.dumps(diagnostics, ensure_ascii=False, sort_keys=True),
        ),
    )


def get_current_learner_state_lineage() -> dict[str, Any]:
    from app.user_state_core import _coerce_optional_int

    try:
        from app.index_registry import get_index_version_public

        raw = get_index_version_public()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.debug("learner_state_lineage_lookup_failed", exc_info=True)
        return {"generation_id": None, "index_version": None}
    if not isinstance(raw, dict):
        return {"generation_id": None, "index_version": None}
    return {
        "generation_id": str(raw.get("generation_id") or "").strip() or None,
        "index_version": _coerce_optional_int(raw.get("index_version")),
    }


def _active_concept_ids_for_lineage() -> set[str]:
    try:
        from app.knowledge_graph import get_active_knowledge_graph

        concepts = get_active_knowledge_graph().get_concepts()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.debug("learner_state_active_concepts_failed", exc_info=True)
        return set()
    return {
        str(concept_id).strip()
        for concept_id, node in concepts.items()
        if isinstance(node, dict) and str(concept_id).strip()
    }


def _facade_override(name: str, fallback: Any) -> Any:
    facade = sys.modules.get("app.user_state")
    if facade is None or facade is sys.modules.get(__name__):
        return fallback
    return getattr(facade, name, fallback)


def _lineage_sync_action(
    *,
    concept: str,
    row_generation_id: str | None,
    current_generation_id: str,
    active_concepts: set[str],
    first_sync: bool,
    generation_changed: bool,
) -> tuple[str, str | None]:
    in_active_graph = not active_concepts or concept in active_concepts
    if first_sync:
        if row_generation_id and row_generation_id != current_generation_id:
            return "archive", "generation_mismatch_initial"
        if not in_active_graph:
            return "archive", "inactive_concept_initial"
        return "stamp", None
    if generation_changed:
        if row_generation_id != current_generation_id:
            return "archive", "generation_rollover" if row_generation_id else "legacy_rollover"
        if not in_active_graph:
            return "archive", "inactive_concept_rollover"
        return "stamp", None
    if row_generation_id and row_generation_id != current_generation_id:
        return "archive", "generation_mismatch_repair"
    if not in_active_graph:
        return "archive", "inactive_concept_repair"
    return "stamp", None


def _archive_spaced_repetition_row(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    *,
    target_generation_id: str,
    target_index_version: int | None,
    archived_at: str,
    archived_reason: str,
) -> None:
    from app.user_state_core import _coerce_optional_int

    conn.execute(
        """
        INSERT INTO spaced_repetition_archive(
            concept, easiness, interval_days, repetitions, next_review, last_review,
            source_generation_id, source_index_version,
            target_generation_id, target_index_version,
            archived_at, archived_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.get("concept"),
            float(row.get("easiness") or 0.0),
            int(row.get("interval_days") or 1),
            int(row.get("repetitions") or 0),
            row.get("next_review"),
            row.get("last_review"),
            str(row.get("generation_id") or "").strip() or None,
            _coerce_optional_int(row.get("index_version")),
            target_generation_id,
            target_index_version,
            archived_at,
            archived_reason,
        ),
    )


def _archive_quiz_mastery_row(
    conn: sqlite3.Connection,
    row: dict[str, Any],
    *,
    target_generation_id: str,
    target_index_version: int | None,
    archived_at: str,
    archived_reason: str,
) -> None:
    from app.user_state_core import _coerce_optional_int

    conn.execute(
        """
        INSERT INTO quiz_mastery_archive(
            concept, current_level, success_streak, last_updated,
            source_generation_id, source_index_version,
            target_generation_id, target_index_version,
            archived_at, archived_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row.get("concept"),
            str(row.get("current_level") or "recognition").strip() or "recognition",
            int(row.get("success_streak") or 0),
            row.get("last_updated"),
            str(row.get("generation_id") or "").strip() or None,
            _coerce_optional_int(row.get("index_version")),
            target_generation_id,
            target_index_version,
            archived_at,
            archived_reason,
        ),
    )


def sync_current_learner_state_lineage(conn: sqlite3.Connection) -> dict[str, Any]:
    from app.user_state_core import (
        _LEARNER_STATE_GENERATION_KV_KEY,
        _LEARNER_STATE_INDEX_VERSION_KV_KEY,
        _LEARNER_STATE_MIGRATED_AT_KV_KEY,
        _coerce_optional_int,
        _read_kv_row,
        _upsert_kv_row,
    )
    from app.user_state_db import _utc_now_iso

    lineage_fn = _facade_override(
        "get_current_learner_state_lineage",
        get_current_learner_state_lineage,
    )
    lineage = lineage_fn()
    current_generation_id = str(lineage.get("generation_id") or "").strip()
    current_index_version = _coerce_optional_int(lineage.get("index_version"))
    if not current_generation_id:
        return {
            **lineage,
            "synced": False,
            "changed": False,
            "archived_counts": {"spaced_repetition": 0, "quiz_mastery": 0},
            "stamped_counts": {"spaced_repetition": 0, "quiz_mastery": 0},
        }

    marker_generation_id = str(_read_kv_row(conn, _LEARNER_STATE_GENERATION_KV_KEY) or "").strip() or None
    marker_index_version = _coerce_optional_int(_read_kv_row(conn, _LEARNER_STATE_INDEX_VERSION_KV_KEY))
    if (
        marker_generation_id == current_generation_id
        and marker_index_version == current_index_version
    ):
        return {
            **lineage,
            "synced": True,
            "changed": False,
            "previous_generation_id": marker_generation_id,
            "previous_index_version": marker_index_version,
            "archived_counts": {"spaced_repetition": 0, "quiz_mastery": 0},
            "stamped_counts": {"spaced_repetition": 0, "quiz_mastery": 0},
        }

    first_sync = marker_generation_id is None and marker_index_version is None
    generation_changed = marker_generation_id is not None and marker_generation_id != current_generation_id
    active_concepts_fn = _facade_override(
        "_active_concept_ids_for_lineage",
        _active_concept_ids_for_lineage,
    )
    active_concepts = active_concepts_fn()
    archived_at = _utc_now_iso()
    archived_counts = {"spaced_repetition": 0, "quiz_mastery": 0}
    stamped_counts = {"spaced_repetition": 0, "quiz_mastery": 0}

    spaced_rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT concept, easiness, interval_days, repetitions, next_review, last_review,
                   generation_id, index_version
            FROM spaced_repetition
            """
        ).fetchall()
    ]
    for row in spaced_rows:
        concept = str(row.get("concept") or "").strip()
        if not concept:
            continue
        row_generation_id = str(row.get("generation_id") or "").strip() or None
        action, reason = _lineage_sync_action(
            concept=concept,
            row_generation_id=row_generation_id,
            current_generation_id=current_generation_id,
            active_concepts=active_concepts,
            first_sync=first_sync,
            generation_changed=generation_changed,
        )
        if action == "archive":
            _archive_spaced_repetition_row(
                conn,
                row,
                target_generation_id=current_generation_id,
                target_index_version=current_index_version,
                archived_at=archived_at,
                archived_reason=str(reason or "generation_rollover"),
            )
            conn.execute("DELETE FROM spaced_repetition WHERE concept = ?", (concept,))
            archived_counts["spaced_repetition"] += 1
            continue
        conn.execute(
            """
            UPDATE spaced_repetition
            SET generation_id = ?, index_version = ?
            WHERE concept = ?
            """,
            (current_generation_id, current_index_version, concept),
        )
        stamped_counts["spaced_repetition"] += 1

    mastery_rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT concept, current_level, success_streak, last_updated,
                   generation_id, index_version
            FROM quiz_mastery
            """
        ).fetchall()
    ]
    for row in mastery_rows:
        concept = str(row.get("concept") or "").strip()
        if not concept:
            continue
        row_generation_id = str(row.get("generation_id") or "").strip() or None
        action, reason = _lineage_sync_action(
            concept=concept,
            row_generation_id=row_generation_id,
            current_generation_id=current_generation_id,
            active_concepts=active_concepts,
            first_sync=first_sync,
            generation_changed=generation_changed,
        )
        if action == "archive":
            _archive_quiz_mastery_row(
                conn,
                row,
                target_generation_id=current_generation_id,
                target_index_version=current_index_version,
                archived_at=archived_at,
                archived_reason=str(reason or "generation_rollover"),
            )
            conn.execute("DELETE FROM quiz_mastery WHERE concept = ?", (concept,))
            archived_counts["quiz_mastery"] += 1
            continue
        conn.execute(
            """
            UPDATE quiz_mastery
            SET generation_id = ?, index_version = ?
            WHERE concept = ?
            """,
            (current_generation_id, current_index_version, concept),
        )
        stamped_counts["quiz_mastery"] += 1

    _upsert_kv_row(conn, _LEARNER_STATE_GENERATION_KV_KEY, current_generation_id, archived_at)
    _upsert_kv_row(
        conn,
        _LEARNER_STATE_INDEX_VERSION_KV_KEY,
        str(current_index_version) if current_index_version is not None else "",
        archived_at,
    )
    _upsert_kv_row(conn, _LEARNER_STATE_MIGRATED_AT_KV_KEY, archived_at, archived_at)
    live_counts = {
        "spaced_repetition": int(
            (conn.execute("SELECT COUNT(*) AS n FROM spaced_repetition").fetchone() or {"n": 0})["n"] or 0
        ),
        "quiz_mastery": int(
            (conn.execute("SELECT COUNT(*) AS n FROM quiz_mastery").fetchone() or {"n": 0})["n"] or 0
        ),
    }
    if first_sync:
        event_type = "initial_sync"
    elif generation_changed:
        event_type = "generation_rollover"
    else:
        event_type = "index_version_update"
    diagnostics = {
        "first_sync": first_sync,
        "generation_changed": generation_changed,
        "active_concepts_total": len(active_concepts),
    }
    _insert_learner_profile_migration_log(
        conn,
        event_type=event_type,
        source_generation_id=marker_generation_id,
        source_index_version=marker_index_version,
        target_generation_id=current_generation_id,
        target_index_version=current_index_version,
        migrated_at=archived_at,
        archived_counts=archived_counts,
        stamped_counts=stamped_counts,
        live_counts=live_counts,
        diagnostics=diagnostics,
    )
    conn.commit()
    return {
        **lineage,
        "synced": True,
        "changed": True,
        "previous_generation_id": marker_generation_id,
        "previous_index_version": marker_index_version,
        "archived_counts": archived_counts,
        "stamped_counts": stamped_counts,
        "live_counts": live_counts,
        "migration_event_type": event_type,
        "migrated_at": archived_at,
    }

