"""Baseline 7-day SSR weekly planner (rule-based, pre-L3 optimization).

Consumes compact learner profiles (fixtures or API-shaped dicts), distributes
minutes across retention (due SM-2 cards), weak-concept recovery, and
new/continuation work, and emits an auxiliary L3 telemetry event when enabled.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ssr_ai.telemetry import record_ssr_ai_auxiliary_event

logger = logging.getLogger(__name__)

DayPrimaryLabel = Literal[
    "retention_debt",
    "weak_concept_recovery",
    "new_learning_or_continuation",
]
RouterSignal = Literal[
    "retention_debt",
    "weak_concept_recovery",
    "new_learning_or_continuation",
]
SessionKind = Literal["retention", "recovery", "continuation"]


class WeeklyPlannerProfile(BaseModel):
    """Fixture-friendly profile for offline evaluation and tests."""

    model_config = ConfigDict(extra="ignore")

    profile_id: str
    due_flashcard_count: int = Field(0, ge=0)
    overdue_days_max: float = Field(0.0, ge=0.0)
    quiz_failure_active: bool = False
    weak_concepts: list[str] = Field(default_factory=list)
    mastery_avg: float = Field(0.7, ge=0.0, le=1.0)
    continuation_queue_min: int = Field(0, ge=0)
    minutes_per_retention_card: float = Field(2.5, gt=0)
    minutes_per_weak_concept: float = Field(12.0, gt=0)
    quiz_failure_recovery_min: int = Field(20, ge=0)
    minutes_available_per_day: list[int] = Field(default_factory=lambda: [45] * 7)

    @field_validator("minutes_available_per_day")
    @classmethod
    def _seven_days(cls, v: list[int]) -> list[int]:
        if len(v) != 7:
            msg = "minutes_available_per_day must have length 7"
            raise ValueError(msg)
        for m in v:
            if m < 0:
                msg = "daily minutes must be non-negative"
                raise ValueError(msg)
        return v


def _compute_pool_minutes(profile: WeeklyPlannerProfile) -> dict[str, float]:
    retention = float(profile.due_flashcard_count) * float(profile.minutes_per_retention_card)
    recovery = float(len(profile.weak_concepts)) * float(profile.minutes_per_weak_concept)
    if profile.quiz_failure_active:
        recovery += float(profile.quiz_failure_recovery_min)
    # Continuation / new learning demand scales with gap to mastery and explicit queue.
    gap = max(0.0, 1.0 - float(profile.mastery_avg))
    continuation = float(profile.continuation_queue_min) + gap * 120.0
    return {"retention": retention, "recovery": recovery, "continuation": continuation}


def _router_signal_from_pools(pools: dict[str, float]) -> RouterSignal:
    r, v, c = pools["retention"], pools["recovery"], pools["continuation"]
    best = max(r, v, c)
    if best <= 0:
        return "new_learning_or_continuation"
    # Tie-break: retention > recovery > continuation (per backlog / US-20.9 intent).
    if r >= best and r > 0:
        return "retention_debt"
    if v >= best and v > 0:
        return "weak_concept_recovery"
    return "new_learning_or_continuation"


def _day_primary_from_sessions(sessions: list[dict[str, Any]]) -> DayPrimaryLabel:
    totals: dict[str, int] = {"retention": 0, "recovery": 0, "continuation": 0}
    for s in sessions:
        kind = str(s.get("kind") or "")
        minutes = int(s.get("minutes") or 0)
        if kind in totals:
            totals[kind] += minutes
    best = max(totals.values())
    if best <= 0:
        return "new_learning_or_continuation"
    if totals["retention"] >= best:
        return "retention_debt"
    if totals["recovery"] >= best:
        return "weak_concept_recovery"
    return "new_learning_or_continuation"


def generate_weekly_study_plan(
    profile: WeeklyPlannerProfile | dict[str, Any],
    *,
    emit_telemetry: bool = True,
) -> dict[str, Any]:
    """Build a 7-day plan dict; optional L3 auxiliary telemetry (best-effort)."""
    if isinstance(profile, dict):
        model = WeeklyPlannerProfile.model_validate(profile)
    else:
        model = profile

    pools = _compute_pool_minutes(model)
    router_signal = _router_signal_from_pools(pools)
    remaining = {k: float(v) for k, v in pools.items()}
    total_budget = float(sum(model.minutes_available_per_day))
    total_demand = sum(remaining.values())
    completion_ratio = min(1.0, total_budget / total_demand) if total_demand > 0 else 1.0

    order: list[SessionKind] = ["retention", "recovery", "continuation"]
    days_out: list[dict[str, Any]] = []

    for day_index in range(7):
        budget = int(model.minutes_available_per_day[day_index])
        sessions: list[dict[str, Any]] = []
        b_left = budget
        for kind in order:
            if b_left <= 0:
                break
            key = kind
            take_f = min(remaining[key], float(b_left))
            take = int(take_f)
            if take > 0:
                note_parts: list[str] = []
                concepts: list[str] = []
                if kind == "retention" and model.due_flashcard_count > 0:
                    note_parts.append(
                        f"due_cards≈{model.due_flashcard_count}, overdue_max_d={model.overdue_days_max:.1f}"
                    )
                if kind == "recovery" and model.weak_concepts:
                    concepts = list(model.weak_concepts)[:6]
                    note_parts.append("weak_concept_recovery")
                    if model.quiz_failure_active:
                        note_parts.append("quiz_failure_active")
                if kind == "continuation":
                    note_parts.append(f"mastery_avg={model.mastery_avg:.2f}")
                sess: dict[str, Any] = {"kind": kind, "minutes": take}
                if note_parts:
                    sess["notes"] = "; ".join(note_parts)
                if concepts:
                    sess["concepts"] = concepts
                sessions.append(sess)
                remaining[key] -= float(take)
                b_left -= take
        primary = _day_primary_from_sessions(sessions)
        days_out.append(
            {
                "day_index": day_index,
                "budget_minutes": budget,
                "sessions": sessions,
                "primary_label": primary,
            }
        )

    summary = {
        "pools_requested_minutes": {k: round(v, 3) for k, v in pools.items()},
        "pools_unmet_minutes": {k: round(max(0.0, remaining[k]), 3) for k in remaining},
        "total_budget_minutes": int(total_budget),
        "completion_feasibility_ratio": round(completion_ratio, 4),
        "router_signal": router_signal,
    }

    payload: dict[str, Any] = {
        "profile_id": model.profile_id,
        "days": days_out,
        "summary": summary,
    }

    if emit_telemetry:
        try:
            record_ssr_ai_auxiliary_event(
                level="L3",
                category="weekly_plan_baseline_completed",
                detail={
                    "profile_id": model.profile_id,
                    "router_signal": router_signal,
                    "completion_feasibility_ratio": summary["completion_feasibility_ratio"],
                    "due_flashcard_count": model.due_flashcard_count,
                    "quiz_failure_active": model.quiz_failure_active,
                    "weak_concepts_n": len(model.weak_concepts),
                },
            )
        except Exception as exc:  # noqa: BLE001 - telemetry must never break planning
            logger.warning(
                "ssr_weekly_planner telemetry skipped: %s",
                exc,
                exc_info=True,
            )

    return payload


def load_weekly_planner_fixtures(
    path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Load canonical fixture list (tracked default under archive/ml_eval/ssr_level3/)."""
    base = Path(__file__).resolve().parents[1]
    canonical = base / "archive" / "ml_eval" / "ssr_level3" / "ssr_weekly_plan_fixtures.json"
    legacy = base / "data" / "ml" / "ssr_weekly_plan_fixtures.json"
    if path is None:
        p = canonical if canonical.is_file() else legacy
    else:
        p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "fixtures root must be an object"
        raise ValueError(msg)
    profiles = raw.get("profiles")
    if not isinstance(profiles, list):
        msg = "fixtures.profiles must be a list"
        raise ValueError(msg)
    return [x for x in profiles if isinstance(x, dict)]


__all__ = [
    "WeeklyPlannerProfile",
    "generate_weekly_study_plan",
    "load_weekly_planner_fixtures",
]
