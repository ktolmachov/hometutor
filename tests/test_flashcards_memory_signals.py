"""Pure local memory-strength analytics for the review card face (no LLM/DB)."""

from datetime import datetime, timedelta, timezone

from app.flashcards_memory_signals import compute_card_memory_signals


def _card(**overrides):
    base = {
        "id": 1,
        "front": "q",
        "back": "a",
        "easiness": 2.5,
        "interval_days": 0,
        "repetitions": 0,
        "next_review": None,
        "last_review": None,
    }
    base.update(overrides)
    return base


def test_new_card_is_new_status_with_low_strength() -> None:
    signals = compute_card_memory_signals(_card())
    assert signals["status"] == "new"
    assert signals["overdue_days"] == 0
    assert signals["forecast_ru"] == "готова к первому повторению"
    assert 0 <= signals["strength_pct"] < 30


def test_status_bucket_boundaries() -> None:
    def status_for(interval_days: int, repetitions: int = 5) -> str:
        return compute_card_memory_signals(_card(interval_days=interval_days, repetitions=repetitions))["status"]

    assert status_for(1) == "learning"
    assert status_for(2) == "young"
    assert status_for(7) == "young"
    assert status_for(8) == "maturing"
    assert status_for(30) == "maturing"
    assert status_for(31) == "mature"


def test_zero_repetitions_is_always_new_regardless_of_interval() -> None:
    signals = compute_card_memory_signals(_card(interval_days=45, repetitions=0))
    assert signals["status"] == "new"


def test_strength_pct_monotonic_in_interval_days() -> None:
    low = compute_card_memory_signals(_card(interval_days=1, repetitions=3))["strength_pct"]
    high = compute_card_memory_signals(_card(interval_days=60, repetitions=3))["strength_pct"]
    assert high > low


def test_strength_pct_monotonic_in_repetitions() -> None:
    low = compute_card_memory_signals(_card(interval_days=10, repetitions=1))["strength_pct"]
    high = compute_card_memory_signals(_card(interval_days=10, repetitions=8))["strength_pct"]
    assert high > low


def test_strength_pct_monotonic_in_easiness() -> None:
    low = compute_card_memory_signals(_card(interval_days=10, repetitions=3, easiness=1.4))["strength_pct"]
    high = compute_card_memory_signals(_card(interval_days=10, repetitions=3, easiness=2.9))["strength_pct"]
    assert high > low


def test_strength_pct_is_bounded() -> None:
    signals = compute_card_memory_signals(_card(interval_days=3650, repetitions=999, easiness=5.0))
    assert 0 <= signals["strength_pct"] <= 100


def test_overdue_card_reports_days_overdue_and_forecast() -> None:
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    next_review = (now - timedelta(days=5)).isoformat()
    signals = compute_card_memory_signals(
        _card(interval_days=10, repetitions=3, next_review=next_review), now=now
    )
    assert signals["overdue_days"] == 5
    assert signals["forecast_ru"] == "просрочена на 5 дн."


def test_future_next_review_reports_days_until() -> None:
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    next_review = (now + timedelta(days=4)).isoformat()
    signals = compute_card_memory_signals(
        _card(interval_days=10, repetitions=3, next_review=next_review), now=now
    )
    assert signals["overdue_days"] == 0
    assert "4" in signals["forecast_ru"]
    assert "до повтора" in signals["forecast_ru"]


def test_null_next_review_does_not_crash_and_has_zero_overdue() -> None:
    # get_due_flashcards includes brand-new cards with next_review IS NULL.
    signals = compute_card_memory_signals(_card(next_review=None))
    assert signals["overdue_days"] == 0


def test_unparsable_next_review_does_not_crash() -> None:
    signals = compute_card_memory_signals(_card(next_review="not-a-date"))
    assert signals["overdue_days"] == 0


def test_naive_now_is_normalized_to_utc_without_crashing() -> None:
    naive_now = datetime(2026, 7, 1)  # no tzinfo — would TypeError against aware next_review.
    next_review = "2026-06-20T00:00:00+00:00"
    signals = compute_card_memory_signals(_card(next_review=next_review), now=naive_now)
    assert signals["overdue_days"] >= 10


def test_ease_factor_alias_used_when_easiness_missing() -> None:
    # Offline/e2e fixtures (app/offline_payloads/scenario_06.json) carry
    # `ease_factor`, not `easiness` — same alias fallback as
    # filter_due_cards_expert (app/flashcard_service.py:718).
    card = {
        "id": 2,
        "front": "q",
        "back": "a",
        "ease_factor": 2.5,
        "interval_days": 0,
        "repetitions": 0,
        "next_review": None,
    }
    signals = compute_card_memory_signals(card)
    assert signals["easiness"] == 2.5


def test_ease_label_buckets() -> None:
    hard = compute_card_memory_signals(_card(easiness=1.5))["ease_label_ru"]
    medium = compute_card_memory_signals(_card(easiness=2.5))["ease_label_ru"]
    easy = compute_card_memory_signals(_card(easiness=2.9))["ease_label_ru"]
    assert hard == "трудная"
    assert medium == "средняя"
    assert easy == "лёгкая"


def test_status_label_and_color_present_for_every_status() -> None:
    for interval_days, repetitions in ((0, 0), (1, 2), (5, 2), (15, 2), (60, 2)):
        signals = compute_card_memory_signals(_card(interval_days=interval_days, repetitions=repetitions))
        assert signals["status_label_ru"]
        assert signals["status_color"].startswith("#")
