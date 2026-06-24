"""Action helpers for tutor chat UI."""

from __future__ import annotations

import logging

import streamlit as st

DEEPEN_WITH_SOURCES_CTA = "Углубить по источникам"


def build_deepen_with_sources_prompt(card_question: str | None = None) -> str:
    topic = " ".join(str(card_question or "").split()).strip()
    if topic:
        return (
            f"Углуби объяснение по источникам базы знаний для карточки: «{topic}». "
            "Проверь найденные фрагменты, явно отдели то, что подтверждено источниками, "
            "и дай один короткий пример."
        )
    return (
        "Углуби последнее объяснение по источникам базы знаний. "
        "Проверь найденные фрагменты, явно отдели то, что подтверждено источниками, "
        "и дай один короткий пример."
    )


def _last_user_question_for_message(session_id: str, msg_idx: int) -> str:
    from app.session_store import session_store

    messages = session_store.get(session_id)
    upper = min(max(0, int(msg_idx)), len(messages) - 1)
    for i in range(upper, -1, -1):
        msg = messages[i]
        if getattr(msg, "role", None) != "user":
            continue
        text = str(getattr(msg, "content", "") or "").strip()
        if text:
            return text
    return ""


def handle_tutor_cta_click(action: str, session_id: str, msg_idx: int) -> None:
    """CTA: micro-quiz launch or pending tutor prompt."""
    act = (action or "").strip()
    try:
        from app.ui_events import track_cta_click, track_micro_quiz_started

        track_cta_click(act)
        if act == "Проверь меня":
            track_micro_quiz_started()
    except Exception as exc:  # noqa: BLE001 - non-critical UI telemetry.
        logging.getLogger(__name__).debug("UI event tracking failed: %s", exc)

    if act == "Проверь меня":
        st.session_state["tutor_micro_quiz_start"] = {
            "sid": session_id,
            "msg_idx": int(msg_idx),
        }
        st.rerun()
        return
    if act == "Пора повторить":
        st.session_state["tutor_pending_prompt"] = (
            "Какие темы из очереди повторений сейчас наиболее приоритетны и как их быстро повторить?"
        )
        st.session_state["tutor_pending_session_id"] = session_id
        st.rerun()
        return
    if act == DEEPEN_WITH_SOURCES_CTA:
        st.session_state["tutor_pending_prompt"] = build_deepen_with_sources_prompt(
            _last_user_question_for_message(session_id, msg_idx)
        )
        st.session_state["tutor_pending_session_id"] = session_id
        st.rerun()
        return
    st.session_state["tutor_pending_prompt"] = act
    st.session_state["tutor_pending_session_id"] = session_id
    st.rerun()


def micro_quiz_letter_from_choice(choice: str, options: list[str]) -> str:
    c = (choice or "").strip()
    for i, opt in enumerate(options):
        if opt.strip() == c and 0 <= i <= 3:
            return "ABCD"[i]
    ch = c[:1].upper()
    return ch if ch in "ABCD" else ""


def micro_quiz_status_ru(status: str | None) -> str:
    """US-5.1: clear status label for micro-quiz."""
    s = str(status or "").strip().lower()
    return {"correct": "Верно", "incorrect": "Неверно", "partial": "Частично"}.get(s, s or "—")
