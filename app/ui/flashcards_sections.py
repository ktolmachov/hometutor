"""Section navigation helpers for Flashcards hub."""

from __future__ import annotations

from typing import Any

import streamlit as st

FC_MAIN_SECTION_DECKS = "decks"
FC_MAIN_SECTION_CREATE = "create"
FC_MAIN_SECTION_REVIEW = "review"

_FLASHCARDS_SECTION_PENDING_KEY = "flashcards_section_pending"
_E2E_FC_SECTION_QUERY_KEY = "e2e_fc_section"
_E2E_FC_SOURCE_QUERY_KEY = "e2e_fc_source"

FC_SOURCE_DOCUMENT_LABEL = "📄 Документ из базы знаний"
FC_SOURCE_COURSE_LABEL = "📚 Активный курс"
FC_SOURCE_UPLOAD_LABEL = "📤 Загрузить файл"


def apply_pending_flashcards_section() -> None:
    pending = st.session_state.pop(_FLASHCARDS_SECTION_PENDING_KEY, None)
    if pending in (FC_MAIN_SECTION_DECKS, FC_MAIN_SECTION_CREATE, FC_MAIN_SECTION_REVIEW):
        st.session_state["flashcards_main_section"] = pending


def set_flashcards_section(section: str) -> None:
    if section not in (FC_MAIN_SECTION_DECKS, FC_MAIN_SECTION_CREATE, FC_MAIN_SECTION_REVIEW):
        return
    st.session_state[_FLASHCARDS_SECTION_PENDING_KEY] = section
    st.rerun()


def query_param_str(name: str) -> str:
    raw = st.query_params.get(name)
    if raw is None:
        return ""
    if isinstance(raw, list):
        if not raw:
            return ""
        return str(raw[0]).strip()
    return str(raw).strip()


def apply_e2e_section_override() -> None:
    section_map = {
        "decks": FC_MAIN_SECTION_DECKS,
        "create": FC_MAIN_SECTION_CREATE,
        "review": FC_MAIN_SECTION_REVIEW,
    }
    requested = section_map.get(query_param_str(_E2E_FC_SECTION_QUERY_KEY).lower())
    if not requested:
        return
    if st.session_state.get("flashcards_main_section") == requested:
        return
    st.session_state[_FLASHCARDS_SECTION_PENDING_KEY] = requested
    st.session_state["flashcards_main_section"] = requested
    st.rerun()


def apply_e2e_source_override() -> None:
    source_map = {
        "document": FC_SOURCE_DOCUMENT_LABEL,
        "course": FC_SOURCE_COURSE_LABEL,
        "upload": FC_SOURCE_UPLOAD_LABEL,
    }
    requested = source_map.get(query_param_str(_E2E_FC_SOURCE_QUERY_KEY).lower())
    if not requested:
        return
    if st.session_state.get("fc_source_mode") == requested:
        return
    st.session_state["fc_source_mode"] = requested
    st.rerun()


def pending_section_key() -> str:
    return _FLASHCARDS_SECTION_PENDING_KEY


def e2e_source_labels() -> tuple[str, str]:
    return FC_SOURCE_DOCUMENT_LABEL, FC_SOURCE_UPLOAD_LABEL


def section_order_and_labels() -> tuple[list[str], dict[str, str]]:
    order = [FC_MAIN_SECTION_DECKS, FC_MAIN_SECTION_CREATE, FC_MAIN_SECTION_REVIEW]
    labels = {
        FC_MAIN_SECTION_DECKS: "🗂 Мои колоды",
        FC_MAIN_SECTION_CREATE: "✨ Создать новые",
        FC_MAIN_SECTION_REVIEW: "🔁 Повторение",
    }
    return order, labels


def build_section_context() -> dict[str, Any]:
    """Small helper for dependency injection in section views."""
    return {
        "pending_key": _FLASHCARDS_SECTION_PENDING_KEY,
        "source_document_label": FC_SOURCE_DOCUMENT_LABEL,
        "source_course_label": FC_SOURCE_COURSE_LABEL,
        "source_upload_label": FC_SOURCE_UPLOAD_LABEL,
    }
