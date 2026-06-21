"""Warm-up planning for course resume after study pauses.

Intended consumer: course resume cards and course cache hooks from US-17.8.
Keep this module pure; API/UI wiring should happen in the consumer layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any, Final, Mapping

# Confidence dip / retrieval-gate stress (course retention follow-up, epoch-course-confidence-dip-detector)
RECENT_GATE_WINDOW: Final[int] = 5
LOW_CONF_THRESHOLD: Final[float] = 0.45
MISSES_IN_LAST3_TRIGGER: Final[int] = 2
LOW_CONF_STREAK_TRIGGER: Final[int] = 2
REMEDIATION_SUCCESSES_TO_EXIT: Final[int] = 2
CONFIDENT_SCORE_MIN: Final[float] = 0.55


@dataclass(frozen=True)
class WarmupPlan:
    tier: str
    message: str
    review_days: int
    recap_sentences: int = 0
    recall_questions: int = 0
    mini_quiz_facts: int = 0
    refresher_minutes: int = 0
    overdue_spread_sessions: int = 0


def recommended_runway_micro_target(due_today: int, micro_cap: int = 5) -> int:
    """Системная дневная нарезка catch-up для runway (единая точка для кокпита и планировщика)."""
    due = max(0, int(due_today))
    if due <= 0:
        return 0
    return min(int(micro_cap), due)


def classify_pause_tier(days_since_last_session: int) -> str:
    """Map pause length to a stable warm-up tier."""
    days = max(0, int(days_since_last_session))
    if days < 1:
        return "fast_continue"
    if days <= 3:
        return "recap_90s"
    if days <= 7:
        return "mini_quiz"
    return "course_refresher"


def overdue_spread_sessions(
    *,
    overdue_count: int,
    days_since_last_session: int,
    min_sessions: int = 3,
    max_sessions: int = 5,
) -> int:
    """Return how many future sessions should absorb overdue cards."""
    overdue = max(0, int(overdue_count))
    paused_days = max(0, int(days_since_last_session))
    if overdue <= 20 or paused_days <= 2:
        return 0
    # Scale sessions by backlog, then clamp to 3..5 as per US-17.8.
    scaled = ceil(overdue / 12)
    return max(min_sessions, min(max_sessions, scaled))


def build_warmup_plan(
    *,
    days_since_last_session: int,
    overdue_count: int = 0,
) -> WarmupPlan:
    """Build a warm-up plan aligned with US-17.8 acceptance slices."""
    tier = classify_pause_tier(days_since_last_session)
    spread = overdue_spread_sessions(
        overdue_count=overdue_count,
        days_since_last_session=days_since_last_session,
    )

    if tier == "fast_continue":
        return WarmupPlan(
            tier=tier,
            message="Продолжить с последнего шага в один клик.",
            review_days=max(1, spread),
        )
    if tier == "recap_90s":
        return WarmupPlan(
            tier=tier,
            message="Краткий recap + 3 recall-вопроса перед входом в сессию.",
            review_days=max(1, spread),
            recap_sentences=2,
            recall_questions=3,
        )
    if tier == "mini_quiz":
        return WarmupPlan(
            tier=tier,
            message="Warm-up mini-quiz по ключевым фактам перед основной сессией.",
            review_days=max(1, spread),
            mini_quiz_facts=5,
        )
    return WarmupPlan(
        tier=tier,
        message="Course refresher на 10 минут с возможностью пропуска/сужения.",
        review_days=max(1, spread),
        refresher_minutes=10,
        overdue_spread_sessions=spread,
    )


def confidence_dip_initial_state() -> dict[str, Any]:
    return {
        "passes": [],
        "in_remediation": False,
        "remediation_success_streak": 0,
        "low_conf_sequence": 0,
    }


def confidence_dip_reduce(
    state: Mapping[str, Any] | None,
    *,
    gate_passed: bool,
    confidence_0_1: float | None = None,
) -> dict[str, Any]:
    """
    Чистый reducer: серия провалов retrieval-gate / низкая уверенность → короткий repair-loop;
    уверенные серии успехов не переводят в remediation (false-positive guard).
    """
    base = confidence_dip_initial_state()
    if isinstance(state, Mapping):
        for key in ("in_remediation", "remediation_success_streak", "low_conf_sequence"):
            if key in state:
                base[key] = state[key]
        if "passes" in state:
            base["passes"] = [bool(x) for x in (state.get("passes") or [])]

    passes: list[bool] = [bool(x) for x in (base.get("passes") or [])]
    passes.append(bool(gate_passed))
    passes = passes[-RECENT_GATE_WINDOW:]

    lc = int(base.get("low_conf_sequence") or 0)
    if confidence_0_1 is not None and float(confidence_0_1) < LOW_CONF_THRESHOLD:
        lc += 1
    else:
        lc = 0

    recent3 = passes[-3:]
    misses_last_3 = sum(1 for p in recent3 if not p)
    conf_val = float(confidence_0_1) if confidence_0_1 is not None else None
    confident_run = (
        len(passes) >= 2
        and bool(passes[-1])
        and bool(passes[-2])
        and (conf_val is None or conf_val >= CONFIDENT_SCORE_MIN)
    )

    in_rem = bool(base.get("in_remediation"))
    succ = int(base.get("remediation_success_streak") or 0)

    if confident_run:
        return {
            "passes": passes,
            "in_remediation": False,
            "remediation_success_streak": 0,
            "low_conf_sequence": lc,
        }

    if not in_rem:
        if misses_last_3 >= MISSES_IN_LAST3_TRIGGER or lc >= LOW_CONF_STREAK_TRIGGER:
            in_rem = True
            succ = 0
    else:
        if gate_passed and (conf_val is None or conf_val >= LOW_CONF_THRESHOLD):
            succ += 1
        elif not gate_passed:
            succ = 0
        if succ >= REMEDIATION_SUCCESSES_TO_EXIT:
            in_rem = False
            succ = 0

    return {
        "passes": passes,
        "in_remediation": in_rem,
        "remediation_success_streak": succ,
        "low_conf_sequence": lc,
    }


def remediation_mini_loop_plan(state: Mapping[str, Any] | None) -> WarmupPlan:
    """Короткий bounded repair-loop поверх warm-up-метафоры (без отдельного UI-стека)."""
    s = state if isinstance(state, Mapping) else confidence_dip_initial_state()
    cap = REMEDIATION_SUCCESSES_TO_EXIT
    done = min(cap, int(s.get("remediation_success_streak") or 0))
    remain = max(0, cap - done)
    msg = (
        "Ремедиация: 1–2 удачные микро-проверки подряд, затем возврат к дневному runway. "
        f"Осталось шагов до выхода (успешных gate): **{remain}**."
    )
    return WarmupPlan(
        tier="confidence_repair",
        message=msg,
        review_days=1,
        recap_sentences=1,
        recall_questions=2,
        mini_quiz_facts=3,
        refresher_minutes=0,
        overdue_spread_sessions=0,
    )


def confidence_dip_public_status(state: Mapping[str, Any] | None) -> dict[str, Any]:
    """Компактный снимок для UI/планов."""
    s = dict(confidence_dip_initial_state())
    if isinstance(state, Mapping):
        s.update(
            {
                "passes": [bool(x) for x in (state.get("passes") or [])],
                "in_remediation": bool(state.get("in_remediation")),
                "remediation_success_streak": int(state.get("remediation_success_streak") or 0),
                "low_conf_sequence": int(state.get("low_conf_sequence") or 0),
            }
        )
    if s["in_remediation"]:
        s["remediation_plan"] = remediation_mini_loop_plan(s).message
    else:
        s["remediation_plan"] = ""
    return s
