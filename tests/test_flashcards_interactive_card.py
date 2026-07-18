"""Interactive 3D flip flashcard iframe builder (client-side flip + rating bridge)."""

from app.flashcards_memory_signals import compute_card_memory_signals
from app.flashcards_rating_labels import RATING_BUTTONS
from app.flashcards_scheduling import RATING_TO_QUALITY
from app.ui.flashcards_interactive_card import build_interactive_card_html, estimate_interactive_card_height

_CARD = {
    "id": 42,
    "front": "front <b>&</b> question",
    "back": "back <script>x</script> answer",
    "deck_name": "Алгебра",
    "deck_source_type": "course",
    "tags": "algebra, formulas, course:abc123",
    "easiness": 2.5,
    "interval_days": 6,
    "repetitions": 3,
    "next_review": None,
    "last_review": None,
}

_INTERVAL_PREVIEW = {"again": 1, "hard": 4, "good": 6, "easy": 9}
_MEMORY = compute_card_memory_signals(_CARD)


def _build(**overrides) -> str:
    kwargs = dict(
        card=_CARD,
        idx=0,
        total=5,
        interval_preview=_INTERVAL_PREVIEW,
        memory=_MEMORY,
        initial_flipped=False,
        session_nonce=1,
    )
    kwargs.update(overrides)
    return build_interactive_card_html(**kwargs)


def test_front_and_back_are_html_escaped() -> None:
    html_out = _build()
    assert "<b>" not in html_out
    assert "<script>x</script>" not in html_out
    assert "&lt;b&gt;" in html_out
    assert "&lt;script&gt;" in html_out


def test_bridge_selectors_present_for_all_ratings_and_handoff() -> None:
    html_out = _build()
    for _label, q_label, _quality, _color in RATING_BUTTONS:
        assert f"st-key-fc_rate_{q_label}" in html_out
    assert "st-key-fc_gap_to_tutor" in html_out


def test_projected_intervals_shown_in_rating_chips() -> None:
    html_out = _build()
    # format_interval_ru(1) == "завтра", format_interval_ru(4) == "4 дня", etc.
    assert "завтра" in html_out
    assert "4 дня" in html_out
    assert "6 дней" in html_out
    assert "9 дней" in html_out


def test_physical_key_codes_present() -> None:
    html_out = _build()
    for code in ("Digit1", "Numpad1", "Digit4", "Numpad4", "Space", "Enter", "NumpadEnter", "KeyE"):
        assert code in html_out


def test_key_handler_attached_to_local_and_parent_document() -> None:
    html_out = _build()
    assert "document.addEventListener('keydown', window.__fcCardKeyHandler)" in html_out
    assert "pwin.document.addEventListener('keydown', pwin.__fcCardKeyHandler)" in html_out


def test_dedup_removes_both_card_handler_and_legacy_parent_handler() -> None:
    html_out = _build()
    # New handler deduped on both documents before re-attaching.
    assert "document.removeEventListener('keydown', window.__fcCardKeyHandler)" in html_out
    assert "pwin.document.removeEventListener('keydown', pwin.__fcCardKeyHandler)" in html_out
    # Legacy single-iframe keyboard module's handler is also swept from the
    # parent document, so a stale listener from a hot-reloaded prior page
    # can't double-fire a keystroke.
    assert "pwin.__fcKeyHandler" in html_out
    assert "pwin.document.removeEventListener('keydown', pwin.__fcKeyHandler)" in html_out


def test_typing_targets_are_ignored() -> None:
    html_out = _build()
    assert "input" in html_out and "textarea" in html_out and "isContentEditable" in html_out


def test_initial_flipped_reflected_in_markup() -> None:
    flipped_html = _build(initial_flipped=True)
    unflipped_html = _build(initial_flipped=False)
    assert "var initialFlipped = true;" in flipped_html
    assert "var initialFlipped = false;" in unflipped_html


def test_session_storage_key_namespaced_by_session_nonce() -> None:
    html_out = _build(session_nonce=7)
    assert "'fc_flip_' + queueNonce + '_' + cardId" in html_out
    assert "var queueNonce = 7;" in html_out
    assert "var cardId = 42;" in html_out


def test_ease_factor_alias_card_does_not_crash() -> None:
    card = dict(_CARD)
    card.pop("easiness")
    card["ease_factor"] = 2.5
    memory = compute_card_memory_signals(card)
    html_out = build_interactive_card_html(
        card=card,
        idx=0,
        total=5,
        interval_preview=_INTERVAL_PREVIEW,
        memory=memory,
        initial_flipped=False,
        session_nonce=1,
    )
    assert "fc3-scene" in html_out


def test_non_hex_ink_does_not_get_raw_alpha_suffix() -> None:
    html_out = _build(ink="rgb(1, 2, 3)")

    assert "rgb(1, 2, 3)22" not in html_out
    assert "border: 1px solid rgb(1, 2, 3)" in html_out


def test_rating_quality_matches_scheduling_quality_map() -> None:
    # If these diverge, a chip would show one rating's projected interval
    # while the bridge click sends a different `quality` to the server.
    from_labels = {q_label: quality for _label, q_label, quality, _color in RATING_BUTTONS}
    assert from_labels == RATING_TO_QUALITY


def test_card_resizes_itself_to_content_via_streamlit_frame_height() -> None:
    # A fixed Python-side height estimate leaves short cards with a big empty
    # box; the iframe measures its own front/back content and asks Streamlit
    # to shrink the frame via the standard component postMessage protocol.
    html_out = _build()
    assert "measureNaturalHeight" in html_out
    assert "streamlit:setFrameHeight" in html_out
    assert "isStreamlitMessage: true" in html_out
    assert "card3d.style.height = contentH + 'px'" in html_out


def test_estimate_height_grows_with_text_length_and_is_bounded() -> None:
    short_card = {"front": "q", "back": "a"}
    long_card = {"front": "q" * 500, "back": "a" * 500}
    short_h = estimate_interactive_card_height(short_card)
    long_h = estimate_interactive_card_height(long_card)
    assert short_h < long_h
    assert long_h <= 900


def test_estimate_height_grows_with_tag_count() -> None:
    # The outer iframe box is sized once from Python, before any content is
    # rendered — it can't shrink/grow afterwards (components.html() doesn't
    # get the JS resize message a declared custom component would). Tag
    # chips wrap onto their own line(s) and aren't reflected in front/back
    # text length at all, so an under-count here means the tag row gets
    # clipped at the iframe boundary with no scrollbar to reach it.
    few_tags = {"front": "q", "back": "a", "tags": "algebra, formulas"}
    many_tags = {"front": "q", "back": "a", "tags": "a, b, c, d, e, f, g, h"}
    assert estimate_interactive_card_height(many_tags) > estimate_interactive_card_height(few_tags)


def test_estimate_height_accounts_for_source_line() -> None:
    no_source = {"front": "q", "back": "a", "tags": "algebra"}
    with_source = {"front": "q", "back": "a", "tags": "algebra, source:lesson_3.md"}
    assert estimate_interactive_card_height(with_source) > estimate_interactive_card_height(no_source)


def test_hidden_face_is_marked_inert_so_it_leaves_tab_order() -> None:
    # backface-visibility only hides a face *visually* — its buttons/summary
    # stay focusable unless something removes them from the tab order.
    # `inert` is toggled on the face turned away from the viewer, both faces
    # start present, and the flip flag decides which one is disabled.
    html_out = _build()
    assert "frontFace.inert = flipped" in html_out
    assert "backFace.inert = !flipped" in html_out


def test_keyboard_shortcuts_skip_native_interactive_targets() -> None:
    # This handler is also attached to window.parent.document (see the
    # focus-crossing-iframe-boundary tests above), so e.target can be a real
    # Streamlit button, an expander <summary>, or a link — Space/Enter there
    # must reach that element's own activation, not hijack a card flip/rating.
    html_out = _build()
    assert (
        "t.closest('button, summary, a, select, [role=\"button\"], [contenteditable=\"true\"]')"
        in html_out
    )


# ─── W4 accessibility / sizing contract ─────────────────────────────────────


def test_w4_flip_surface_is_semantic_button_with_aria_pressed() -> None:
    html_out = _build()
    assert 'class="fc3-flip-surface"' in html_out or "class='fc3-flip-surface'" in html_out
    assert 'id="fc3-flip-surface"' in html_out
    assert 'aria-pressed="false"' in html_out
    assert "Показать ответ" in html_out
    assert "aria-live" in html_out
    assert "fc3-flip-status" in html_out
    assert "setAttribute('aria-pressed'" in html_out or 'setAttribute("aria-pressed"' in html_out


def test_w4_flip_back_button_has_accessible_name() -> None:
    html_out = _build()
    assert 'id="fc3-flip-back"' in html_out
    assert "к вопросу" in html_out
    assert "aria-label" in html_out


def test_w4_reduced_motion_disables_3d_rotation() -> None:
    html_out = _build()
    assert "prefers-reduced-motion" in html_out
    assert "transform: none !important" in html_out or "transform: none !important;" in html_out
    # Swap/fade path for back face under reduced motion.
    assert "visibility: hidden" in html_out


def test_w4_rating_chips_min_touch_geometry_and_mnemonic_primary() -> None:
    html_out = _build()
    assert "min-height: 44px" in html_out
    # Mnemonic meaning rendered before grade label in chip markup.
    again_idx = html_out.find('data-q="again"')
    assert again_idx > 0
    chip_slice = html_out[again_idx : again_idx + 400]
    assert "не вспомнил" in chip_slice
    meaning_pos = chip_slice.find("fc3-rate-meaning")
    label_pos = chip_slice.find("fc3-rate-label")
    eta_pos = chip_slice.find("fc3-rate-eta")
    assert 0 <= meaning_pos < label_pos < eta_pos


def test_w4_rating_chip_aria_label_includes_mnemonic() -> None:
    html_out = _build()
    assert "не вспомнил" in html_out
    assert 'aria-label="' in html_out
    assert "Интервал:" in html_out


def test_w4_resize_observer_and_frame_element_height() -> None:
    html_out = _build()
    assert "ResizeObserver" in html_out
    assert "window.frameElement" in html_out
    assert "data-fc3-resize-observer" in html_out
    assert "applyOuterHeight" in html_out
    assert "data-fc3-scroll-fallback" in html_out


def test_w4_focus_visible_on_primary_controls() -> None:
    html_out = _build()
    assert ":focus-visible" in html_out
    assert "fc3-flip-surface:focus-visible" in html_out or ".fc3-flip-surface:focus-visible" in html_out
    assert ".fc3-rate-chip:focus-visible" in html_out


def test_w4_review_host_keeps_scrolling_fallback() -> None:
    """Degraded path: host components.html keeps scrolling=True (W4 DoD)."""
    import inspect

    from app.ui import flashcards_review_view as review_mod

    src = inspect.getsource(review_mod)
    assert "scrolling=True" in src
    assert "estimate_interactive_card_height" in src


def test_w4_hub_has_single_section_nav_no_duplicate_buttons() -> None:
    """Horizontal radio only — no parallel Колоды/Создать/Повторение button row."""
    import inspect

    from app.ui import flashcards_ui as hub_mod

    src = inspect.getsource(hub_mod)
    assert "flashcards_main_section" in src
    assert "fc_nav_decks" not in src
    assert "fc_nav_create" not in src
    assert "fc_nav_review" not in src
