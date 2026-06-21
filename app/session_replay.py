"""Lenient session tape reader."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app import session_tape as session_tape_module
from app.session_tape import sanitize_session_id

logger = logging.getLogger(__name__)


def _sessions_dir(*, sessions_dir: Path | None = None) -> Path:
    return sessions_dir or session_tape_module.SESSIONS_DIR


def _tape_path(session_id: str, *, sessions_dir: Path | None = None) -> Path:
    base = _sessions_dir(sessions_dir=sessions_dir)
    return base / f"{sanitize_session_id(session_id)}.jsonl"


def iter_events(
    session_id: str,
    *,
    sessions_dir: Path | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield parsed events; skip malformed lines without raising."""
    path = _tape_path(session_id, sessions_dir=sessions_dir)
    if not path.is_file():
        return

    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                logger.debug(
                    "session_replay_skip_bad_line session_id=%s line=%s: %s",
                    session_id,
                    line_no,
                    exc,
                )
                continue
            if isinstance(row, dict):
                yield row
