"""Pace mode helpers for Course plan.v2."""
from __future__ import annotations

from typing import Any

PACE_MODES = ("sprint", "steady", "deep")
DEFAULT_PACE_MODE = "steady"

PACE_MODE_LABELS = {
    "sprint": "Sprint",
    "steady": "Steady",
    "deep": "Deep",
}


def normalize_pace_mode(value: Any, *, default: str = DEFAULT_PACE_MODE) -> str:
    """Normalize user/system value into one of sprint/steady/deep."""
    candidate = str(value or "").strip().lower()
    if candidate in PACE_MODES:
        return candidate
    return default


def pace_mode_label(value: Any) -> str:
    """Human-friendly pace mode label for UI rendering."""
    mode = normalize_pace_mode(value)
    return PACE_MODE_LABELS.get(mode, PACE_MODE_LABELS[DEFAULT_PACE_MODE])

