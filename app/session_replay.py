"""Read-only session tape replay helpers."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.session_tape import SESSIONS_DIR, sanitize_session_id


def iter_events(
    session_id: str,
    *,
    sessions_dir: Path | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield valid JSON event rows for a session tape, skipping malformed lines."""
    path = (sessions_dir or SESSIONS_DIR) / f"{sanitize_session_id(session_id)}.jsonl"
    if not path.is_file():
        return

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row
