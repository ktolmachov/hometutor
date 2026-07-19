"""Regression: wave-progress-home P0-1 navigation contracts — sidebar & alias redirect."""
from __future__ import annotations

from pathlib import Path
import runpy

import streamlit as st

from app.ui.session_state import PENDING_CURRENT_VIEW_KEY


def test_sidebar_uses_pending_key_not_switch_page() -> None:
    sidebar_path = Path(__file__).resolve().parent.parent / "app" / "ui" / "sidebar.py"
    text = sidebar_path.read_text(encoding="utf-8")

    assert "PENDING_CURRENT_VIEW_KEY" in text
    assert '"Прогресс обучения"' in text
    assert 'st.switch_page("pages/3_Мой_прогресс.py")' not in text


def test_orphan_alias_sets_pending_view_and_breadcrumb() -> None:
    orphan_path = (
        Path(__file__).resolve().parent.parent
        / "app" / "ui" / "pages" / "3_Мой_прогресс.py"
    )
    text = orphan_path.read_text(encoding="utf-8")

    assert "PENDING_CURRENT_VIEW_KEY" in text
    assert '"Прогресс обучения"' in text
    assert '"home_breadcrumb_origin"' in text
    assert '"Mission Control"' in text
    assert 'st.switch_page("main.py")' in text


def test_orphan_alias_runtime_sets_pending_view_and_switches_to_main(monkeypatch) -> None:
    orphan_path = (
        Path(__file__).resolve().parent.parent
        / "app" / "ui" / "pages" / "3_Мой_прогресс.py"
    )
    state: dict[str, str] = {}
    switched: list[str] = []

    monkeypatch.setattr(st, "session_state", state)
    monkeypatch.setattr(st, "switch_page", switched.append)

    runpy.run_path(str(orphan_path))

    assert state[PENDING_CURRENT_VIEW_KEY] == "Прогресс обучения"
    assert state["home_breadcrumb_origin"] == "Mission Control"
    assert switched == ["main.py"]


def test_render_progress_home_tab_impl_no_dead_params() -> None:
    home_path = (
        Path(__file__).resolve().parent.parent / "app" / "ui" / "dashboards_progress_home.py"
    )
    text = home_path.read_text(encoding="utf-8")

    sig_line = [ln for ln in text.splitlines() if "def render_progress_home_tab_impl" in ln]
    assert sig_line, "render_progress_home_tab_impl not found"
    assert "stats" not in sig_line[0], "dead param 'stats' should be removed"
    assert "qs" not in sig_line[0], "dead param 'qs' should be removed"


def test_extended_extras_reading_topics_under_debug_gate() -> None:
    home_path = (
        Path(__file__).resolve().parent.parent / "app" / "ui" / "dashboards_progress_home.py"
    )
    text = home_path.read_text(encoding="utf-8")

    assert 'feature_visible_by_id("panel:debug_summary")' in text
    assert "reading_topics" in text


def test_sidebar_sets_home_breadcrumb_origin_for_progress() -> None:
    """Sidebar button for progress must set home_breadcrumb_origin so breadcrumb shows."""
    sidebar_path = Path(__file__).resolve().parent.parent / "app" / "ui" / "sidebar.py"
    text = sidebar_path.read_text(encoding="utf-8")

    assert '"home_breadcrumb_origin"' in text
    assert '"Mission Control"' in text
    assert "sidebar_nav_mastery" in text
