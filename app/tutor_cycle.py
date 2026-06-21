"""
Tutor retention cycle (итерация 19.3): единый контракт состояния цикла
«ответ → micro-quiz → diagnostic → next step» и нормализованный diagnostic feedback.
"""

from __future__ import annotations

from typing import Any, Literal

DiagnosticFeedbackStatus = Literal["recognized", "recalled", "misconception", "cannot_apply"]


def map_quiz_outcome_to_diagnostic(
    *,
    is_correct: bool,
    question_type: str,
) -> DiagnosticFeedbackStatus:
    """
    Нормализованный статус после micro-quiz (соответствует § итерация 19.3 tasklist).

    - Верно + recognition → recognized
    - Верно + recall → recalled
    - Верно + application/transfer → recalled (успешный перенос)
    - Неверно + recognition/recall → misconception
    - Неверно + application → cannot_apply
    """
    qt = (question_type or "application").strip().lower()
    if qt == "transfer":
        qt = "application"

    if is_correct:
        if qt == "recognition":
            return "recognized"
        if qt == "recall":
            return "recalled"
        return "recalled"

    if qt == "application":
        return "cannot_apply"
    return "misconception"


def compute_default_next_step(
    *,
    due_reviews_count: int,
    auto_quiz_attached: bool,
) -> str:
    """Приоритет: сначала due review при наличии, иначе micro-quiz, иначе продолжение диалога."""
    if due_reviews_count > 0:
        return "due_review_first"
    if auto_quiz_attached:
        return "micro_quiz_first"
    return "continue_tutor"


def build_tutor_cycle_state(
    *,
    session_id: str | None,
    due_reviews_count: int,
    auto_quiz_payload: dict[str, Any] | None,
    tutor_answer_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Состояние цикла для TutorPayload.tutor_cycle и session metadata.

    Поля стабильны для UI/API; не дублировать сырой debug.
    """
    sid = (session_id or "").strip() or None
    auto_attached = False
    if isinstance(auto_quiz_payload, dict):
        qwrap = auto_quiz_payload.get("quiz")
        if isinstance(qwrap, dict) and qwrap.get("questions"):
            auto_attached = True
        elif auto_quiz_payload.get("show_immediately"):
            auto_attached = True
    ta = tutor_answer_contract if isinstance(tutor_answer_contract, dict) else {}
    next_action = str(ta.get("next_action") or "").strip() or None
    next_reason = str(ta.get("next_action_reason") or "").strip() or None

    default_next = compute_default_next_step(
        due_reviews_count=due_reviews_count,
        auto_quiz_attached=auto_attached,
    )

    phase = "after_tutor_answer"
    if auto_attached:
        phase = "micro_quiz_offered"
    elif due_reviews_count > 0 and default_next == "due_review_first":
        phase = "due_review_pending"

    quiz_state: dict[str, Any] = {
        "auto_loop_enabled": auto_attached,
        "expects_micro_quiz": auto_attached,
    }
    review_state: dict[str, Any] = {
        "due_reviews_count": int(due_reviews_count),
        "due_review_priority": due_reviews_count > 0,
    }

    return {
        "contract_version": 1,
        "session_id": sid,
        "phase": phase,
        "quiz_state": quiz_state,
        "review_state": review_state,
        "recommended_next_action": next_action,
        "next_action_reason": next_reason,
        "default_next_step": default_next,
    }


__all__ = [
    "DiagnosticFeedbackStatus",
    "build_tutor_cycle_state",
    "compute_default_next_step",
    "map_quiz_outcome_to_diagnostic",
]
