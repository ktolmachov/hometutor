"""Home RAG Tutor — main UI entry point (thin router).

All tab/panel implementations live in dedicated modules under app/ui/:
  tutor_chat, interactive_quiz, dashboards, data_views, home_hub, fragments.
This file wires up page config, session init, sidebar, hero, and view dispatch.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

logger = logging.getLogger(__name__)

from app import user_state
from app.config import get_settings
from app.otel_tracing import init_otel_if_enabled
from app.ui.analytics import inject_yandex_metrika
from app.ui.auth_gate import require_ui_auth_or_stop
from app.session_tape import ensure_session_started
from app.ui.config_env_banner import render_config_env_banner as _render_config_env_banner
from app.ui.offline_banner import render_offline_banner as _render_offline_banner
from app.ui.quick_answer import render_quick_answer_tab as _render_quick_answer_tab
from app.ui.adaptive_plan_card import render_adaptive_daily_plan, render_adaptive_plan_hub
from app.ui.breadcrumb import HOME_VIEW, render_back_to_home
from app.ui.mission_control import render_mission_control
from app.ui.session_state import (
    PENDING_CURRENT_VIEW_KEY,
    hydrate_tutor_goal_snapshot_once as _hydrate_tutor_goal_snapshot_once,
    hydrate_tutor_mastery_from_db as _hydrate_tutor_mastery_from_db,
    init_state as _init_state,
)
from app.ui.sidebar import render_sidebar as _render_sidebar
from app.ui.streamlit_activity import touch_streamlit_session as _touch_streamlit_session
from app.ui.styles import inject_styles as _inject_styles
from app.ui.tutorial_guide import (
    hydrate_tutorial_progress_once as _hydrate_tutorial_progress_once,
    render_tutorial_overlay as _render_tutorial_overlay,
    start_tutorial as _start_tutorial,
)
from app.ui.study_scope import activate_scope as _activate_scope
from app.ui.study_scope import deactivate_scope as _deactivate_scope
from app.ui.study_scope import get_active_scope as _get_active_scope
from app.ui.llm_local_banner import render_latency_budget_banner, render_llm_local_banner
from app.ui_client import load_index_stats, load_ui_bootstrap

# --- Extracted module imports ---
from app.ui.home_hub import _render_onboarding
from app.ui.fragments import (
    _fragment_explain_tab,
    _fragment_flashcards_tab,
    _fragment_history_tab,
    _fragment_interactive_quiz_tab,
    _fragment_knowledge_graph_tab,
    _fragment_learning_progress_tab,
    _fragment_living_konspekt_tab,
    _fragment_metrics_tab,
    _fragment_print_view,
    _fragment_search_tab,
    _fragment_topics_tab,
    _fragment_tutor_chat_tab,
)


# ---------------------------------------------------------------------------
# NOTE: most retrieval paths use the HTTP API, but tutor chat still runs
# query_service in a Streamlit worker thread. Initialize only lightweight OTEL
# here; model services remain owned by their existing call paths.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Page config, init, hero, sidebar, view router
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Home RAG Tutor", page_icon="🎓", layout="wide")
inject_yandex_metrika()
init_otel_if_enabled()
_inject_styles()
_render_offline_banner()
_render_config_env_banner()
_init_state()
require_ui_auth_or_stop()
_touch_streamlit_session()
_hydrate_tutor_mastery_from_db()
_hydrate_tutor_goal_snapshot_once()
_hydrate_tutorial_progress_once()


@st.dialog("Начало работы")
def _render_onboarding_dialog() -> None:
    _render_onboarding()


try:
    if user_state.get_kv("onboarding_v1_done") != "1":
        _render_onboarding_dialog()
except Exception as e:  # noqa: BLE001 - onboarding check failure is non-fatal during startup
    logger.debug("Onboarding check failed, skipping: %s", e)
_ui_boot = load_ui_bootstrap()
if _ui_boot and isinstance(_ui_boot.get("index_stats"), dict):
    index_stats = _ui_boot["index_stats"]
    if _ui_boot.get("topics") is not None:
        st.session_state["topics_catalog"] = _ui_boot["topics"]
    _kb_hero = _ui_boot.get("kb_overview")
else:
    index_stats = load_index_stats()
    _kb_hero = None
render_llm_local_banner(_ui_boot)
render_latency_budget_banner()
st.session_state["_ui_index_stats_tab"] = index_stats
folder, folder_rel, file_name, relative_path, topic_quick, folder_quick = _render_sidebar(index_stats)
_settings_cockpit = get_settings()
if _settings_cockpit.home_rag_e2e_offline:
    _e2e_tour_start = str(st.query_params.get("e2e_tour_start") or "").lower()
    _e2e_tour_resume = str(st.query_params.get("e2e_tour_resume") or "").lower()
    if _e2e_tour_start in {"1", "true", "yes"}:
        _start_tutorial(0)
    elif _e2e_tour_resume in {"1", "true", "yes"}:
        st.session_state["tutorial_active"] = True
    _e2e_tour_chapter = str(st.query_params.get("e2e_tour_chapter") or "").strip()
    _e2e_tour_step = str(st.query_params.get("e2e_tour_step") or "").strip()
    if _e2e_tour_chapter or _e2e_tour_step:
        st.session_state["tutorial_active"] = True
        if _e2e_tour_chapter.isdigit():
            st.session_state["tutorial_chapter_index"] = max(0, int(_e2e_tour_chapter))
        if _e2e_tour_step.isdigit():
            st.session_state["tutorial_step_index"] = max(0, int(_e2e_tour_step))
_render_tutorial_overlay()
view_options = [
    HOME_VIEW,
    "Быстрый ответ",
    "Чат с тьютором",
    "Интерактивный Quiz",
    "Flashcards",
    "Курс",
    "Адаптивный план",
    "Knowledge Graph",
    "Живой конспект",
    "Прогресс обучения",
    "История",
    "Темы",
    "Метрики",
    "Найти материалы",
    "Объяснить файл",
    "Чистый вид",
]

_e2e_view_map = {
    "home": HOME_VIEW,
    "mission_control": HOME_VIEW,
    "kg": "Knowledge Graph",
    "knowledge_graph": "Knowledge Graph",
    "living_konspekt": "Живой конспект",
    "qa": "Быстрый ответ",
    "quick_answer": "Быстрый ответ",
    "tutor": "Чат с тьютором",
    "quiz": "Интерактивный Quiz",
    "flashcards": "Flashcards",
    "course": "Курс",
    "adaptive_plan": "Адаптивный план",
    "progress": "Прогресс обучения",
    "history": "История",
    "topics": "Темы",
    "metrics": "Метрики",
    "search": "Найти материалы",
    "explain": "Объяснить файл",
    "print": "Чистый вид",
}
_e2e_fc_section_map = {
    "decks": "decks",
    "create": "create",
    "review": "review",
}
_e2e_fc_source_map = {
    "document": "📄 Документ из базы знаний",
    "upload": "📤 Загрузить файл",
}

def _qp_first_str(name: str) -> str:
    raw = st.query_params.get(name)
    if raw is None:
        return ""
    if isinstance(raw, list):
        if not raw:
            return ""
        return str(raw[0]).strip()
    return str(raw).strip()


_e2e_fc_section_raw = _qp_first_str("e2e_fc_section").lower()
_e2e_fc_section = _e2e_fc_section_map.get(_e2e_fc_section_raw)
if _e2e_fc_section:
    st.session_state["flashcards_section_pending"] = _e2e_fc_section
    st.session_state["flashcards_main_section"] = _e2e_fc_section

_e2e_fc_source_raw = _qp_first_str("e2e_fc_source").lower()
_e2e_fc_source = _e2e_fc_source_map.get(_e2e_fc_source_raw)
if _e2e_fc_source:
    st.session_state["fc_source_mode"] = _e2e_fc_source

_e2e_scope_clear = _qp_first_str("e2e_scope_clear")
if _e2e_scope_clear in ("1", "true", "yes"):
    _deactivate_scope()
_e2e_scope_folder = _qp_first_str("e2e_scope_folder")
if _e2e_scope_folder:
    _e2e_scope_title = _qp_first_str("e2e_scope_title") or f"Курс: {_e2e_scope_folder}"
    _e2e_scope_paths_raw = _qp_first_str("e2e_scope_paths")
    _e2e_scope_paths = [path.strip() for path in _e2e_scope_paths_raw.split(",") if path.strip()]
    _activate_scope(
        folder_rel=_e2e_scope_folder,
        title=_e2e_scope_title,
        source_paths=_e2e_scope_paths,
    )
_active_scope = st.session_state.get("active_study_scope")
if isinstance(_active_scope, dict) and _active_scope.get("active"):
    _scope_folder_rel = str(_active_scope.get("folder_rel") or "")
    st.markdown(f'<div data-testid="e2e-active-scope">{_scope_folder_rel}</div>', unsafe_allow_html=True)
else:
    st.markdown('<div data-testid="e2e-active-scope"></div>', unsafe_allow_html=True)

_view_nav_labels = {
    HOME_VIEW: "Главная — Mission Control",
    "Быстрый ответ": "База знаний — Быстрый ответ",
    "Чат с тьютором": "Обучение — Чат с тьютором",
    "Интерактивный Quiz": "Обучение — Интерактивный Quiz",
    "Flashcards": "Обучение — Flashcards (интервальное повторение)",
    "Курс": "Обучение — Курс",
    "Адаптивный план": "Обучение — Адаптивный план",
    "Прогресс обучения": "Обучение — Прогресс обучения",
    "Темы": "База знаний — Темы",
    "Найти материалы": "База знаний — Поиск по материалам",
    "Объяснить файл": "База знаний — Объяснить файл",
    "Knowledge Graph": "Ещё — Knowledge Graph",
    "Живой конспект": "База знаний — Живой конспект",
    "История": "Ещё — История",
    "Метрики": "Ещё — Метрики",
    "Чистый вид": "Ещё — Чистый вид",
}
if st.session_state["current_view"] not in view_options:
    st.session_state["current_view"] = view_options[0]

# Deep-link раздела: применяем после верхнего UI (hero/mode), чтобы e2e не перебивался колбэками того же run.
_e2e_target_view = _e2e_view_map.get(_qp_first_str("e2e_view").lower())
if _e2e_target_view in view_options:
    st.session_state["current_view"] = _e2e_target_view

# Flashcard → Tutor handoff navigation (deferred from flashcards_review_view to avoid widget key conflict)
if st.session_state.pop("_request_navigate_to_tutor", False):
    st.session_state["current_view"] = "Чат с тьютором"

# Mission Control / Smart Study: отложенная смена раздела до инстанцирования selectbox.
_pending_nav_view = st.session_state.pop(PENDING_CURRENT_VIEW_KEY, None)
if isinstance(_pending_nav_view, str):
    _pending_mapped = _e2e_view_map.get(_pending_nav_view.strip().lower())
    if _pending_mapped:
        _pending_nav_view = _pending_mapped
if _pending_nav_view in view_options:
    st.session_state["current_view"] = _pending_nav_view

st.markdown('<div data-testid="e2e-view-switcher"></div>', unsafe_allow_html=True)
selected_view = st.selectbox(
    "Раздел",
    view_options,
    format_func=lambda v: _view_nav_labels.get(v, v),
    key="current_view",
    label_visibility="collapsed",
)
_session_tape_id = str(st.session_state.get("_session_tape_id") or "").strip()
if _session_tape_id and get_settings().session_tape_full_events_enabled:
    ensure_session_started(
        _session_tape_id,
        entry_surface=str(selected_view),
        surface="streamlit",
    )
if selected_view != HOME_VIEW:
    render_back_to_home()

if selected_view == HOME_VIEW:
    from app.ui.e2e_demo_scenes import render_e2e_demo_scene_for_view

    # Mission Control SSR: см. app/ui/mission_control.py — баннер primary + текст «почему не тьютор/quiz/карточки/прогресс»
    render_mission_control(index_stats)
    render_e2e_demo_scene_for_view(selected_view)
elif selected_view == "Быстрый ответ":
    _render_quick_answer_tab(folder, folder_rel, file_name, relative_path, topic_quick, folder_quick)
elif selected_view == "Чат с тьютором":
    _fragment_tutor_chat_tab()
elif selected_view == "Интерактивный Quiz":
    _fragment_interactive_quiz_tab()
elif selected_view == "Flashcards":
    _fragment_flashcards_tab()
elif selected_view == "Курс":
    from app.ui.e2e_demo_scenes import e2e_cockpit_enabled, render_e2e_demo_scene_for_view

    _scope_course = _get_active_scope()
    render_e2e_demo_scene_for_view(selected_view)
    if e2e_cockpit_enabled(_settings_cockpit) and _scope_course:
        from app.ui.course_cockpit import render_course_cockpit_scaffold

        st.session_state["course_cockpit_active"] = True
        render_course_cockpit_scaffold()
    else:
        st.info("Активируйте курс на Mission Control или во вкладке «Темы».")
elif selected_view == "Адаптивный план":
    render_adaptive_plan_hub(key_prefix="adaptive_plan_view_hub")
    render_adaptive_daily_plan(key_prefix="adaptive_plan_view_daily")
elif selected_view == "Knowledge Graph":
    from app.ui.e2e_demo_scenes import render_e2e_demo_scene_for_view

    render_e2e_demo_scene_for_view(selected_view)
    _fragment_knowledge_graph_tab()
elif selected_view == "Живой конспект":
    _fragment_living_konspekt_tab()
elif selected_view == "Прогресс обучения":
    from app.ui.e2e_demo_scenes import render_e2e_demo_scene_for_view

    try:
        from app.ui.resume_cards import render_smart_study_router_for_progress_tab

        _ix_stats_pr = st.session_state.get("_ui_index_stats_tab")
        render_smart_study_router_for_progress_tab(
            index_stats=_ix_stats_pr if isinstance(_ix_stats_pr, dict) else None,
        )
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("progress smart study router: %s", _exc)
    render_e2e_demo_scene_for_view(selected_view)
    _fragment_learning_progress_tab()
elif selected_view == "История":
    _fragment_history_tab()
elif selected_view == "Темы":
    _fragment_topics_tab()
elif selected_view == "Метрики":
    _fragment_metrics_tab()
elif selected_view == "Найти материалы":
    _fragment_search_tab()
elif selected_view == "Объяснить файл":
    _fragment_explain_tab()
else:
    _fragment_print_view()

if get_settings().home_rag_e2e_offline:
    st.markdown('<div data-testid="e2e-streamlit-ready"></div>', unsafe_allow_html=True)
