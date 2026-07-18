"""W4a: sidebar deep link «В Мнемополис» → Knowledge Graph via pending view."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from app.ui.mnemo_nav import (
    KG_GRAPH_TAB_LABEL,
    KG_MNEMO_TAB_LABEL,
    KG_OPEN_3D_HALL_KEY,
    KG_RETURN_FROM_KEY,
    KG_SURFACE_TAB_REVISION_KEY,
    KG_SURFACE_TAB_KEY,
    knowledge_surface_tab_key,
    open_mnemo_polis,
)
from app.ui.session_state import PENDING_CURRENT_VIEW_KEY


def test_open_mnemo_polis_sets_pending_view_not_current_view():
    state: dict = {}
    open_mnemo_polis(state=state)
    assert state[PENDING_CURRENT_VIEW_KEY] == "Knowledge Graph"
    assert state[KG_OPEN_3D_HALL_KEY] is True
    assert state[KG_SURFACE_TAB_REVISION_KEY] == 1
    assert state[knowledge_surface_tab_key(state=state)] == KG_MNEMO_TAB_LABEL
    # Must not write current_view (widget key risk).
    assert "current_view" not in state


def test_open_mnemo_polis_return_from_quiz_channel():
    state: dict = {}
    open_mnemo_polis(state=state, return_from="quiz")
    assert state[PENDING_CURRENT_VIEW_KEY] == "Knowledge Graph"
    assert state[KG_RETURN_FROM_KEY] == "quiz"
    assert state[KG_OPEN_3D_HALL_KEY] is True


def test_open_mnemo_polis_return_from_flashcards_and_collect():
    state: dict = {}
    open_mnemo_polis(state=state, return_from="flashcards")
    assert state[KG_RETURN_FROM_KEY] == "flashcards"
    state2: dict = {}
    open_mnemo_polis(state=state2, return_from="collect")
    assert state2[KG_RETURN_FROM_KEY] == "collect"


def test_arrival_banner_quiz_channel_message():
    import streamlit as st

    from app.ui.mnemo_nav import arrival_banner_message

    # Simulate post-click state without full Streamlit runtime where possible.
    st.session_state[KG_OPEN_3D_HALL_KEY] = True
    st.session_state[KG_RETURN_FROM_KEY] = "quiz"
    msg = arrival_banner_message()
    assert msg is not None
    assert "quiz" in msg.lower() or "✓" in msg
    assert KG_OPEN_3D_HALL_KEY not in st.session_state
    assert KG_RETURN_FROM_KEY not in st.session_state


def test_arrival_banner_flashcards_and_collect_channels():
    import streamlit as st

    from app.ui.mnemo_nav import arrival_banner_message

    st.session_state[KG_OPEN_3D_HALL_KEY] = True
    st.session_state[KG_RETURN_FROM_KEY] = "flashcards"
    msg_fc = arrival_banner_message()
    assert msg_fc and ("SR" in msg_fc or "туман" in msg_fc or "retention" in msg_fc)

    st.session_state[KG_OPEN_3D_HALL_KEY] = True
    st.session_state[KG_RETURN_FROM_KEY] = "collect"
    msg_c = arrival_banner_message()
    assert msg_c and "◆" in msg_c


def _app_sidebar_mnemo_button() -> None:
    """Selectbox first (main.py shape), then sidebar-style deep-link button."""
    import streamlit as st

    from app.ui.mnemo_nav import open_mnemo_polis

    st.selectbox(
        "Раздел",
        ["Mission Control", "Knowledge Graph", "Flashcards"],
        key="current_view",
    )
    if st.button("🌆 В Мнемополис", key="sidebar_nav_mnemo_polis"):
        open_mnemo_polis()
        st.rerun()


def _app_knowledge_surface_tabs() -> None:
    import streamlit as st

    from app.ui.mnemo_nav import (
        KG_GRAPH_TAB_LABEL,
        KG_MNEMO_TAB_LABEL,
        knowledge_surface_tab_key,
    )

    surface_tab_key = knowledge_surface_tab_key()
    graph_tab, mnemo_tab = st.tabs(
        [KG_GRAPH_TAB_LABEL, KG_MNEMO_TAB_LABEL],
        default=KG_GRAPH_TAB_LABEL,
        key=surface_tab_key,
        on_change="rerun",
    )
    if graph_tab.open:
        st.session_state["rendered_kg_surface"] = "graph"
    if mnemo_tab.open:
        st.session_state["rendered_kg_surface"] = "mnemo"


class TestSidebarMnemoPolisNavigation:
    def test_button_does_not_raise_and_sets_pending(self):
        at = AppTest.from_function(_app_sidebar_mnemo_button)
        at.run()
        at.button(key="sidebar_nav_mnemo_polis").click().run()
        assert not at.exception
        assert at.session_state[PENDING_CURRENT_VIEW_KEY] == "Knowledge Graph"
        assert at.session_state[KG_OPEN_3D_HALL_KEY] is True
        assert at.session_state[KG_SURFACE_TAB_REVISION_KEY] == 1
        surface_key = f"{KG_SURFACE_TAB_KEY}:1"
        assert at.session_state[surface_key] == KG_MNEMO_TAB_LABEL

    def test_sidebar_source_contains_button_key(self):
        from pathlib import Path

        src = Path("app/ui/sidebar.py").read_text(encoding="utf-8")
        assert "sidebar_nav_mnemo_polis" in src
        assert "В Мнемополис" in src
        assert "open_mnemo_polis" in src
        nav = Path("app/ui/mnemo_nav.py").read_text(encoding="utf-8")
        assert "render_return_to_mnemo_cta" in nav
        assert "return_from" in nav
        iq = Path("app/ui/interactive_quiz.py").read_text(encoding="utf-8")
        assert "interactive_quiz_return_mnemo" in iq
        assert "render_return_to_mnemo_cta" in iq
        fc = Path("app/ui/flashcards_review_view.py").read_text(encoding="utf-8")
        assert "flashcards_review_return_mnemo" in fc
        assert "return_from=\"flashcards\"" in fc or "return_from='flashcards'" in fc
        graph = Path("app/ui/dashboards_graph.py").read_text(encoding="utf-8")
        assert "st.tabs(" in graph
        assert "KG_GRAPH_TAB_LABEL, KG_MNEMO_TAB_LABEL" in graph
        assert 'on_change="rerun"' in graph
        assert "if graph_tab.open" in graph
        assert "if mnemo_tab.open" in graph
        assert "render_component=False" in graph
        # Commit 326 extended the D3 component call with `initial_selected_concept`
        # (persist the selected concept across tab switches). The assertion checks
        # the components of the new signature rather than a single exact line, so
        # it stays green whether the call is one-line or multi-line.
        assert "render_kg_d3_component(" in graph
        assert "height=740" in graph
        assert "initial_selected_concept" in graph

    def test_knowledge_graph_is_default_and_mnemo_state_is_lazy(self):
        at = AppTest.from_function(_app_knowledge_surface_tabs)
        at.run()
        assert not at.exception
        assert [tab.label for tab in at.tabs] == [
            KG_GRAPH_TAB_LABEL,
            KG_MNEMO_TAB_LABEL,
        ]
        assert at.session_state[f"{KG_SURFACE_TAB_KEY}:0"] == KG_GRAPH_TAB_LABEL
        assert at.session_state["rendered_kg_surface"] == "graph"

        at.session_state[KG_SURFACE_TAB_REVISION_KEY] = 1
        at.session_state[f"{KG_SURFACE_TAB_KEY}:1"] = KG_MNEMO_TAB_LABEL
        at.run()
        assert not at.exception
        assert at.session_state["rendered_kg_surface"] == "mnemo"

        at.run()
        assert not at.exception
        assert at.session_state[f"{KG_SURFACE_TAB_KEY}:1"] == KG_MNEMO_TAB_LABEL
        assert at.session_state["rendered_kg_surface"] == "mnemo"
