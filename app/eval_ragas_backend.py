"""Optional RAGAS-compatible evaluation backend adapter."""

from __future__ import annotations

from importlib import import_module
from typing import Any

from app.config import get_settings


def run_ragas_cross_check(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Run optional RAGAS metrics when enabled; never make ragas a hard dependency."""
    if not get_settings().enable_ragas_metrics:
        return {"status": "disabled", "result": None}

    try:
        ragas = import_module("ragas")
    except ImportError:
        return {"status": "unavailable", "result": None}

    evaluate = getattr(ragas, "evaluate", None)
    if evaluate is None:
        return {"status": "unavailable", "result": None}

    return {"status": "ok", "result": evaluate(samples)}
