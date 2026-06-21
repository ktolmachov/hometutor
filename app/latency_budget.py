"""Surface latency budgets, degradation ladder, and Package E JSONL trace."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from app.config import LOG_DIR
from app.course_cache import course_scope_hash, first_session_artifact_is_populated
from app.logging_config import log_event

logger = logging.getLogger(__name__)

T = TypeVar("T")

LATENCY_BUDGET_JSONL = LOG_DIR / "latency_budget.jsonl"

SURFACE_BUDGETS: dict[str, dict[str, dict[str, int]]] = {
    "mission_load": {
        "cold": {"target_ms": 800, "soft_ms": 1500, "hard_ms": 3000},
        "warm": {"target_ms": 200, "soft_ms": 600, "hard_ms": 1500},
    },
    "query": {
        "cold": {"target_ms": 2500, "soft_ms": 4000, "hard_ms": 8000},
    },
    "tutor_turn": {
        "cold": {"target_ms": 1500, "soft_ms": 3000, "hard_ms": 6000},
    },
    "quiz_gen": {
        "cold": {"target_ms": 2000, "soft_ms": 3000, "hard_ms": 6000},
    },
    "quiz_submit": {
        "cold": {"target_ms": 2000, "soft_ms": 3000, "hard_ms": 6000},
    },
}


@dataclass(frozen=True)
class BudgetThresholds:
    target_ms: int
    soft_ms: int
    hard_ms: int


@dataclass(frozen=True)
class BudgetMeta:
    surface: str
    variant: str | None
    target_ms: int
    soft_ms: int
    hard_ms: int
    actual_ms: float
    degraded: bool
    degrade_reason: str
    event: str
    ladder_step: int


@dataclass(frozen=True)
class BudgetResult:
    result: Any
    meta: BudgetMeta


def classify_mission_load_variant(
    scope: dict[str, Any] | None,
    session_state: dict[str, Any],
) -> str:
    """Warm when session cache is valid before disk read; otherwise cold."""
    if not isinstance(scope, dict):
        return "cold"
    folder = str(scope.get("folder_rel") or "").strip()
    if not folder:
        return "cold"
    paths = scope.get("source_paths") if isinstance(scope.get("source_paths"), list) else []
    current_hash = course_scope_hash(paths) if paths else ""
    cached = session_state.get("first_session_artifact_cache")
    cached_hash = str(session_state.get("first_session_artifact_scope_hash") or "")
    cached_folder = str(session_state.get("first_session_course_id") or "")
    if (
        isinstance(cached, dict)
        and cached_hash == current_hash
        and cached_folder == folder
        and first_session_artifact_is_populated(cached)
    ):
        return "warm"
    return "cold"


def resolve_query_surface(options: Any) -> str:
    """Return tutor_turn when query_mode=tutor; otherwise query (mutex surfaces)."""
    if (getattr(options, "query_mode", None) or "").strip().lower() == "tutor":
        return "tutor_turn"
    return "query"


def maybe_append_budget_tape_event(
    session_id: str | None,
    meta: BudgetMeta,
    *,
    course_id: str | None = None,
) -> None:
    """Append session tape on soft/hard breach when session_id is set."""
    if not session_id:
        return
    if meta.event not in ("surface_breached_soft", "surface_breached_hard"):
        return
    from app.session_tape import append_event

    append_event(
        session_id,
        meta.event,
        budget_meta_to_session_event(meta),
        course_id=course_id,
        surface=meta.surface,
    )


def budget_meta_to_session_event(meta: BudgetMeta) -> dict[str, Any]:
    return {
        "surface": meta.surface,
        "variant": meta.variant,
        "target_ms": meta.target_ms,
        "soft_ms": meta.soft_ms,
        "hard_ms": meta.hard_ms,
        "actual_ms": round(meta.actual_ms, 3),
        "degraded": meta.degraded,
        "degrade_reason": meta.degrade_reason,
        "event": meta.event,
        "ladder_step": meta.ladder_step,
    }


def _thresholds_for(surface: str, variant: str | None) -> BudgetThresholds:
    surface_budgets = SURFACE_BUDGETS.get(surface, {})
    key = variant if variant in surface_budgets else "cold"
    raw = surface_budgets.get(key) or surface_budgets.get("cold") or {
        "target_ms": 0,
        "soft_ms": 0,
        "hard_ms": 0,
    }
    return BudgetThresholds(
        target_ms=int(raw["target_ms"]),
        soft_ms=int(raw["soft_ms"]),
        hard_ms=int(raw["hard_ms"]),
    )


def _evaluate_ladder(actual_ms: float, thresholds: BudgetThresholds) -> tuple[int, bool, str, str]:
    if actual_ms <= thresholds.target_ms:
        return 1, False, "", "budget_completed"
    if actual_ms <= thresholds.soft_ms:
        return 2, True, "approaching_soft", "budget_completed"
    if actual_ms <= thresholds.hard_ms:
        return 3, True, "soft_breach", "surface_breached_soft"
    return 4, True, "hard_breach", "surface_breached_hard"


def _emit_budget_event(meta: BudgetMeta, *, jsonl_path: Path | None = None) -> None:
    path = jsonl_path or LATENCY_BUDGET_JSONL
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **budget_meta_to_session_event(meta),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        logger.warning("latency_budget_jsonl_write_failed: %s", exc)
    debug_fields = {k: v for k, v in budget_meta_to_session_event(meta).items() if k != "event"}
    log_event(logger, logging.DEBUG, meta.event, **debug_fields)


def with_budget(
    surface: str,
    fn: Callable[[], T],
    *,
    variant: str | None = None,
    empty_scope: bool = False,
    clock: Callable[[], float] = time.perf_counter,
    jsonl_path: Path | None = None,
) -> BudgetResult[T]:
    """Measure ``fn``, evaluate degradation ladder, emit trace, return result + metadata."""
    start = clock()
    result = fn()
    actual_ms = max(0.0, (clock() - start) * 1000.0)

    if empty_scope:
        meta = BudgetMeta(
            surface=surface,
            variant=variant,
            target_ms=0,
            soft_ms=0,
            hard_ms=0,
            actual_ms=0.0,
            degraded=False,
            degrade_reason="",
            event="budget_completed",
            ladder_step=1,
        )
        _emit_budget_event(meta, jsonl_path=jsonl_path)
        return BudgetResult(result=result, meta=meta)

    thresholds = _thresholds_for(surface, variant)
    ladder_step, degraded, degrade_reason, event = _evaluate_ladder(actual_ms, thresholds)
    meta = BudgetMeta(
        surface=surface,
        variant=variant,
        target_ms=thresholds.target_ms,
        soft_ms=thresholds.soft_ms,
        hard_ms=thresholds.hard_ms,
        actual_ms=actual_ms,
        degraded=degraded,
        degrade_reason=degrade_reason,
        event=event,
        ladder_step=ladder_step,
    )
    _emit_budget_event(meta, jsonl_path=jsonl_path)

    if event == "surface_breached_hard" and surface == "mission_load":
        if isinstance(result, tuple) and len(result) == 2:
            artifact, status = result
            if status == "ok":
                result = (None, "empty")
            elif status not in ("empty", "error"):
                result = (None, "error")

    return BudgetResult(result=result, meta=meta)
