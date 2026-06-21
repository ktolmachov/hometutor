from __future__ import annotations
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Any
import re
import hashlib

from app.user_state_core import *

def save_quiz_result(
    *,
    concept: str,
    level: str,
    score: float,
    attempt_number: int = 1,
) -> int:
    """Сохранить результат проверки (inline quiz / self-check). Возвращает id строки."""

    def _work(conn: sqlite3.Connection) -> int:
        lineage = sync_current_learner_state_lineage(conn)
        ts = _utc_now_iso()
        cur = conn.execute(
            """
            INSERT INTO quiz_results(
                concept, level, score, timestamp, attempt_number, generation_id, index_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                concept,
                level,
                score,
                ts,
                attempt_number,
                lineage.get("generation_id"),
                _coerce_optional_int(lineage.get("index_version")),
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    return _with_db(_work, write=True)


def get_recent_quiz_levels_low_score(concept: str, *, limit: int = 5) -> list[str]:
    """Уровни (recognition/recall/transfer) последних попыток с низким score по концепту."""

    c = (concept or "").strip() or "general"
    lim = max(1, min(int(limit), 20))

    def _work(conn: sqlite3.Connection) -> list[str]:
        lineage = sync_current_learner_state_lineage(conn)
        current_generation_id = str(lineage.get("generation_id") or "").strip()
        where = """
            concept = ? AND score < 0.7
        """
        params: list[Any] = [c]
        if current_generation_id:
            where += " AND generation_id = ?"
            params.append(current_generation_id)
        rows = conn.execute(
            f"""
            SELECT level FROM quiz_results
            WHERE {where}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (*params, lim),
        ).fetchall()
        out: list[str] = []
        for r in rows:
            lv = str(r["level"] or "").strip().lower()
            if lv and lv not in out:
                out.append(lv)
        return out

    return _with_db(_work)


def save_micro_quiz_outcome(
    *,
    topic: str,
    quiz_feedback: dict[str, Any],
    recommended_next: dict[str, Any],
) -> int:
    """Сохранить итог micro-quiz + рекомендацию learning plan (SQLite)."""

    def _work(conn: sqlite3.Connection) -> int:
        ts = _utc_now_iso()
        cur = conn.execute(
            """
            INSERT INTO micro_quiz_events(topic, feedback_json, next_step_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                (topic or "").strip() or None,
                json.dumps(quiz_feedback, ensure_ascii=False),
                json.dumps(recommended_next, ensure_ascii=False),
                ts,
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    return _with_db(_work, write=True)

