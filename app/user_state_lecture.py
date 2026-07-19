"""Lecture segment progress persistence (#19 P1).

Stores per-konspekt segment gate results so the «глубина лекции с подтверждением»
metric survives restart and is visible on the progress dashboard.

Table: lecture_segment_progress (in user_state.db)
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from app.user_state_core import _utc_now_iso, _with_db

logger = logging.getLogger(__name__)


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS lecture_segment_progress (
            konspekt_path  TEXT NOT NULL,
            segment_index  INTEGER NOT NULL,
            passed         INTEGER NOT NULL DEFAULT 0,
            predicted_correct  INTEGER DEFAULT NULL,
            gate_score     REAL,
            completed_at   TEXT NOT NULL,
            PRIMARY KEY (konspekt_path, segment_index)
        )
        """
    )


def upsert_lecture_segment_result(
    *,
    konspekt_path: str,
    segment_index: int,
    passed: bool,
    predicted_correct: bool | None = None,
    gate_score: float | None = None,
) -> None:
    """Record one segment gate result. Called from _advance_segment after gate."""
    ts = _utc_now_iso()

    def _work(conn: sqlite3.Connection) -> None:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT INTO lecture_segment_progress(
                konspekt_path, segment_index, passed, predicted_correct,
                gate_score, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(konspekt_path, segment_index) DO UPDATE SET
                passed = excluded.passed,
                predicted_correct = excluded.predicted_correct,
                gate_score = excluded.gate_score,
                completed_at = excluded.completed_at
            """,
            (
                konspekt_path,
                segment_index,
                1 if passed else 0,
                predicted_correct,
                gate_score,
                ts,
            ),
        )

    try:
        _with_db(_work, write=True)
    except Exception:  # noqa: BLE001 — best-effort persistence, never block UI
        logger.warning("lecture_segment_upsert_failed", exc_info=True)


def get_lecture_segment_results(konspekt_path: str) -> list[dict[str, Any]]:
    """Return all segment results for a konspekt, ordered by segment_index."""

    def _read(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        _ensure_table(conn)
        rows = conn.execute(
            """
            SELECT konspekt_path, segment_index, passed, predicted_correct,
                   gate_score, completed_at
            FROM lecture_segment_progress
            WHERE konspekt_path = ?
            ORDER BY segment_index
            """,
            (konspekt_path,),
        ).fetchall()
        return [
            {
                "konspekt_path": r[0],
                "segment_index": r[1],
                "passed": bool(r[2]),
                "predicted_correct": bool(r[3]) if r[3] is not None else None,
                "gate_score": r[4],
                "completed_at": r[5],
            }
            for r in rows
        ]

    try:
        return _with_db(_read)
    except Exception:  # noqa: BLE001
        logger.warning("lecture_segment_read_failed", exc_info=True)
        return []


def compute_lecture_depth(
    konspekt_path: str,
    total_segments: int,
) -> dict[str, Any]:
    """Return a privacy-safe depth snapshot for progress display.

    Returns dict with:
      - passed_count: int
      - total_segments: int
      - depth_pct: float (passed / total, 0.0–100.0)
      - predicted_correct_count: int (segments with correct prediction)
      - last_completed_at: str | None
    """
    results = get_lecture_segment_results(konspekt_path)
    passed = [r for r in results if r["passed"]]
    predicted_correct = [r for r in results if r.get("predicted_correct") is True]
    last_ts = max((r.get("completed_at", "") for r in results if r.get("completed_at")), default=None)

    effective_total = max(total_segments, len(results))

    return {
        "passed_count": len(passed),
        "total_segments": effective_total,
        "depth_pct": round(len(passed) / effective_total * 100, 1) if effective_total else 0.0,
        "predicted_correct_count": len(predicted_correct),
        "last_completed_at": last_ts,
    }
