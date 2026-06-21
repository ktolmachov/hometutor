"""Shared due-queue display contract (no Streamlit)."""

from __future__ import annotations

from typing import Any

DUE_QUEUE_TOP_LIMIT = 7
DUE_QUEUE_OVERFLOW_THRESHOLD = 50


def due_queue_overflow_caption(total: int, shown: int) -> str:
    overflow = max(0, int(total) - int(shown))
    if overflow <= 0:
        return ""
    return f"ещё {overflow} отложено"


def is_soft_recovery_overflow(total: int) -> bool:
    return int(total) > DUE_QUEUE_OVERFLOW_THRESHOLD


def due_queue_preview_caption(
    rows: list[dict[str, Any]] | None,
    total: int,
    *,
    shown_limit: int = DUE_QUEUE_TOP_LIMIT,
) -> str:
    concepts = [
        str((row or {}).get("concept") or "").strip()
        for row in (rows or [])
        if str((row or {}).get("concept") or "").strip()
    ][:shown_limit]
    if not concepts:
        return ""
    preview = " · ".join(concepts)
    overflow_text = due_queue_overflow_caption(total, len(concepts))
    if overflow_text:
        return preview + f" · {overflow_text}"
    return preview


__all__ = [
    "DUE_QUEUE_OVERFLOW_THRESHOLD",
    "DUE_QUEUE_TOP_LIMIT",
    "due_queue_overflow_caption",
    "due_queue_preview_caption",
    "is_soft_recovery_overflow",
]
