"""Undo snapshot for one-step flashcard review undo."""

from app.flashcard_service import build_flashcard_review_undo_snapshot


def test_snapshot_captures_sr_fields() -> None:
    card = {
        "id": 42,
        "easiness": 2.36,
        "interval_days": 15,
        "repetitions": 3,
        "next_review": "2026-07-10T00:00:00+00:00",
        "last_review": "2026-06-25T00:00:00+00:00",
        "front": "q",
        "back": "a",
    }
    snap = build_flashcard_review_undo_snapshot(card)
    assert snap == {
        "card_id": 42,
        "easiness": 2.36,
        "interval_days": 15,
        "repetitions": 3,
        "next_review": "2026-07-10T00:00:00+00:00",
        "last_review": "2026-06-25T00:00:00+00:00",
    }


def test_snapshot_defaults_for_new_card() -> None:
    # A never-reviewed card: NULL review timestamps, default ease, no interval.
    snap = build_flashcard_review_undo_snapshot({"id": 7})
    assert snap["card_id"] == 7
    assert snap["easiness"] == 2.5
    assert snap["interval_days"] == 0
    assert snap["repetitions"] == 0
    assert snap["next_review"] is None
    assert snap["last_review"] is None


def test_snapshot_is_json_safe_types() -> None:
    snap = build_flashcard_review_undo_snapshot(
        {"id": "9", "easiness": "2.5", "interval_days": "6", "repetitions": "2"}
    )
    assert isinstance(snap["card_id"], int)
    assert isinstance(snap["easiness"], float)
    assert isinstance(snap["interval_days"], int)
    assert isinstance(snap["repetitions"], int)
