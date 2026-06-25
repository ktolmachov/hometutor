"""Keyboard-shortcut JS builder for the flashcard review loop."""

from app.flashcards_review_keyboard import build_review_keyboard_js


def test_unflipped_only_wires_reveal() -> None:
    js = build_review_keyboard_js(False)
    assert "var flipped = false;" in js
    # Reveal target present; rating clicks are gated behind the flipped branch.
    assert "st-key-fc_flip" in js
    assert "st-key-fc_rate_again" in js  # in the rate map, but unreachable when not flipped


def test_flipped_wires_all_rating_targets() -> None:
    js = build_review_keyboard_js(True)
    assert "var flipped = true;" in js
    for cls in (
        "st-key-fc_rate_again",
        "st-key-fc_rate_hard",
        "st-key-fc_rate_good",
        "st-key-fc_rate_easy",
        "st-key-fc_gap_to_tutor",
    ):
        assert cls in js


def test_uses_physical_key_codes_for_layout_independence() -> None:
    js = build_review_keyboard_js(True)
    # Physical codes (not e.key) so ЙЦУКЕН / digits-row both work.
    for code in ("Digit1", "Numpad1", "Digit4", "Space", "Enter", "KeyE"):
        assert code in js


def test_listener_is_deduped_across_reruns() -> None:
    js = build_review_keyboard_js(True)
    # Prior handler removed before re-attaching, so reruns don't stack listeners.
    assert "removeEventListener('keydown', win.__fcHandler" not in js  # guard against typo
    assert "win.__fcKeyHandler" in js
    assert "removeEventListener('keydown', win.__fcKeyHandler)" in js
    assert "addEventListener('keydown', win.__fcKeyHandler)" in js


def test_ignores_typing_targets() -> None:
    js = build_review_keyboard_js(True)
    assert "input" in js and "textarea" in js and "isContentEditable" in js
