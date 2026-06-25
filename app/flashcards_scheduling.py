"""Flashcard review scheduling — SM-2 ease, Anki-style divergent intervals.

Vanilla SM-2 (:func:`app.spaced_repetition.apply_sm2`) only moves the *ease
factor* on quality 3/4/5 — the next interval is identical for "Трудно", "Хорошо"
and "Легко" (and is ``1`` for every rating on a brand-new card). That makes three
of the four review buttons meaningless on any given card.

This module keeps SM-2's ease/repetition progression but shapes the *immediate*
interval so the four ratings actually diverge, the way learners expect from Anki:

* **again** → relearn tomorrow, repetitions reset;
* **hard**  → a short step (≈ previous × 1.2), strictly below *good*;
* **good**  → the SM-2 interval (previous × ease);
* **easy**  → an "easy bonus" on top of *good*.

Both the live review (:func:`app.flashcard_service.review_flashcard`) and the
on-button interval preview call :func:`compute_flashcard_schedule`, so the number
shown on a button is exactly what pressing it will do.
"""

from __future__ import annotations

from typing import Any

from app.spaced_repetition import apply_sm2

# UI rating label → SM-2 quality. Mirrors RATING_BUTTONS / QUALITY_MAP.
RATING_TO_QUALITY: dict[str, int] = {"again": 0, "hard": 3, "good": 4, "easy": 5}

# Interval shaping factors (Anki defaults, day-granular).
_HARD_FACTOR = 1.2
_EASY_BONUS = 1.3
# Graduating intervals (days) for a brand-new card by rating.
_NEW_CARD_INTERVALS = {"hard": 1, "good": 2, "easy": 4}


def quality_to_rating(quality: int) -> str:
    """Bucket a 0..5 SM-2 quality into one of the four UI ratings."""
    q = max(0, min(5, int(quality)))
    if q < 3:
        return "again"
    if q == 3:
        return "hard"
    if q == 4:
        return "good"
    return "easy"


def compute_flashcard_schedule(
    easiness: float,
    interval_days: int,
    repetitions: int,
    quality: int,
    *,
    max_interval_days: int = 3650,
    min_easiness: float | None = None,
) -> dict[str, Any]:
    """Next ``(easiness, interval_days, repetitions)`` for one flashcard review.

    Ease factor and repetition counting follow SM-2; the interval is shaped so
    ratings diverge monotonically (again ≤ hard ≤ good ≤ easy). Returns a dict
    with ``easiness`` (rounded), ``interval_days``, ``repetitions`` and the
    effective ``quality``.
    """
    q = max(0, min(5, int(quality)))
    rating = quality_to_rating(q)
    prev_interval = max(1, int(interval_days or 1))
    reps = max(0, int(repetitions or 0))

    # SM-2 drives the ease factor (and tells us the canonical "good" interval).
    new_ef, sm2_interval, _sm2_reps = apply_sm2(easiness, prev_interval, reps, q)
    if min_easiness is not None:
        try:
            floor = float(min_easiness)
            if 1.3 <= floor <= 5.0:
                new_ef = max(new_ef, floor)
        except (TypeError, ValueError):
            pass

    if rating == "again":
        interval = 1
        new_reps = 0
    elif reps == 0:
        # Graduating a new card: hard/good/easy fan out from day one.
        interval = _NEW_CARD_INTERVALS[rating]
        new_reps = reps + 1
    else:
        new_reps = reps + 1
        good_interval = max(1, int(sm2_interval))
        if rating == "hard":
            interval = max(1, min(good_interval - 1, round(prev_interval * _HARD_FACTOR)))
        elif rating == "good":
            interval = good_interval
        else:  # easy
            interval = max(good_interval + 1, round(good_interval * _EASY_BONUS))

    interval = max(1, min(int(interval), int(max_interval_days)))
    return {
        "easiness": round(new_ef, 3),
        "interval_days": interval,
        "repetitions": new_reps,
        "quality": q,
    }


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def format_interval_ru(days: int) -> str:
    """Short Russian label for a projected interval, for a button caption.

    ``1`` → ``"завтра"``; ``15`` → ``"15 дней"``; ``45`` → ``"1.5 мес"``;
    ``400`` → ``"1.1 года"``.
    """
    d = int(days)
    if d <= 0:
        return "сегодня"
    if d == 1:
        return "завтра"
    if d < 30:
        return f"{d} {_plural_ru(d, 'день', 'дня', 'дней')}"
    if d < 365:
        months = d / 30
        months_str = f"{months:.0f}" if abs(months - round(months)) < 0.05 else f"{months:.1f}"
        m_int = round(months)
        return f"{months_str} {_plural_ru(m_int, 'мес', 'мес', 'мес')}"
    years = d / 365
    is_whole = abs(years - round(years)) < 0.05
    years_str = f"{years:.0f}" if is_whole else f"{years:.1f}"
    # Fractional quantities take the genitive singular in Russian ("1.5 года").
    unit = _plural_ru(round(years), "год", "года", "лет") if is_whole else "года"
    return f"{years_str} {unit}"
