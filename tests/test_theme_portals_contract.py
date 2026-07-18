"""W3: Streamlit portal / theme base static contract (full dark deferred)."""

from __future__ import annotations

from pathlib import Path

from app.ui.design_tokens import FULL_DARK_DECISION, PORTAL_SELECTORS


def test_streamlit_base_remains_light_while_dark_deferred():
    cfg = Path(".streamlit/config.toml").read_text(encoding="utf-8")
    assert 'base = "light"' in cfg
    assert FULL_DARK_DECISION == "deferred"


def test_portal_selectors_present_in_ui_theme_css():
    css = Path("app/ui_theme.css").read_text(encoding="utf-8")
    for sel in PORTAL_SELECTORS:
        assert sel in css, f"missing portal selector {sel}"


def test_portal_block_sets_background_text_and_focus():
    css = Path("app/ui_theme.css").read_text(encoding="utf-8")
    assert "data-baseweb=\"popover\"" in css or "data-baseweb='popover'" in css
    assert "background-color: var(--select-bg" in css or "background-color: var(--surface" in css
    assert "aria-disabled" in css
    assert "focus-visible" in css


def test_kgx_spatial_aliases_in_hall_template():
    html = Path("app/ui/assets/kg_3d_template.html").read_text(encoding="utf-8")
    assert "--surface-spatial" in html
    assert "--text-spatial" in html
    assert "--kgx-panel" in html
    assert "prefers-reduced-motion" in html
