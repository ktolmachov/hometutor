"""W2b handoff: one-shot focus survives first scope-signature reset on Review entry."""

from __future__ import annotations

from app.ui.flashcards_review_view import (
    FLASHCARDS_REVIEW_SCOPE_PRIMARY_TAG_KEY,
    _card_matches_body_soft,
    _card_matches_focus_needles,
    _card_matches_meta_exact,
    apply_concept_handoff_queue_scope,
    apply_pending_review_scope_reset,
    consume_concept_handoff_one_shot,
    resolve_active_concept_scope_primary,
    resolve_concept_scope_api_tags,
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


def test_concept_handoff_prefers_concept_id_over_label_or_union():
    """OR tags (id+label) must not keep label-only unrelated cards when id matches exist."""
    queue = [
        {"id": 1, "tags": "linear-algebra", "front": "matrix rank", "back": "r"},
        {"id": 2, "tags": "Линейная алгебра", "front": "unrelated label twin", "back": "x"},
        {"id": 3, "tags": "other", "front": "no match", "back": "y"},
    ]
    scoped = apply_concept_handoff_queue_scope(
        queue,
        focus="linear-algebra",
        selected_tags=["linear-algebra", "Линейная алгебра"],
    )
    assert [c["id"] for c in scoped] == [1]


def test_concept_handoff_label_fallback_when_id_absent():
    """Cards tagged only with human label still load when no concept_id match."""
    queue = [
        {"id": 2, "tags": "Линейная алгебра", "front": "матрица", "back": "array"},
        {"id": 3, "tags": "other", "front": "no", "back": "y"},
    ]
    scoped = apply_concept_handoff_queue_scope(
        queue,
        focus="linear-algebra",
        selected_tags=["linear-algebra", "Линейная алгебра"],
    )
    assert [c["id"] for c in scoped] == [2]


def test_resolve_concept_scope_api_tags_primary_only():
    """Count/recovery/undo must not send id+label OR to backend."""
    tags = resolve_concept_scope_api_tags(
        ["linear-algebra", "Линейная алгебра"],
        primary="linear-algebra",
    )
    assert tags == ["linear-algebra"]
    assert resolve_concept_scope_api_tags(["a", "b"], primary=None) == ["a", "b"]


def test_sticky_primary_drops_when_tags_manually_cleared():
    """P1: empty tag field after handoff must leave concept scope (not keep primary)."""
    state = {
        FLASHCARDS_REVIEW_SCOPE_PRIMARY_TAG_KEY: "linear-algebra",
        "flashcards_focus_concept": "linear-algebra",
        # handoff finished — autoload already consumed
        "flashcards_review_autoload_pending": False,
        "flashcards_review_focus_filter_once": False,
    }
    active = resolve_active_concept_scope_primary(state, selected_tags=[])
    assert active == ""
    assert FLASHCARDS_REVIEW_SCOPE_PRIMARY_TAG_KEY not in state
    assert "flashcards_focus_concept" not in state


def test_handoff_then_clear_tags_load_count_recovery_without_primary():
    """Audit: handoff → user clears tags text → api_tags empty (all due), not [primary].

    Mirrors render_review wiring: resolve primary from state + selected_tags, then
    resolve_concept_scope_api_tags for count / due / recovery / undo payloads.
    """
    from app.ui.flashcards_review_view import apply_flashcards_concept_due_handoff

    state: dict = {}
    apply_flashcards_concept_due_handoff(
        state, concept_id="linear-algebra", label="Линейная алгебра"
    )
    assert state[FLASHCARDS_REVIEW_SCOPE_PRIMARY_TAG_KEY] == "linear-algebra"
    # First load consumed one-shot flags (as after autoload).
    state["flashcards_review_autoload_pending"] = False
    state.pop("flashcards_review_focus_filter_once", None)
    state.pop("flashcards_focus_concept", None)

    # User clears the tags text field → selected_tags == [].
    selected_tags: list[str] = []
    scope_primary = resolve_active_concept_scope_primary(
        state, selected_tags=selected_tags
    )
    api_tags = resolve_concept_scope_api_tags(
        selected_tags, primary=scope_primary or None
    )

    assert scope_primary == ""
    assert api_tags == []
    assert FLASHCARDS_REVIEW_SCOPE_PRIMARY_TAG_KEY not in state
    # Backend params must not carry a phantom concept tag.
    ser = ", ".join(api_tags) if api_tags else None
    assert ser is None


def test_due_api_failure_does_not_leave_handoff_pending_after_one_shot_consume():
    """Audit P2: one-shot flags must be consumed before /flashcards/due.

    If the due API fails after consume, clearing tags must still exit concept
    scope (resolver must not see stuck focus_once).
    """
    from app.ui.flashcards_review_view import apply_flashcards_concept_due_handoff

    state: dict = {}
    apply_flashcards_concept_due_handoff(
        state, concept_id="linear-algebra", label="Линейная алгебра"
    )
    # Load path always pops autoload first, then one-shot before API.
    state.pop("flashcards_review_autoload_pending", None)
    focus_once, focus = consume_concept_handoff_one_shot(state)
    assert focus_once is True
    assert focus == "linear-algebra"
    assert "flashcards_review_focus_filter_once" not in state
    assert "flashcards_focus_concept" not in state
    # Simulate due API failure: primary may still be sticky until tag clear.
    assert state.get(FLASHCARDS_REVIEW_SCOPE_PRIMARY_TAG_KEY) == "linear-algebra"
    # Learner clears tags after error → all due, not stuck concept scope.
    active = resolve_active_concept_scope_primary(state, selected_tags=[])
    api_tags = resolve_concept_scope_api_tags([], primary=active or None)
    assert active == ""
    assert api_tags == []


def test_sticky_primary_drops_when_primary_removed_from_tags():
    state = {
        FLASHCARDS_REVIEW_SCOPE_PRIMARY_TAG_KEY: "linear-algebra",
        "flashcards_review_autoload_pending": False,
        "flashcards_review_focus_filter_once": False,
    }
    active = resolve_active_concept_scope_primary(
        state, selected_tags=["other-topic"]
    )
    assert active == ""
    assert FLASHCARDS_REVIEW_SCOPE_PRIMARY_TAG_KEY not in state


def test_sticky_primary_kept_while_handoff_pending_even_if_tags_empty():
    """First handoff paint may briefly see empty widget before seed — keep primary."""
    state = {
        FLASHCARDS_REVIEW_SCOPE_PRIMARY_TAG_KEY: "linear-algebra",
        "flashcards_review_autoload_pending": True,
        "flashcards_review_focus_filter_once": True,
    }
    active = resolve_active_concept_scope_primary(state, selected_tags=[])
    assert active == "linear-algebra"
    assert state[FLASHCARDS_REVIEW_SCOPE_PRIMARY_TAG_KEY] == "linear-algebra"


def test_sticky_primary_kept_when_tags_still_include_concept():
    state = {
        FLASHCARDS_REVIEW_SCOPE_PRIMARY_TAG_KEY: "linear-algebra",
        "flashcards_review_autoload_pending": False,
    }
    active = resolve_active_concept_scope_primary(
        state, selected_tags=["linear-algebra", "линейная алгебра"]
    )
    assert active == "linear-algebra"


def test_scope_reset_clears_primary_api_tag():
    state = {
        "flashcards_review_scope_reset_pending": True,
        FLASHCARDS_REVIEW_SCOPE_PRIMARY_TAG_KEY: "linear-algebra",
        "flashcards_focus_concept": "linear-algebra",
        "flashcards_review_focus_filter_once": True,
        "flashcards_review_session_tags_text": "linear-algebra",
        "flashcards_review_session_tag_ids": ["linear-algebra"],
    }

    def _sig(deck, tags):
        return "sig"

    assert apply_pending_review_scope_reset(
        state,
        reset_review_session_state=_reset_review_session_state,
        review_scope_signature=_sig,
    )
    assert FLASHCARDS_REVIEW_SCOPE_PRIMARY_TAG_KEY not in state


def test_meta_exact_preferred_over_body_substring():
    """Primary exact tag wins; short body substring alone is not enough for short needles."""
    tagged = {"id": 1, "tags": "rag", "front": "something", "back": "x"}
    body_only = {"id": 2, "tags": "other", "front": "covers rag in prose", "back": "y"}
    assert _card_matches_meta_exact(tagged, ["rag"]) is True
    assert _card_matches_meta_exact(body_only, ["rag"]) is False
    # body soft requires min length; "rag" is 3 < 4 → no body match
    assert _card_matches_body_soft(body_only, ["rag"]) is False
    scoped = apply_concept_handoff_queue_scope(
        [tagged, body_only],
        focus="rag",
        selected_tags=["rag", "Retrieval"],
    )
    assert [c["id"] for c in scoped] == [1]


def test_body_fallback_for_long_needle_when_meta_empty():
    card = {
        "id": 9,
        "tags": "",
        "front": "linear-algebra matrices",
        "back": "definition",
    }
    assert _card_matches_focus_needles(card, ["linear-algebra"]) is True
    scoped = apply_concept_handoff_queue_scope(
        [card],
        focus="linear-algebra",
        selected_tags=["linear-algebra"],
    )
    assert [c["id"] for c in scoped] == [9]
