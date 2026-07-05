"""Streamlit @fragment обёртки для частичного rerun (US-12.2 split)."""

import streamlit as st

from app.ui.dashboards import (
    _render_knowledge_graph_tab,
    _render_learning_progress_tab,
)
from app.ui.data_views import (
    _render_explain_tab,
    _render_history_tab,
    _render_metrics_tab,
    _render_search_tab,
)
from app.ui.flashcards_ui import _render_flashcards_tab
from app.ui.interactive_quiz import _render_interactive_quiz_tab
from app.ui.living_konspekt_view import render_living_konspekt_view as _render_living_konspekt_view
from app.ui.print_view import render_print_view as _render_print_view
from app.ui.topics_tab import render_topics_tab as _render_topics_tab
from app.ui.tutor_chat import _render_tutor_chat_tab


@st.fragment
def _fragment_tutor_chat_tab() -> None:
    _render_tutor_chat_tab()


def _fragment_flashcards_tab() -> None:
    # Без @st.fragment: частичный rerun ломал связку виджетов (radio раздела) с сессией
    # после нескольких оценок подряд (см. flashcards_main_section).
    _render_flashcards_tab()


@st.fragment
def _fragment_interactive_quiz_tab() -> None:
    _render_interactive_quiz_tab()


def _fragment_knowledge_graph_tab() -> None:
    # Без @st.fragment: kg_d3 custom component + _kgc-bridge требуют полного rerun;
    # partial fragment rerun не поднимает selected_concept до selectbox ниже графа.
    _render_knowledge_graph_tab()


@st.fragment
def _fragment_living_konspekt_tab() -> None:
    _render_living_konspekt_view()


@st.fragment
def _fragment_learning_progress_tab() -> None:
    _render_learning_progress_tab()


def _fragment_history_tab() -> None:
    # Без @st.fragment: smoke `home_mode_selection` должен видеть заголовок «История вопросов»
    # сразу после `?e2e_view=history`; отложенный fragment-run оставлял панель пустой в e2e.
    _render_history_tab()


@st.fragment
def _fragment_topics_tab() -> None:
    stats = st.session_state.get("_ui_index_stats_tab")
    _render_topics_tab(stats)


@st.fragment
def _fragment_metrics_tab() -> None:
    _render_metrics_tab()


@st.fragment
def _fragment_search_tab() -> None:
    _render_search_tab()


@st.fragment
def _fragment_explain_tab() -> None:
    _render_explain_tab()


@st.fragment
def _fragment_print_view() -> None:
    _render_print_view()
