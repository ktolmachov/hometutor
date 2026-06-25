"""Flashcard scheduler: Anki-style divergent intervals + Russian interval labels."""

import pytest

from app.flashcards_scheduling import (
    RATING_TO_QUALITY,
    compute_flashcard_schedule,
    format_interval_ru,
    quality_to_rating,
)


def _interval(easiness, interval_days, repetitions, rating):
    sched = compute_flashcard_schedule(
        easiness, interval_days, repetitions, RATING_TO_QUALITY[rating]
    )
    return sched["interval_days"]


def test_quality_buckets() -> None:
    assert quality_to_rating(0) == "again"
    assert quality_to_rating(1) == "again"
    assert quality_to_rating(3) == "hard"
    assert quality_to_rating(4) == "good"
    assert quality_to_rating(5) == "easy"


def test_review_card_intervals_diverge_monotonically() -> None:
    # The core fix: on a real review card hard < good < easy (vanilla SM-2 made
    # all three identical), and "again" always resets to tomorrow.
    again = _interval(2.5, 6, 2, "again")
    hard = _interval(2.5, 6, 2, "hard")
    good = _interval(2.5, 6, 2, "good")
    easy = _interval(2.5, 6, 2, "easy")
    assert again == 1
    assert again <= hard < good < easy


def test_new_card_fans_out_from_day_one() -> None:
    # A brand-new card (reps=0) previously scheduled every rating at 1 day.
    assert _interval(2.5, 0, 0, "again") == 1
    assert _interval(2.5, 0, 0, "hard") == 1
    assert _interval(2.5, 0, 0, "good") == 2
    assert _interval(2.5, 0, 0, "easy") == 4


def test_again_resets_repetitions_and_keeps_ease_floor() -> None:
    sched = compute_flashcard_schedule(2.5, 30, 5, 0)
    assert sched["interval_days"] == 1
    assert sched["repetitions"] == 0
    assert sched["easiness"] >= 1.3


def test_good_and_easy_increment_repetitions() -> None:
    assert compute_flashcard_schedule(2.5, 6, 2, 4)["repetitions"] == 3
    assert compute_flashcard_schedule(2.5, 6, 2, 5)["repetitions"] == 3


def test_min_easiness_floor_applied() -> None:
    # Repeated lapses would drop ease below the floor without clamping.
    low = compute_flashcard_schedule(1.4, 6, 2, 0, min_easiness=2.0)
    assert low["easiness"] >= 2.0


def test_max_interval_clamped() -> None:
    sched = compute_flashcard_schedule(2.5, 1000, 9, 5, max_interval_days=100)
    assert sched["interval_days"] == 100


@pytest.mark.parametrize(
    "days,expected",
    [
        (0, "сегодня"),
        (1, "завтра"),
        (2, "2 дня"),
        (5, "5 дней"),
        (21, "21 день"),
        (15, "15 дней"),
    ],
)
def test_format_interval_ru_days(days, expected) -> None:
    assert format_interval_ru(days) == expected


def test_format_interval_ru_months_and_years() -> None:
    assert format_interval_ru(60) == "2 мес"
    assert format_interval_ru(45) == "1.5 мес"
    assert format_interval_ru(365) == "1 год"
    assert format_interval_ru(400).endswith("года")
