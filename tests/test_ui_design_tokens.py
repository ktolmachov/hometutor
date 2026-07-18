"""W3: foundation design tokens contract."""

from __future__ import annotations

from pathlib import Path

from app.ui.design_tokens import (
    FOUNDATION_TOKEN_KEYS,
    FOUNDATION_TOKENS,
    FULL_DARK_DECISION,
    FULL_DARK_RATIONALE,
    SPATIAL_DARK_TOKENS,
    UI_MODES,
    foundation_css_block,
    is_world_theme_token,
)


def test_foundation_keys_match_tokens_dict():
    assert FOUNDATION_TOKEN_KEYS == frozenset(FOUNDATION_TOKENS.keys())


def test_foundation_baseline_sizes():
    assert FOUNDATION_TOKENS["type-meta"] == "12px"
    assert FOUNDATION_TOKENS["type-body"] == "16px"
    assert FOUNDATION_TOKENS["control-default"] == "40px"
    assert FOUNDATION_TOKENS["control-touch"] == "44px"
    assert FOUNDATION_TOKENS["space-1"] == "4px"
    assert FOUNDATION_TOKENS["space-4"] == "16px"


def test_modes_and_full_dark_gate():
    assert "light" in UI_MODES
    assert "spatial-dark" in UI_MODES
    assert "dark" not in UI_MODES  # not enabled until gate approved
    assert FULL_DARK_DECISION in {"approved", "rejected", "deferred"}
    assert FULL_DARK_DECISION == "deferred"
    assert "portal" in FULL_DARK_RATIONALE.casefold() or "base" in FULL_DARK_RATIONALE.casefold()


def test_spatial_dark_has_surface_and_text():
    assert SPATIAL_DARK_TOKENS["surface"].startswith("#")
    assert SPATIAL_DARK_TOKENS["text"].startswith("#")
    assert "accent" in SPATIAL_DARK_TOKENS


def test_foundation_css_block_lists_all_keys():
    block = foundation_css_block()
    for key in FOUNDATION_TOKENS:
        assert f"--{key}:" in block


def test_world_token_classifier():
    assert is_world_theme_token("ink") is True
    assert is_world_theme_token("space-1") is False
    assert is_world_theme_token("font-sans") is False


def test_ui_theme_css_has_no_hardcoded_brand_in_new_surface_helpers():
    """New W3 a11y helpers should prefer vars, not forest hex literals."""
    css = Path("app/ui_theme.css").read_text(encoding="utf-8")
    # Focus / portal blocks after foundation should not introduce #b95631
    idx = css.find("W3 accessibility foundation")
    assert idx > 0
    tail = css[idx : idx + 2500]
    assert "#b95631" not in tail
    assert "var(--focus-ring-color" in tail or "var(--accent" in tail
