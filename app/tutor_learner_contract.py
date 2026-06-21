"""
Typed learner / orchestration snapshot для API (итерация 19.4).
Хранение: KV ``tutor_orchestration_state_v1`` в ``user_state.db``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.user_state import get_kv, set_kv

logger = logging.getLogger(__name__)

KV_KEY = "tutor_orchestration_state_v1"

HOMEWORK_LADDER_STEPS = ("hint", "plan", "error_review", "full_solution")


class TutorOrchestrationStateV1(BaseModel):
    """Стабильный контракт для UI/API (не путать с debug-only полями)."""

    model_config = {"extra": "ignore"}

    contract_version: int = 1
    current_concept: str = Field(default="general")
    mastery_estimate: str = Field(default="intermediate")
    last_error_type: str | None = None
    needs_review: bool = False
    prerequisite_gap: str | None = None
    recommended_action: str | None = None
    orchestration_phase: str | None = None
    orchestration_decision_source: str | None = None
    selected_agent: str | None = None
    should_trigger_microquiz: bool | None = None
    policy_clamped: bool | None = None
    policy_clamp_reasons: list[str] = Field(default_factory=list)


def next_homework_level(current: str | None, *, advance: bool) -> str:
    """
    Session-aware homework ladder: hint → plan → error_review → full_solution.
    ``advance=True`` — после успешного шага; ``False`` — откат к более мягкому уровню.
    """
    steps = list(HOMEWORK_LADDER_STEPS)
    cur = (current or "hint").strip().lower()
    if cur not in steps:
        cur = "hint"
    idx = steps.index(cur)
    if advance:
        idx = min(len(steps) - 1, idx + 1)
    else:
        idx = max(0, idx - 1)
    return steps[idx]


def build_orchestration_state_dict(
    *,
    tutor_decision: dict[str, Any] | None,
    session_metadata: dict[str, Any] | None,
    tutor_orchestration_pipeline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Собрать typed state из уже вычисленного tutor_decision и metadata.

    Опционально вкладывает снимок ``tutor_orchestration_pipeline`` (E6) для KV/UI read path.
    """
    td = tutor_decision if isinstance(tutor_decision, dict) else {}
    md = session_metadata if isinstance(session_metadata, dict) else {}
    pipe = (
        dict(tutor_orchestration_pipeline)
        if isinstance(tutor_orchestration_pipeline, dict)
        else {}
    )
    action = td.get("action")
    rec_label = ""
    if isinstance(action, dict):
        rec_label = str(action.get("next_action") or action.get("label") or "").strip()
    gap = None
    weak = td.get("weak_concepts") if isinstance(td.get("weak_concepts"), list) else []
    if weak:
        gap = str(weak[0]).strip() or None
    phase = str(
        pipe.get("phase")
        or md.get("orchestration_phase")
        or ""
    ).strip() or None
    decision_source = str(
        pipe.get("decision_source")
        or md.get("orchestration_decision_source")
        or ""
    ).strip() or None
    selected_agent = str(
        pipe.get("selected_agent")
        or md.get("selected_agent")
        or ""
    ).strip() or None
    if "should_trigger_microquiz" in pipe:
        should_trigger_microquiz = bool(pipe.get("should_trigger_microquiz"))
    elif "should_trigger_microquiz" in md:
        should_trigger_microquiz = bool(md.get("should_trigger_microquiz"))
    else:
        should_trigger_microquiz = None
    if "policy_clamped" in pipe:
        policy_clamped = bool(pipe.get("policy_clamped"))
    elif "policy_clamped" in md:
        policy_clamped = bool(md.get("policy_clamped"))
    else:
        policy_clamped = None
    raw_reasons = (
        pipe.get("policy_clamp_reasons")
        if isinstance(pipe.get("policy_clamp_reasons"), list)
        else md.get("policy_clamp_reasons")
    )
    policy_clamp_reasons = []
    if isinstance(raw_reasons, list):
        policy_clamp_reasons = [str(x).strip() for x in raw_reasons if str(x).strip()]

    st = TutorOrchestrationStateV1(
        current_concept=str(td.get("focus_topic") or md.get("current_topic") or "general").strip()
        or "general",
        mastery_estimate=str(md.get("mastery_level") or "intermediate").strip() or "intermediate",
        last_error_type=str(md.get("last_quiz_error_type") or "").strip() or None,
        needs_review=int(td.get("due_review_count") or 0) > 0,
        prerequisite_gap=gap,
        recommended_action=rec_label or None,
        orchestration_phase=phase,
        orchestration_decision_source=decision_source,
        selected_agent=selected_agent,
        should_trigger_microquiz=should_trigger_microquiz,
        policy_clamped=policy_clamped,
        policy_clamp_reasons=policy_clamp_reasons,
    )
    out = st.model_dump()
    if pipe:
        out["tutor_orchestration_pipeline"] = pipe
    return out


def persist_orchestration_state(state_dict: dict[str, Any]) -> None:
    try:
        set_kv(KV_KEY, json.dumps(state_dict, ensure_ascii=False))
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.debug("persist_orchestration_state failed", exc_info=True)


def load_orchestration_state() -> dict[str, Any] | None:
    raw = get_kv(KV_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


__all__ = [
    "HOMEWORK_LADDER_STEPS",
    "KV_KEY",
    "TutorOrchestrationStateV1",
    "build_orchestration_state_dict",
    "load_orchestration_state",
    "next_homework_level",
    "persist_orchestration_state",
]
