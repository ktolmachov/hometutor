"""E24-B-2-1: подстановка сохранённого learner goal snapshot в POST /ask."""

from __future__ import annotations

from app.api_requests import AskRequest
from app.user_state import get_learner_goal_snapshot


def merge_learner_goal_snapshot_into_ask(request: AskRequest) -> AskRequest:
    """Если в теле запроса нет ``tutor_goal_*``, подставляет значения из SQLite snapshot.

    Приоритет: явные поля ``AskRequest`` выше, чем снимок (поля ``None`` считаются отсутствующими).
    Маппинг из ``goal_context`` (как в GET ``/learner/goal-snapshot``):
    ``subtopic`` → ``tutor_goal_subtopic``, ``target_level`` → ``tutor_goal_target_level``,
    ``desired_outcome`` → ``tutor_goal_desired_outcome``, ``time_budget_min`` → ``tutor_goal_time_budget_min``.
    """
    row = get_learner_goal_snapshot()
    if not row:
        return request
    gc = row.get("goal_context")
    if not isinstance(gc, dict):
        return request

    updates: dict[str, object] = {}
    if request.tutor_goal_subtopic is None:
        sub = gc.get("subtopic")
        if sub:
            updates["tutor_goal_subtopic"] = sub
    if request.tutor_goal_target_level is None:
        tl = gc.get("target_level")
        if tl:
            updates["tutor_goal_target_level"] = tl
    if request.tutor_goal_desired_outcome is None:
        dout = gc.get("desired_outcome")
        if dout:
            updates["tutor_goal_desired_outcome"] = dout
    if request.tutor_goal_time_budget_min is None:
        tbm = gc.get("time_budget_min")
        if tbm is not None:
            updates["tutor_goal_time_budget_min"] = tbm

    if not updates:
        return request
    return request.model_copy(update=updates)
