"""Deterministic weekly study narrative snapshot (no LLM, no SSR policy).

Must not import ``app.smart_study_router``, ``app.smart_study_recommendation``, or ``app.provider``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.quiz_adaptive import get_weak_concepts
from app.user_state_weekly_narrative import (
    aggregate_dominant_ssr_routes_7d,
    compute_due_trend,
    count_learning_events_7d,
)

DueTrendBucket = Literal["up", "down", "flat", "neutral"]
NarrativeState = Literal["empty", "populated"]

_EMPTY_MESSAGE_RU = (
    "Пока мало учебных действий за последние 7 дней — недельный срез появится после "
    "нескольких занятий (квиз, повторение карточек или шаг с подсказкой Smart Study). "
    "Продолжайте обычный цикл: подсказка выше, повторения или тьютор."
)

_TEMPLATE_TEXT: dict[str, str] = {
    "due_trend_up": "За неделю очередь повторений выросла — система чаще предлагала закрыть due.",
    "due_trend_down": "Очередь повторений снизилась относительно начала недели.",
    "due_trend_flat": "Очередь due держалась без резких скачков.",
    "due_trend_neutral": "Тренд due пока не оценить — мало истории.",
    "weak_concepts_named": "Слабые места: {names} — на них чаще уходили подсказки.",
    "weak_concepts_absent": "Явных слабых концептов в срезе не зафиксировано.",
    "route_dominant": "Чаще предлагалось: {hint_label} → {nav_label} — {plain_why}.",
    "route_sparse": "Маршруты Smart Study за неделю разнообразные, без одного доминанта.",
    "week_stable": "Неделя ровная: без резких сдвигов в метриках среза.",
    "empty_insufficient_data": _EMPTY_MESSAGE_RU,
}

_HINT_LABELS: dict[str, str] = {
    "cards_due": "карточки due",
    "sm2_due": "повторения по расписанию",
    "quiz_failed": "разбор ошибок квиза",
    "tutor_resume": "продолжение тьютора",
    "answer_ready": "ответ на вопрос",
    "mastery_stale": "освежение mastery",
    "adaptive_plan": "блок плана",
    "safe_default": "короткая сессия",
}

_NAV_LABELS: dict[str, str] = {
    "flashcards_review": "карточки",
    "sm2_tutor": "тьютор по повторениям",
    "quiz_recovery_tutor": "квиз + тьютор",
    "tutor_resume": "тьютор",
    "qa_continue": "вопрос-ответ",
    "tutor_weak_gap": "закрытие пробелов",
    "plan_block_tutor": "план обучения",
    "safe_tutor_5min": "5 мин тьютора",
}

_PLAIN_WHY: dict[str, str] = {
    "cards_due": "закрыть due по карточкам",
    "sm2_due": "закрыть очередь повторений",
    "quiz_failed": "подтянуть слабые темы после квиза",
    "tutor_resume": "продолжить прерванную сессию",
    "answer_ready": "завершить ответ",
    "mastery_stale": "освежить mastery",
    "adaptive_plan": "идти по плану",
    "safe_default": "короткий безопасный шаг",
}

_MAX_WORDS = 120
_MIN_BULLETS = 3
_MAX_BULLETS = 5
_WEAK_NAMES_MAX_CHARS = 40


@dataclass(frozen=True)
class WeeklyNarrativeSignals:
    event_count: int
    due_trend: DueTrendBucket
    weak_concepts: tuple[str, ...] = ()
    dominant_route: tuple[str, str] | None = None
    route_sparse: bool = False


@dataclass(frozen=True)
class WeeklyStudyNarrativeViewModel:
    state: NarrativeState
    message_ru: str
    bullets: tuple[str, ...]
    template_ids: tuple[str, ...]
    word_count: int
    event_count: int


def _word_count(text: str) -> int:
    return len([w for w in str(text or "").split() if w])


def _bullets_word_count(bullets: tuple[str, ...]) -> int:
    return _word_count(" ".join(bullets))


def _truncate_weak_names(names: tuple[str, ...]) -> str:
    joined = ", ".join(names)
    if len(joined) <= _WEAK_NAMES_MAX_CHARS:
        return joined
    trimmed = joined[: _WEAK_NAMES_MAX_CHARS - 1].rstrip(", ")
    return f"{trimmed}…"


def _due_template_id(trend: DueTrendBucket) -> str:
    return {
        "up": "due_trend_up",
        "down": "due_trend_down",
        "flat": "due_trend_flat",
        "neutral": "due_trend_neutral",
    }[trend]


def _render_dominant_route(hint_kind: str, primary_nav: str) -> tuple[str, str]:
    hint_label = _HINT_LABELS.get(hint_kind, hint_kind)
    nav_label = _NAV_LABELS.get(primary_nav, primary_nav)
    plain_why = _PLAIN_WHY.get(hint_kind, "поддержать текущий ритм")
    text = _TEMPLATE_TEXT["route_dominant"].format(
        hint_label=hint_label,
        nav_label=nav_label,
        plain_why=plain_why,
    )
    return "route_dominant", text


def _select_bullet_candidates(signals: WeeklyNarrativeSignals) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []

    due_tid = _due_template_id(signals.due_trend)
    out.append((due_tid, _TEMPLATE_TEXT[due_tid]))

    if signals.weak_concepts:
        names = _truncate_weak_names(signals.weak_concepts)
        text = _TEMPLATE_TEXT["weak_concepts_named"].format(names=names)
        out.append(("weak_concepts_named", text))
    else:
        out.append(("weak_concepts_absent", _TEMPLATE_TEXT["weak_concepts_absent"]))

    if signals.dominant_route is not None:
        hk, pn = signals.dominant_route
        tid, text = _render_dominant_route(hk, pn)
        out.append((tid, text))
    elif signals.route_sparse or signals.dominant_route is None:
        out.append(("route_sparse", _TEMPLATE_TEXT["route_sparse"]))

    out.append(("week_stable", _TEMPLATE_TEXT["week_stable"]))
    return out


def _enforce_word_limit(
    candidates: list[tuple[str, str]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    selected_ids: list[str] = []
    selected_texts: list[str] = []

    for tid, text in candidates:
        if len(selected_texts) >= _MAX_BULLETS:
            break
        trial = tuple(selected_texts + [text])
        if _bullets_word_count(trial) <= _MAX_WORDS:
            selected_ids.append(tid)
            selected_texts.append(text)
        elif len(selected_texts) >= _MIN_BULLETS - 1:
            break

    while len(selected_texts) < _MIN_BULLETS and len(selected_texts) < len(candidates):
        for tid, text in candidates:
            if tid in selected_ids:
                continue
            trial = tuple(selected_texts + [text])
            if _bullets_word_count(trial) <= _MAX_WORDS:
                selected_ids.append(tid)
                selected_texts.append(text)
                break
        else:
            break

    if selected_texts and _bullets_word_count(tuple(selected_texts)) > _MAX_WORDS:
        last = selected_texts[-1]
        words = last.split()
        while words and _bullets_word_count(tuple(selected_texts[:-1] + [" ".join(words) + "…"])) > _MAX_WORDS:
            words.pop()
        if words:
            selected_texts[-1] = " ".join(words) + "…"

    return tuple(selected_texts), tuple(selected_ids)


def _collect_production_signals(now_utc: datetime | None) -> WeeklyNarrativeSignals:
    event_count = count_learning_events_7d(now_utc=now_utc)
    due_trend = compute_due_trend(now_utc=now_utc)  # type: ignore[assignment]
    weak = tuple(get_weak_concepts(threshold=60, limit=3))
    dominant = aggregate_dominant_ssr_routes_7d(now_utc=now_utc)
    return WeeklyNarrativeSignals(
        event_count=event_count,
        due_trend=due_trend,  # type: ignore[arg-type]
        weak_concepts=weak,
        dominant_route=dominant,
        route_sparse=dominant is None,
    )


def build_weekly_study_narrative_snapshot(
    *,
    now_utc: datetime | None = None,
    inject_signals: WeeklyNarrativeSignals | None = None,
) -> WeeklyStudyNarrativeViewModel:
    signals = inject_signals if inject_signals is not None else _collect_production_signals(now_utc)

    if signals.event_count < 3:
        return WeeklyStudyNarrativeViewModel(
            state="empty",
            message_ru=_EMPTY_MESSAGE_RU,
            bullets=(),
            template_ids=("empty_insufficient_data",),
            word_count=_word_count(_EMPTY_MESSAGE_RU),
            event_count=signals.event_count,
        )

    candidates = _select_bullet_candidates(signals)
    bullets, template_ids = _enforce_word_limit(candidates)
    return WeeklyStudyNarrativeViewModel(
        state="populated",
        message_ru="",
        bullets=bullets,
        template_ids=template_ids,
        word_count=_bullets_word_count(bullets),
        event_count=signals.event_count,
    )


__all__ = [
    "DueTrendBucket",
    "NarrativeState",
    "WeeklyNarrativeSignals",
    "WeeklyStudyNarrativeViewModel",
    "build_weekly_study_narrative_snapshot",
]
