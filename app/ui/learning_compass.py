"""B2 learning compass: a single compact status line above the route shell.

Format: цель · фаза · бюджет · возврат
Example: «Понять agent-harness · объяснение · 9 мин осталось · затем короткая проверка»

Used on every learning surface (home, tutor, quiz, flashcards, plan) above the
route shell / checkpoint card. One line, no raw agent/mode ids, honest reduction
when data is missing — no synthetic defaults. Max one progress indicator.
"""

from __future__ import annotations

from app.smart_study_router import SmartStudyRecommendation

_SSR_PHASE_LABEL_RU: dict[str, str] = {
    "understand": "объяснение",
    "practice": "практика",
    "check": "проверка",
    "retain": "повторение",
    "plan": "план",
}

_SSR_HINT_GOAL_RU: dict[str, str] = {
    "cards_due": "Повторить карточки",
    "sm2_due": "Повторить по расписанию",
    "quiz_failed": "Разобрать ошибку",
    "tutor_resume": "Продолжить чат",
    "answer_ready": "Проверить ответ",
    "mastery_stale": "Освоить концепт",
    "adaptive_plan": "По плану",
    "safe_default": "Начать занятие",
}


def _phase_label_ru(phase: str) -> str:
    return _SSR_PHASE_LABEL_RU.get(str(phase or "").strip(), "")


def build_learning_compass_html(
    rec: SmartStudyRecommendation,
    *,
    goal_text: str | None = None,
    time_budget_min: int | None = None,
    return_point: str | None = None,
) -> str | None:
    """Build compact HTML for the learning compass line.

    Returns None when there is nothing meaningful to show (honest reduction).
    """
    parts: list[str] = []

    # ── цель ──
    goal = (goal_text or "").strip()
    if not goal:
        goal = _SSR_HINT_GOAL_RU.get(str(rec.hint_kind), "")
    if not goal and rec.topic_hint:
        t = str(rec.topic_hint).strip()
        goal = t if len(t) <= 50 else f"{t[:47]}…"
    if not goal and rec.primary_label_ru:
        goal = str(rec.primary_label_ru).strip()
        if len(goal) > 50:
            goal = goal[:47] + "…"
    if goal:
        parts.append(goal)

    # ── фаза ──
    phase = _phase_label_ru(rec.phase)
    if phase:
        parts.append(phase)

    # ── бюджет ──
    if time_budget_min is not None:
        try:
            t = int(time_budget_min)
            if t > 0:
                parts.append(f"{t} мин осталось")
        except (TypeError, ValueError):
            pass

    # ── возврат ──
    rp = (return_point or "").strip()
    if rp:
        parts.append(f"затем {rp}")

    if not parts:
        return None

    line = " · ".join(parts)
    return (
        f'<div class="learning-compass" data-testid="e2e-learning-compass" '
        f'style="font-size:0.82rem;opacity:0.88;margin-bottom:0.35rem;'
        f'padding:0.2rem 0;border-bottom:1px solid var(--border-subtle, #e0e0e0);">'
        f"<strong>{line}</strong></div>"
    )


def render_learning_compass(
    rec: SmartStudyRecommendation,
    *,
    goal_text: str | None = None,
    time_budget_min: int | None = None,
    return_point: str | None = None,
) -> None:
    """Render the compact learning compass HTML above the route shell.

    When data is insufficient, renders nothing (honest reduction).
    """
    html = build_learning_compass_html(
        rec,
        goal_text=goal_text,
        time_budget_min=time_budget_min,
        return_point=return_point,
    )
    if html:
        import streamlit as st
        st.html(html)
