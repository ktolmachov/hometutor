"""Mapping from 7 calm learner intents to existing executors (#23 P0-2 A2).

Each intent: closeable palette entry → screen-reader label, existing handler, return point.
No new write-actions or LLM; intents reuse existing navigation / prompt builders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import streamlit as st

from app.ui.session_state import PENDING_CURRENT_VIEW_KEY


@dataclass(frozen=True)
class LearningIntent:
    intent_id: str
    label_ru: str
    sr_label: str
    icon: str


INTENTS: tuple[LearningIntent, ...] = (
    LearningIntent("simpler", "Объясни проще", "Попросить тьютора объяснить тему проще", "💡"),
    LearningIntent("practice", "Хочу практику", "Получить упражнение по теме", "🏋️"),
    LearningIntent("check_me", "Проверь меня", "Короткая проверка знаний по теме", "✅"),
    LearningIntent("remember", "Помоги запомнить", "Создать карточки для запоминания темы", "🧠"),
    LearningIntent("plan", "Составь план", "Построить учебный маршрут по теме", "📋"),
    LearningIntent("what_next", "Что дальше", "Предложить следующую тему для изучения", "🔜"),
    LearningIntent("didnt_get", "Не понял", "Разобрать непонятную тему шаг за шагом", "🤔"),
)


_HOME_VIEW = "Mission Control"


def _tutor_setup() -> None:
    """Common tutor intent setup: session + pending id."""
    from app.ui import adaptive_plan_card as _card

    _card._ensure_tutor_session_local()
    st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")


def _set_breadcrumb(origin: str | None) -> None:
    """Set home_breadcrumb_origin for back-to-home navigation."""
    st.session_state["home_breadcrumb_origin"] = origin if origin else _HOME_VIEW


def apply_learning_intent(
    intent_id: str,
    *,
    topic_hint: str | None = None,
    return_view: str | None = None,
) -> None:
    """Execute the intent via existing handlers; returns by setting session state for navigation."""
    topic = str(topic_hint or "").strip() or None

    _set_breadcrumb(return_view)

    if intent_id == "simpler":
        _tutor_setup()
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
        st.session_state["tutor_pending_prompt"] = (
            f"Объясни тему «{topic or 'текущую'}» проще и нагляднее: "
            "коротко, с примером, без сложных терминов."
        )
        st.session_state["tutor_cta_action"] = "learning_intent_simpler"
        st.session_state["current_topic"] = topic or ""
    elif intent_id == "practice":
        _tutor_setup()
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
        st.session_state["tutor_pending_prompt"] = (
            f"Дай одно практическое упражнение по теме «{topic or 'текущей'}»: "
            "задача с короткой проверкой решения."
        )
        st.session_state["tutor_cta_action"] = "learning_intent_practice"
        st.session_state["current_topic"] = topic or ""

    elif intent_id == "check_me":
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Интерактивный Quiz"
        if topic:
            st.session_state["quiz_topic_hint"] = topic
        st.session_state["tutor_cta_action"] = "learning_intent_check"

    elif intent_id == "remember":
        from app.ui.flashcards_sections import FC_MAIN_SECTION_CREATE, set_flashcards_section

        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Flashcards"
        st.session_state["flashcards_subview"] = "decks"
        st.session_state["tutor_cta_action"] = "learning_intent_remember"
        if topic:
            st.session_state["fc_create_topic_hint"] = topic
        _emit_intent_selected(intent_id)
        set_flashcards_section(FC_MAIN_SECTION_CREATE)
        return

    elif intent_id == "plan":
        _tutor_setup()
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
        st.session_state["tutor_pending_prompt"] = (
            f"Составь короткий учебный план по теме «{topic or 'текущей'}»: "
            "3-5 шагов с приоритетами."
        )
        st.session_state["tutor_cta_action"] = "learning_intent_plan"
        st.session_state["current_topic"] = topic or ""

    elif intent_id == "what_next":
        _tutor_setup()
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
        st.session_state["tutor_pending_prompt"] = (
            "Что мне стоит изучить дальше, исходя из текущего прогресса? "
            "Предложи одну следующую тему и обоснуй."
        )
        st.session_state["tutor_cta_action"] = "learning_intent_what_next"
        st.session_state["current_topic"] = topic or ""

    elif intent_id == "didnt_get":
        _tutor_setup()
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
        st.session_state["tutor_pending_prompt"] = (
            f"Разбери тему «{topic or 'текущую'}» по шагам: начни с самого простого, "
            "проверяй понимание на каждом шаге."
        )
        st.session_state["tutor_cta_action"] = "learning_intent_didnt_get"
        st.session_state["current_topic"] = topic or ""

    _emit_intent_selected(intent_id)
    st.rerun()


def _emit_intent_selected(intent_id: str) -> None:
    """Emit session-tape intent_selected (privacy-safe: only intent_id)."""
    try:
        from app.session_tape import append_event

        sid = str(st.session_state.get("_session_tape_id") or "").strip()
        if not sid:
            return
        append_event(sid, "intent_selected", {
            "intent_id": intent_id,
        })
    except Exception:  # noqa: BLE001 - tape must never block navigation
        pass
