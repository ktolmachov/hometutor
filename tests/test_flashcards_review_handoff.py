"""W2b handoff: one-shot focus survives first scope-signature reset on Review entry."""

from __future__ import annotations

from app.ui.flashcards_review_view import (
    _card_matches_focus_needles,
    apply_pending_review_scope_reset,
)
from app.ui.flashcards_ui import _reset_review_session_state


def test_reset_preserves_one_shot_while_autoload_pending():
    state = {
        "flashcards_review_autoload_pending": True,
        "flashcards_focus_concept": "linear-algebra",
        "flashcards_review_focus_filter_once": True,
        "flashcards_review_queue": [{"id": 1}],
        "flashcards_review_index": 3,
    }
    _reset_review_session_state(state)
    assert state["flashcards_focus_concept"] == "linear-algebra"
    assert state["flashcards_review_focus_filter_once"] is True
    assert state["flashcards_review_queue"] == []
    assert state["flashcards_review_index"] == 0


def test_reset_clears_one_shot_without_autoload():
    state = {
        "flashcards_focus_concept": "linear-algebra",
        "flashcards_review_focus_filter_once": True,
    }
    _reset_review_session_state(state)
    assert "flashcards_focus_concept" not in state
    assert "flashcards_review_focus_filter_once" not in state


def test_scope_reset_clears_one_shot_even_if_autoload_was_set():
    """Explicit «Сбросить фильтр» must drop focus (pops before reset)."""
    state = {
        "flashcards_review_scope_reset_pending": True,
        "flashcards_review_autoload_pending": True,
        "flashcards_focus_concept": "rag",
        "flashcards_review_focus_filter_once": True,
        "flashcards_review_session_tags_text": "rag",
        "flashcards_review_session_tag_ids": ["rag"],
    }

    def _sig(deck, tags):
        return "sig"

    cleared = apply_pending_review_scope_reset(
        state,
        reset_review_session_state=_reset_review_session_state,
        review_scope_signature=_sig,
    )
    assert cleared is True
    assert "flashcards_focus_concept" not in state
    assert "flashcards_review_focus_filter_once" not in state


def test_handoff_then_scope_mismatch_reset_keeps_needles_for_autoload():
    """Simulate first Review render after 3D handoff: tags change → reset → autoload."""
    # State after _apply_flashcards_concept_due_handoff
    state = {
        "flashcards_focus_concept": "linear-algebra",
        "flashcards_review_focus_filter_once": True,
        "flashcards_review_autoload_pending": True,
        "flashcards_review_session_tags_text": "linear-algebra, Линейная алгебра",
        "flashcards_review_session_tag_ids": ["linear-algebra", "Линейная алгебра"],
        "flashcards_review_session_scope_signature": "old-scope",
        "flashcards_review_queue": [],
        "flashcards_review_session_status": "idle",
    }
    # Scope signature mismatch path (as in render_review)
    _reset_review_session_state(state)
    assert state["flashcards_review_focus_filter_once"] is True
    assert state["flashcards_focus_concept"] == "linear-algebra"
    # Soft match still works for empty tag-API fallback
    card = {"tags": "Линейная алгебра", "front": "матрица", "back": "array"}
    needles = ["linear-algebra", "Линейная алгебра"]
    assert _card_matches_focus_needles(card, needles)
