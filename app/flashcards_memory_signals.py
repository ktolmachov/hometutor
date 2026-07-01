"""Local memory-strength analytics for the flashcard review card face.

Pure function, no LLM/DB/network calls: :func:`compute_card_memory_signals`
turns the SR fields already present on a due card (``easiness`` /
``interval_days`` / ``repetitions`` / ``next_review``) into a few
learner-facing signals (a 0–100 "strength" estimate, a maturity bucket, an
overdue/forecast line, an ease label). It's an instant, free heuristic — not a
model call — so it can run on every card render.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from app.spaced_repetition import _parse_dt_iso, _utc_now

_DEFAULT_EASINESS = 2.5
_EASE_MIN = 1.3
_EASE_MAX = 3.0

# Weights for the strength heuristic — interval (proven retention over time)
# dominates, repetitions and ease are secondary signals. Sums to 1.0.
_W_INTERVAL = 0.55
_W_REPETITIONS = 0.25
_W_EASE = 0.20

_STATUS_META: dict[str, tuple[str, str]] = {
    "new": ("Новая", "#7f8c8d"),
    "learning": ("Изучение", "#c0392b"),
    "young": ("Молодая", "#d68910"),
    "maturing": ("Закрепляется", "#1e8449"),
    "mature": ("Устойчивая", "#1a5276"),
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _coerce_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _coerce_ease(card: dict[str, Any]) -> float:
    # Offline/e2e cards carry `ease_factor`, not `easiness` — same alias
    # fallback as `filter_due_cards_expert` (app/flashcard_service.py:718).
    raw = card.get("easiness")
    if raw is None:
        raw = card.get("ease_factor")
    try:
        return float(raw) if raw is not None else _DEFAULT_EASINESS
    except (TypeError, ValueError):
        return _DEFAULT_EASINESS


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return _utc_now()
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _classify_status(*, repetitions: int, interval_days: int) -> str:
    if repetitions <= 0:
        return "new"
    if interval_days <= 1:
        return "learning"
    if interval_days <= 7:
        return "young"
    if interval_days <= 30:
        return "maturing"
    return "mature"


def _compute_strength_pct(*, interval_days: int, easiness: float, repetitions: int) -> int:
    interval_score = _clamp01(math.log1p(interval_days) / math.log1p(365))
    repetitions_score = _clamp01(repetitions / 10.0)
    ease_score = _clamp01((easiness - _EASE_MIN) / (_EASE_MAX - _EASE_MIN))
    raw = _W_INTERVAL * interval_score + _W_REPETITIONS * repetitions_score + _W_EASE * ease_score
    return max(0, min(100, round(raw * 100)))


def _ease_label_ru(easiness: float) -> str:
    if easiness < 1.8:
        return "трудная"
    if easiness < 2.6:
        return "средняя"
    return "лёгкая"


def _plural_days_ru(n: int) -> str:
    # Informal abbreviation ("дн.") — same for every quantity, no gender/case
    # agreement pitfalls, matches the plan's example strings verbatim.
    return "дн."


def _build_forecast_ru(*, status: str, overdue_days: int, days_until: int | None, interval_days: int) -> str:
    if overdue_days > 0:
        return f"просрочена на {overdue_days} {_plural_days_ru(overdue_days)}"
    if days_until is not None:
        if days_until <= 0:
            return "к повтору сегодня"
        return f"≈{days_until} {_plural_days_ru(days_until)} до повтора"
    if status == "new":
        return "готова к первому повторению"
    return f"≈{interval_days} {_plural_days_ru(interval_days)} до повтора"


def compute_card_memory_signals(card: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Local, LLM-free memory analytics for one due card.

    Returns a dict with ``strength_pct`` (0–100), ``status`` /
    ``status_label_ru`` / ``status_color``, ``overdue_days``,
    ``forecast_ru`` and ``ease_label_ru`` — plus the coerced raw
    ``easiness`` / ``interval_days`` / ``repetitions`` for callers that want
    to render a details panel without re-reading the card.
    """
    now_dt = _normalize_now(now)
    easiness = _coerce_ease(card)
    interval_days = _coerce_int(card.get("interval_days"))
    repetitions = _coerce_int(card.get("repetitions"))

    overdue_days = 0
    days_until: int | None = None
    next_review_dt = _parse_dt_iso(card.get("next_review"))
    if next_review_dt is not None:
        delta_days = (now_dt - next_review_dt).total_seconds() / 86400.0
        if delta_days > 0:
            overdue_days = int(math.floor(delta_days))
        else:
            days_until = int(math.ceil(-delta_days))

    status = _classify_status(repetitions=repetitions, interval_days=interval_days)
    status_label_ru, status_color = _STATUS_META[status]
    strength_pct = _compute_strength_pct(
        interval_days=interval_days, easiness=easiness, repetitions=repetitions
    )
    forecast_ru = _build_forecast_ru(
        status=status, overdue_days=overdue_days, days_until=days_until, interval_days=interval_days
    )

    return {
        "strength_pct": strength_pct,
        "status": status,
        "status_label_ru": status_label_ru,
        "status_color": status_color,
        "overdue_days": overdue_days,
        "forecast_ru": forecast_ru,
        "ease_label_ru": _ease_label_ru(easiness),
        "easiness": easiness,
        "interval_days": interval_days,
        "repetitions": repetitions,
    }
