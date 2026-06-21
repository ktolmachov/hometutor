"""Course Workspace progress and metrics helpers."""

from __future__ import annotations

import json
from typing import Any

from app.warmup_planner import recommended_runway_micro_target

COURSE_WORKSPACE_LABEL = "course_workspace"

COURSE_WORKSPACE_SLO_THRESHOLDS_MS: dict[str, float] = {
    "activate_course": 1000.0,
    "first_scoped_answer": 5000.0,
    "course_synthesis_first_result": 10000.0,
    "learning_plan_scoped": 30000.0,
    "flashcards_batch": 60000.0,
    "flashcard_gap_to_tutor": 1000.0,
    "course_prepare_cache_hit": 3000.0,
}


def course_tag(scope: dict[str, Any] | None) -> str | None:
    """Return the normalized flashcard tag for a StudyScope course."""
    if not isinstance(scope, dict):
        return None
    course_id = str(scope.get("id") or "").strip().casefold()
    return f"course:{course_id}" if course_id else None


def folder_tag(scope: dict[str, Any] | None) -> str | None:
    """Return the normalized folder tag for a StudyScope course."""
    if not isinstance(scope, dict):
        return None
    folder_rel = str(scope.get("folder_rel") or "").strip().casefold()
    return f"folder:{folder_rel}" if folder_rel else None


def _course_due_tags(scope: dict[str, Any]) -> str | None:
    tags = [tag for tag in (course_tag(scope), folder_tag(scope)) if tag]
    return ", ".join(tags) if tags else None


def _parse_deck_source_id(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _deck_matches_scope(deck: dict[str, Any], scope: dict[str, Any]) -> bool:
    if str(deck.get("source_type") or "").strip().lower() != "course":
        return False
    source = _parse_deck_source_id(deck.get("source_id"))
    course_id = str(scope.get("id") or "").strip()
    folder_rel = str(scope.get("folder_rel") or "").strip()
    return bool(
        (course_id and str(source.get("course_id") or "").strip() == course_id)
        or (folder_rel and str(source.get("folder_rel") or "").strip() == folder_rel)
    )


def course_slo_status(latency_ms: float | None, scenario: str) -> str:
    """Classify one Course Workspace latency sample against the package-F SLO table."""
    threshold = COURSE_WORKSPACE_SLO_THRESHOLDS_MS.get(str(scenario or "").strip())
    if threshold is None or latency_ms is None:
        return "not_configured"
    return "pass" if float(latency_ms) <= threshold else "fail"


def collect_course_progress(
    scope: dict[str, Any] | None,
    *,
    last_topic: str | None = None,
    due_preview_limit: int = 3,
) -> dict[str, Any]:
    """Build active-course progress summary from persisted flashcard state."""
    if not isinstance(scope, dict) or not scope.get("active"):
        return {
            "active": False,
            "documents": 0,
            "cards_total": 0,
            "cards_mastered": 0,
            "due_today": 0,
            "last_topic": last_topic or "",
            "gaps": [],
            "decks": [],
            "metrics_label": COURSE_WORKSPACE_LABEL,
        }

    from app.user_state import (
        count_due_flashcards,
        get_due_flashcards,
        get_flashcard_deck_progress,
        list_flashcard_decks,
    )

    course_decks = [deck for deck in list_flashcard_decks() if _deck_matches_scope(deck, scope)]
    cards_total = sum(int(deck.get("card_count") or 0) for deck in course_decks)
    cards_mastered = 0
    for deck in course_decks:
        progress = get_flashcard_deck_progress(int(deck["id"]))
        cards_mastered += int(progress.get("mastered") or 0)

    due_tags = _course_due_tags(scope)
    due_today = (
        count_due_flashcards(tags=due_tags)
        if due_tags
        else sum(int(deck.get("due_count") or 0) for deck in course_decks)
    )
    due_cards = get_due_flashcards(limit=due_preview_limit, tags=due_tags) if due_tags else []
    gaps = [
        str(card.get("front") or card.get("deck_name") or "").strip()
        for card in due_cards
        if str(card.get("front") or card.get("deck_name") or "").strip()
    ][:due_preview_limit]

    source_paths = scope.get("source_paths") if isinstance(scope.get("source_paths"), list) else []
    return {
        "active": True,
        "course_id": str(scope.get("id") or ""),
        "course_title": str(scope.get("title") or scope.get("folder_rel") or "Активный курс"),
        "folder_rel": str(scope.get("folder_rel") or ""),
        "documents": len(source_paths),
        "cards_total": cards_total,
        "cards_mastered": cards_mastered,
        "due_today": int(due_today or 0),
        "last_topic": (last_topic or "").strip(),
        "gaps": gaps,
        "decks": course_decks,
        "metrics_label": COURSE_WORKSPACE_LABEL,
        "slo_thresholds_ms": COURSE_WORKSPACE_SLO_THRESHOLDS_MS,
    }


def record_course_workflow_event(
    action: str,
    scope: dict[str, Any] | None,
    *,
    scenario: str | None = None,
    latency_ms: float | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Persist a Course Workspace workflow event with the required metrics label."""
    from app.metrics import record_knowledge_workflow_event

    trace: dict[str, Any] = {
        "workflow_label": COURSE_WORKSPACE_LABEL,
        "course_workspace": True,
    }
    if isinstance(scope, dict):
        trace.update(
            {
                "course_id": scope.get("id"),
                "course_title": scope.get("title"),
                "folder_rel": scope.get("folder_rel"),
                "documents_used_count": len(scope.get("source_paths") or []),
            }
        )
    if scenario:
        trace["scenario"] = scenario
    if latency_ms is not None:
        trace["latency_ms"] = round(float(latency_ms), 3)
        trace["slo_status"] = course_slo_status(latency_ms, scenario or "")

    event_payload = {"metrics_label": COURSE_WORKSPACE_LABEL}
    if payload:
        event_payload.update(payload)
    record_knowledge_workflow_event(
        action=f"{COURSE_WORKSPACE_LABEL}.{(action or 'unknown').strip() or 'unknown'}",
        knowledge_product_trace=trace,
        payload=event_payload,
    )


def course_daily_runway_summary(
    scope: dict[str, Any] | None,
    *,
    micro_cap: int = 5,
    recovery_catch_up_today: int | None = None,
) -> dict[str, Any]:
    """Дневная микро-цель (runway) + глобальный streak для Course Cockpit (ideation e30).

    Milestone: видимая цель в контексте курса; streak — ежедневная активность в приложении
    (KV ``gamification_state_v1``), не отдельный per-course трек.

    recovery_catch_up_today — сколько шагов due ученик готов добрать сегодня (не скрывает total due).
    """
    from app.gamification_service import get_streak

    prog = collect_course_progress(scope)
    if not bool(prog.get("active")):
        return {
            "active": False,
            "due_today": 0,
            "micro_target": 0,
            "recommended_micro_target": 0,
            "recovery_budget_user_set": False,
            "streak_days": 0,
            "goal_line": "",
            "streak_caption": "",
            "recovery_backlog_caption": "",
        }

    due = int(prog.get("due_today") or 0)
    streak = int(get_streak() or 0)
    recommended_micro = recommended_runway_micro_target(due, micro_cap)

    if due <= 0:
        return {
            "active": True,
            "due_today": 0,
            "recommended_micro_target": 0,
            "recovery_budget_user_set": False,
            "micro_target": 0,
            "streak_days": streak,
            "goal_line": (
                "Сегодня: очередь due пуста — можно закрепить привычку 1 лёгким шагом"
            ),
            "streak_caption": f"Стрик: **{streak}** дн.",
            "recovery_backlog_caption": "",
        }

    if recovery_catch_up_today is None:
        micro = recommended_micro
        user_set = False
        goal_line = f"Сегодня: **{micro}** из {due} в очереди due"
    else:
        micro = max(1, min(int(recovery_catch_up_today), due))
        user_set = True
        goal_line = (
            f"Сегодня: **{micro}** из {due} в очереди due "
            f"(рекомендация системы: **{recommended_micro}**)"
        )

    remainder = due - micro
    backlog_caption = ""
    if remainder > 0:
        backlog_caption = (
            f"В общей очереди due всё ещё **{remainder}** шагов вне этого дневного блока "
            f"(полный счётчик: **{due}**)."
        )

    return {
        "active": True,
        "due_today": due,
        "recommended_micro_target": recommended_micro,
        "recovery_budget_user_set": user_set,
        "micro_target": micro,
        "streak_days": streak,
        "goal_line": goal_line,
        "streak_caption": f"Стрик: **{streak}** дн.",
        "recovery_backlog_caption": backlog_caption,
    }


__all__ = [
    "COURSE_WORKSPACE_LABEL",
    "COURSE_WORKSPACE_SLO_THRESHOLDS_MS",
    "collect_course_progress",
    "course_daily_runway_summary",
    "course_slo_status",
    "course_tag",
    "folder_tag",
    "record_course_workflow_event",
]
