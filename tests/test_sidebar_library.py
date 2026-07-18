"""Sidebar Library quick link navigation."""

from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
from app.ui.sidebar import open_library


def test_open_library_sets_pending_view_not_current_view() -> None:
    state: dict = {}

    open_library(state=state)

    assert state[PENDING_CURRENT_VIEW_KEY] == "Библиотека"
    assert "current_view" not in state


def test_sidebar_source_contains_library_button_key() -> None:
    from pathlib import Path

    src = Path("app/ui/sidebar.py").read_text(encoding="utf-8")

    assert "sidebar_nav_library" in src
    assert "📚 Библиотека" in src
    assert "open_library" in src
