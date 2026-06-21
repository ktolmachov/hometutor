"""Локальная статистика UI-квизов: отвечено вопросов, сессии, streak по дням."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

_STATS_FILE = DATA_DIR / "quiz_ui_stats.json"


def _today_utc() -> str:
    return datetime.now(tz=timezone.utc).date().isoformat()


def load_quiz_ui_stats() -> Dict[str, Any]:
    if not _STATS_FILE.exists():
        return {
            "total_questions_answered": 0,
            "quiz_sessions_completed": 0,
            "last_activity_date": "",
            "streak_days": 0,
        }
    try:
        raw = json.loads(_STATS_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("not an object")
        return {
            "total_questions_answered": int(raw.get("total_questions_answered", 0)),
            "quiz_sessions_completed": int(raw.get("quiz_sessions_completed", 0)),
            "last_activity_date": str(raw.get("last_activity_date", "") or ""),
            "streak_days": int(raw.get("streak_days", 0)),
        }
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("quiz_stats_load_failed | error=%s", e)
        return {
            "total_questions_answered": 0,
            "quiz_sessions_completed": 0,
            "last_activity_date": "",
            "streak_days": 0,
        }


def record_quiz_session_completed(*, total_questions: int, correct: int) -> Dict[str, Any]:
    """Вызывается после успешного «Завершить quiz» (одна сессия)."""
    total_questions = max(0, int(total_questions))
    correct = max(0, min(correct, total_questions))
    stats = load_quiz_ui_stats()
    stats["total_questions_answered"] = stats["total_questions_answered"] + total_questions
    stats["quiz_sessions_completed"] = stats["quiz_sessions_completed"] + 1

    today = _today_utc()
    prev = (stats.get("last_activity_date") or "").strip()
    streak = int(stats.get("streak_days", 0))
    if not prev:
        streak = 1
    else:
        try:
            pd = date.fromisoformat(prev)
            td = date.fromisoformat(today)
            delta = (td - pd).days
            if delta == 0:
                streak = max(1, streak)
            elif delta == 1:
                streak = streak + 1
            else:
                streak = 1
        except ValueError:
            streak = 1
    stats["last_activity_date"] = today
    stats["streak_days"] = max(1, streak)

    try:
        _STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("quiz_stats_save_failed | error=%s", e)
    return stats


def save_quiz_ui_stats_raw(stats: Dict[str, Any]) -> None:
    """Прямая запись JSON (импорт sync / восстановление)."""
    try:
        out = {
            "total_questions_answered": int(stats.get("total_questions_answered", 0)),
            "quiz_sessions_completed": int(stats.get("quiz_sessions_completed", 0)),
            "last_activity_date": str(stats.get("last_activity_date", "") or ""),
            "streak_days": int(stats.get("streak_days", 0)),
        }
        _STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATS_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, TypeError, ValueError) as e:
        logger.warning("quiz_stats_save_raw_failed | error=%s", e)


__all__ = ["load_quiz_ui_stats", "record_quiz_session_completed", "save_quiz_ui_stats_raw"]
