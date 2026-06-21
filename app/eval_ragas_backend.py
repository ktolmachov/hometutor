"""Optional RAGAS cross-check adapter; native eval metrics remain authoritative."""

from importlib import import_module
from typing import Any

from app.config import get_settings


def run_ragas_cross_check(dataset: Any) -> dict[str, Any]:
    """Run the installed RAGAS evaluator only when explicitly enabled."""
    if not get_settings().enable_ragas_metrics:
        return {"status": "disabled", "result": None}

    try:
        ragas = import_module("ragas")
    except ImportError:
        return {"status": "unavailable", "result": None}

    evaluate = getattr(ragas, "evaluate", None)
    if not callable(evaluate):
        return {"status": "unavailable", "result": None}

    try:
        result = evaluate(dataset)
    except Exception as exc:  # noqa: BLE001 - optional third-party boundary
        return {
            "status": "error",
            "result": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {"status": "ok", "result": result}
