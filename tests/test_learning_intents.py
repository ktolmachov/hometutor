"""Tests for learning intents mapping (#23 P0-2 A2). Pure contract tests only."""
from __future__ import annotations

from app.ui.learning_intents import INTENTS


def test_all_intents_defined() -> None:
    assert len(INTENTS) == 10
    ids = {i.intent_id for i in INTENTS}
    assert ids == {
        "simpler", "practice", "check_me", "remember", "plan", "what_next", "didnt_get",
        "compose_session", "find_gap_practice", "connect_graph_quiz",
    }


def test_intent_labels_are_human_readable() -> None:
    for intent in INTENTS:
        assert intent.label_ru
        assert intent.sr_label
        assert intent.icon


def test_intent_ids_are_unique() -> None:
    ids = [i.intent_id for i in INTENTS]
    assert len(ids) == len(set(ids))


def test_intent_selected_event_in_session_tape_schema() -> None:
    from app.session_tape import EVENT_REQUIRED_FIELDS

    assert "intent_selected" in EVENT_REQUIRED_FIELDS
    assert "intent_id" in EVENT_REQUIRED_FIELDS["intent_selected"]


def test_intent_module_exports_intents_and_apply() -> None:
    from app.ui.learning_intents import apply_learning_intent

    assert callable(apply_learning_intent)


def test_intent_palette_present_in_ssr_card() -> None:
    """Verify SSR card source contains the intent palette integration."""
    from pathlib import Path

    source = (Path(__file__).parent.parent / "app" / "ui" / "smart_study_next_step_card.py").read_text(encoding="utf-8")
    assert "_render_intent_palette" in source
    assert "Сменить направление" in source
    assert "from app.ui.learning_intents" in source


def test_intent_palette_sr_labels_are_action_descriptions() -> None:
    """Screen-reader labels must describe the action, not the mode id."""
    for intent in INTENTS:
        assert intent.intent_id not in intent.sr_label
        assert len(intent.sr_label) > 10
