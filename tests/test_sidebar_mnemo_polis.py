"""W4a: sidebar deep link «В Мнемополис» → Knowledge Graph via pending view."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
from app.ui.sidebar import open_mnemo_polis


def test_open_mnemo_polis_sets_pending_view_not_current_view():
    state: dict = {}
    open_mnemo_polis(state=state)
    assert state[PENDING_CURRENT_VIEW_KEY] == "Knowledge Graph"
    assert state["kg_open_3d_hall"] is True
    # Must not write current_view (widget key risk).
    assert "current_view" not in state


def _app_sidebar_mnemo_button() -> None:
    """Selectbox first (main.py shape), then sidebar-style deep-link button."""
    import streamlit as st

    from app.ui.sidebar import open_mnemo_polis

    st.selectbox(
        "Раздел",
        ["Mission Control", "Knowledge Graph", "Flashcards"],
        key="current_view",
    )
    if st.button("🌆 В Мнемополис", key="sidebar_nav_mnemo_polis"):
        open_mnemo_polis()
        st.rerun()


class TestSidebarMnemoPolisNavigation:
    def test_button_does_not_raise_and_sets_pending(self):
        at = AppTest.from_function(_app_sidebar_mnemo_button)
        at.run()
        at.button(key="sidebar_nav_mnemo_polis").click().run()
        assert not at.exception
        assert at.session_state[PENDING_CURRENT_VIEW_KEY] == "Knowledge Graph"
        assert at.session_state["kg_open_3d_hall"] is True

    def test_sidebar_source_contains_button_key(self):
        from pathlib import Path

        src = Path("app/ui/sidebar.py").read_text(encoding="utf-8")
        assert "sidebar_nav_mnemo_polis" in src
        assert "В Мнемополис" in src
        assert "open_mnemo_polis" in src
