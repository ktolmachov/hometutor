"""Tests for theme_presets.py — key parity, forest byte-exact match."""
from app.ui.theme_presets import THEME_TOKENS, VALID_UI_THEMES, css_vars_for_theme


def test_all_worlds_have_identical_token_keys() -> None:
    keys = None
    for tid, tokens in THEME_TOKENS.items():
        if keys is None:
            keys = set(tokens.keys())
        else:
            assert set(tokens.keys()) == keys, (
                f"world {tid!r} has mismatched keys: "
                f"extra={set(tokens.keys()) - keys}, "
                f"missing={keys - set(tokens.keys())}"
            )


def test_valid_ui_themes_match_presets() -> None:
    assert VALID_UI_THEMES == frozenset(THEME_TOKENS.keys())


def test_forest_values_match_current_css() -> None:
    forest = THEME_TOKENS.get("forest")
    assert forest is not None, "forest preset must exist"
    # Forest must match the CSS :root values (pinned literals in ui_theme.css)
    forest_expected = {
        "bg-panel": "rgba(255, 252, 246, 0.92)",
        "bg-card": "rgba(255, 255, 255, 0.9)",
        "ink": "#132019",
        "muted": "#59685f",
        "accent": "#b95631",
        "accent-dark": "#7d351f",
        "forest": "#243b2c",
        "line": "rgba(19, 32, 25, 0.12)",
        "shadow": "0 20px 48px rgba(49, 29, 15, 0.08)",
        "bg-app-1": "rgba(231, 177, 104, 0.18)",
        "bg-app-2": "rgba(86, 126, 89, 0.12)",
        "bg-app-3": "#f8f2e7",
        "bg-app-4": "#f4ede0",
        "bg-hero": "linear-gradient(135deg, rgba(34, 61, 44, 0.97), rgba(101, 56, 35, 0.95))",
        "bg-hero-text": "#fff6ea",
        "head-text": "#fffef8",
        "head-continue": "linear-gradient(135deg, #1b3224 0%, #2e4a39 40%, #6b3820 100%)",
        "head-due": "linear-gradient(135deg, #5c3564 0%, #b95631 100%)",
        "head-fc": "linear-gradient(135deg, #1a3a4a 0%, #b95631 100%)",
        "chip-bg": "rgba(185, 86, 49, 0.1)",
        "chip-border": "rgba(185, 86, 49, 0.14)",
        "flashcard-front": "linear-gradient(160deg, rgba(36,59,44,0.04) 0%, rgba(185,86,49,0.04) 100%)",
        "flashcard-back": "linear-gradient(160deg, rgba(185,86,49,0.07) 0%, rgba(36,59,44,0.05) 100%)",
        "sidebar-bg": "rgba(251, 244, 233, 0.96)",
        "button-bg": "linear-gradient(180deg, #be633c 0%, #9d4526 100%)",
        "button-bg-hover": "linear-gradient(180deg, #c86d45 0%, #8f3d22 100%)",
        "button-shadow": "0 10px 24px rgba(185, 86, 49, 0.18)",
        "accent-soft": "rgba(185, 86, 49, 0.10)",
    }
    assert forest == forest_expected, (
        f"forest preset mismatch: {set(forest.keys()) ^ set(forest_expected.keys())}"
    )


def test_css_vars_for_theme_produces_valid_block() -> None:
    for tid in THEME_TOKENS:
        block = css_vars_for_theme(tid)
        assert block.startswith(":root {")
        assert block.endswith("}")
        assert "--bg-panel" in block
        assert "--ink" in block
        assert "--sidebar-bg" in block
        assert "--accent-soft" in block


def test_no_empty_tokens() -> None:
    for tid, tokens in THEME_TOKENS.items():
        for key, value in tokens.items():
            assert value, f"world {tid!r} token {key!r} is empty"
