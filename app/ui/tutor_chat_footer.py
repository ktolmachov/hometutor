"""Footer and export components for tutor chat UI."""

from __future__ import annotations

import json
import uuid
from typing import Any

import streamlit as st

from app.tutor_orchestrator import build_redacted_tutor_expert_snapshot
from app.ui.continuity_bridge import tutor_back_to_flashcards_ru, tutor_expert_controls_intro_ru
from app.ui.expert_controls import render_expert_controls


def render_tutor_chat_exports(session_id: str, history: list[Any]) -> None:
    """Render export buttons (Markdown, Anki TSV)."""
    
    def _md_export(msgs) -> str:
        parts = []
        for m in msgs:
            role = "Пользователь" if m.role == "user" else "Ассистент"
            parts.append(f"## {role}\n\n{m.content}\n")
        return "\n".join(parts)

    def _anki_tsv(msgs) -> str:
        lines = ["front\tback"]
        i = 0
        arr = list(msgs)
        while i < len(arr) - 1:
            if arr[i].role == "user" and arr[i + 1].role == "assistant":
                q = str(arr[i].content).replace("\t", " ").replace("\n", " ")
                a = str(arr[i + 1].content).replace("\t", " ").replace("\n", " ")
                lines.append(f"{q}\t{a}")
                i += 2
            else:
                i += 1
        return "\n".join(lines)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Экспорт Markdown",
            _md_export(history),
            file_name=f"chat_{session_id[:8]}.md",
            mime="text/markdown",
            key="tutor_export_md",
            width='stretch',
        )
    with c2:
        st.download_button(
            "Anki TSV",
            _anki_tsv(history),
            file_name=f"chat_{session_id[:8]}_anki.tsv",
            mime="text/tab-separated-values",
            key="tutor_export_anki",
            width='stretch',
        )


def _last_tutor_meta_from_messages(history: list[Any]) -> dict[str, Any] | None:
    for msg in reversed(history):
        if getattr(msg, "role", None) != "assistant":
            continue
        meta = getattr(msg, "metadata", None) or {}
        if not isinstance(meta, dict):
            continue
        tutor_m = meta.get("tutor")
        if isinstance(tutor_m, dict) and tutor_m:
            return tutor_m
    return None


def _render_tutor_expert_policy_panel(session_id: str, history: list[Any]) -> None:
    tutor_meta = _last_tutor_meta_from_messages(history)
    snap = build_redacted_tutor_expert_snapshot(tutor_meta)
    with st.expander("Эксперт: policy / оркестрация (без сырья промпта)", expanded=False):
        st.caption(
            "Последний ответ ассистента: компактный снимок решения. Полные промпты и ключи не отображаются."
        )
        st.json(snap)
        payload = json.dumps(snap, ensure_ascii=False, indent=2)
        st.download_button(
            "Скачать JSON диагностики",
            payload,
            file_name=f"tutor_expert_{session_id[:8]}.json",
            mime="application/json",
            key=f"tutor_expert_diag_dl_{session_id[:8]}",
            width="stretch",
        )


def _render_tutor_expert_session_reset(session_id: str) -> None:
    st.markdown("##### Эксперт: сброс сессии")
    confirm = st.checkbox(
        "Понимаю, что сообщения этой беседы будут удалены локально",
        key=f"tutor_expert_reset_ok_{session_id[:8]}",
    )
    from app.session_store import session_store

    if (
        st.button(
            "Сбросить текущий чат",
            key=f"tutor_expert_reset_btn_{session_id[:8]}",
            width="stretch",
            type="secondary",
            disabled=not confirm,
        )
        and session_store is not None
    ):
        session_store.delete(session_id)
        new_id = str(uuid.uuid4())
        st.session_state["tutor_session_id"] = new_id
        for k in (
            "tutor_last_nba",
            "tutor_last_graph",
            "tutor_micro_quiz_active",
            "tutor_show_quiz_tpl",
            "tutor_pending_prompt",
            "tutor_pending_session_id",
        ):
            st.session_state.pop(k, None)
        st.success("Сессия очищена. Открыт новый пустой чат.")
        st.rerun()


def render_tutor_chat_footer(session_id: str, sessions_count: int, concepts_count: int) -> None:
    """Render small informational caption at the bottom."""
    topic = str(st.session_state.get("current_topic") or "не задана")
    subtopic = str(st.session_state.get("tutor_goal_subtopic") or "").strip()
    desired_outcome = str(st.session_state.get("tutor_goal_desired_outcome") or "").strip()
    time_budget = st.session_state.get("tutor_goal_time_budget_min")
    context_origin = "Flashcards" if st.session_state.get("flashcard_review_return") else "обычная tutor-сессия"
    if st.session_state.get("qa_to_tutor_context"):
        context_origin = "Быстрый ответ"
    signals = [f"источник: {context_origin}", f"тема: {topic[:80]}"]
    if subtopic:
        signals.append(f"фокус: {subtopic[:80]}")
    if desired_outcome:
        signals.append(f"цель: {desired_outcome[:80]}")
    if time_budget:
        signals.append(f"бюджет: {time_budget} мин")
    render_expert_controls(
        intro=tutor_expert_controls_intro_ru(),
        metrics=(
            ("Сессия", f"{session_id[:8]}…", "активный чат"),
            ("Чатов", str(sessions_count), "в базе"),
            ("Концептов", str(concepts_count), "в графе"),
        ),
        signals=signals,
        safe_actions=(
            "Экспорт Markdown и Anki TSV доступен в блоке экспорта выше.",
            "Возврат во Flashcards доступен только для handoff из карточки.",
        ),
    )
    try:
        from app.session_store import session_store as _ss

        hist = list(_ss.get(session_id)) if _ss is not None else []
    except Exception:  # noqa: BLE001
        hist = []
    _render_tutor_expert_policy_panel(session_id, hist)
    _render_tutor_expert_session_reset(session_id)
    if st.session_state.get("flashcard_review_return"):
        if st.button(tutor_back_to_flashcards_ru(), key="tutor_back_to_flashcards", width="stretch", type="secondary"):
            from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

            st.session_state[PENDING_CURRENT_VIEW_KEY] = "Flashcards"
            st.session_state["flashcards_main_section"] = "review"
            st.session_state["flashcards_section_pending"] = "review"
            st.session_state["flashcard_review_return"] = False
            st.rerun()
    # W9: technical counters only in diagnostic/expert layer (not permanent footer chrome).
    try:
        from app.ui_preferences import get_ui_level

        if get_ui_level() == "diagnostic":
            st.caption(
                f"Сессия: {session_id[:8]}… · чатов в базе: {sessions_count} · "
                f"концептов в графе: {concepts_count}"
            )
    except Exception:  # noqa: BLE001 - footer must not fail on preferences
        pass
