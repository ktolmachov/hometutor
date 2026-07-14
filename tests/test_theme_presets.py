"""Tests for theme_presets.py — key parity, forest byte-exact match."""
import re
from pathlib import Path

from app.ui.theme_presets import THEME_TOKENS, VALID_UI_THEMES, css_vars_for_theme


_ROOT_RE = re.compile(r":root\s*\{(?P<body>.*?)\}", re.DOTALL)
_VAR_RE = re.compile(r"^\s*--(?P<key>[\w-]+):\s*(?P<value>.*?);\s*$")


def _root_css_vars() -> dict[str, str]:
    css_path = Path(__file__).resolve().parents[1] / "app" / "ui_theme.css"
    css = css_path.read_text(encoding="utf-8")
    match = _ROOT_RE.search(css)
    assert match is not None, "ui_theme.css must define :root variables"

    vars_: dict[str, str] = {}
    for line in match.group("body").splitlines():
        var_match = _VAR_RE.match(line)
        if var_match:
            key = var_match.group("key")
            if not key.startswith("font-"):  # base fonts are global, not per-world theme tokens
                vars_[key] = var_match.group("value")
    return vars_


def _css_without_root_vars() -> str:
    css_path = Path(__file__).resolve().parents[1] / "app" / "ui_theme.css"
    css = css_path.read_text(encoding="utf-8")
    match = _ROOT_RE.search(css)
    assert match is not None, "ui_theme.css must define :root variables"
    return css[: match.start()] + css[match.end() :]


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
    assert forest == _root_css_vars()


def test_css_vars_for_theme_produces_valid_block() -> None:
    for tid in THEME_TOKENS:
        block = css_vars_for_theme(tid)
        assert block.startswith(":root {")
        assert block.endswith("}")
        assert "--bg-panel" in block
        assert "--ink" in block
        assert "--sidebar-bg" in block
        assert "--accent-soft" in block
        assert "--input-border" in block
        assert "--select-bg" in block
        assert "--recommended-shadow" in block
        assert "--flashcard-summary-bg" in block


def test_no_forest_accent_literals_outside_root_vars() -> None:
    css = _css_without_root_vars()
    forbidden = (
        "#132019",
        "#b95631",
        "#fffcf6",
        "rgba(125, 53, 31",
        "rgba(36, 59, 44",
        "rgba(185, 86, 49",
        "rgba(185,86,49",
        "rgba(255, 211, 158",
        "rgba(30,132,73",
    )
    for literal in forbidden:
        assert literal not in css


def test_no_empty_tokens() -> None:
    for tid, tokens in THEME_TOKENS.items():
        for key, value in tokens.items():
            assert value, f"world {tid!r} token {key!r} is empty"
