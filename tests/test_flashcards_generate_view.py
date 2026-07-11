"""Tests for Flashcards generate-view routing helpers."""

from __future__ import annotations

from app.ui import flashcards_generate_view as view
from app.ui import flashcards_ui


def test_route_saved_living_konspekt_deck_to_review(monkeypatch):
    import app.ui_events as ui_events

    events: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(ui_events, "track_event", lambda name, payload=None: events.append((name, payload)))
    state: dict[str, object] = {
        "flashcards_review_session_scope_signature": "old",
        "flashcards_review_session_tags_text": "source:old.md",
        "flashcards_review_session_tag_ids": ["source:old.md"],
    }
    monkeypatch.setattr(view.st, "session_state", state)

    view._route_saved_living_konspekt_deck_to_review(42)

    assert events == [("living_konspekt_term_deck_saved", {"deck_id": 42})]

    assert state["flashcards_subview"] == "review_from_deck"
    assert state["flashcards_review_session_deck_id"] == 42
    assert state["flashcards_review_deck_sync_pending"] == 42
    assert state["flashcards_review_session_tags_text"] == ""
    assert state["flashcards_review_session_tag_ids"] == []
    assert state["flashcards_section_pending"] == "review"
    assert state["flashcards_review_queue"] == []
    assert state["flashcards_review_index"] == 0
    assert state["flashcards_card_flipped"] is False
    assert state["flashcards_review_stats"] == {"again": 0, "hard": 0, "good": 0, "easy": 0}
    assert "flashcards_review_session_scope_signature" not in state


def test_seed_review_scope_can_autoload_deck_queue(monkeypatch):
    state: dict[str, object] = {
        "flashcards_review_session_scope_signature": "old",
        "flashcards_review_queue": [{"id": 1}],
    }
    monkeypatch.setattr(flashcards_ui.st, "session_state", state)

    flashcards_ui._seed_review_scope(42, autoload=True)

    assert state["flashcards_review_session_deck_id"] == 42
    assert state["flashcards_review_deck_sync_pending"] == 42
    assert state["flashcards_review_autoload_pending"] is True
    assert state["flashcards_review_queue"] == []
    assert state["flashcards_review_index"] == 0
    assert state["flashcards_card_flipped"] is False
