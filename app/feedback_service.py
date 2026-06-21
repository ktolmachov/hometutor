"""Human feedback (👍/👎) для ответов — JSONL + filelock (итерация 14)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from app.config import get_settings
from app.logging_config import setup_logging

logger = setup_logging()

FEEDBACK_SCHEMA_VERSION = 1
FEEDBACK_PATH = Path(get_settings().feedback_path)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def append_feedback(
    *,
    helpful: bool,
    request_id: str | None = None,
    comment: str | None = None,
    question_preview: str | None = None,
    source: str = "ui",
) -> None:
    entry: dict[str, Any] = {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "timestamp": _now_iso(),
        "request_id": (request_id or "").strip() or None,
        "helpful": bool(helpful),
        "comment": (comment or "")[:500],
        "question_preview": (question_preview or "")[:240],
        "source": (source or "ui").strip()[:64] or "ui",
    }
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(FEEDBACK_PATH) + ".lock")
    try:
        with FileLock(lock_path):
            with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("feedback append failed: %s", e)


def get_feedback_summary(*, limit_lines: int = 5000) -> dict[str, Any]:
    if limit_lines < 1:
        limit_lines = 1
    if not FEEDBACK_PATH.exists():
        return {
            "schema_version": FEEDBACK_SCHEMA_VERSION,
            "total_events": 0,
            "helpful_yes": 0,
            "helpful_no": 0,
            "helpful_rate": None,
        }

    yes = 0
    no = 0
    total = 0
    try:
        with open(FEEDBACK_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit_lines:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("helpful") is True:
                yes += 1
                total += 1
            elif row.get("helpful") is False:
                no += 1
                total += 1
    except OSError as e:
        logger.warning("feedback summary read failed: %s", e)
        return {
            "schema_version": FEEDBACK_SCHEMA_VERSION,
            "total_events": 0,
            "helpful_yes": 0,
            "helpful_no": 0,
            "helpful_rate": None,
            "error": str(e),
        }

    rate = round(yes / total, 3) if total else None
    return {
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "total_events": total,
        "helpful_yes": yes,
        "helpful_no": no,
        "helpful_rate": rate,
    }
