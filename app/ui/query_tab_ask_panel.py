"""Левая колонка: ввод вопроса и запрос ответа (P5c split)."""

from __future__ import annotations

import streamlit as st

from app.guardrails import InputGuardrailError
from app.input_validation import prepare_ask_request
from app.ui.answer_helpers import source_paths_from_answer
from app.ui.constants import (
    MAX_HISTORY,
    SUGGESTED_QUESTIONS,
    _SIDEBAR_FILTER_FOLDER_ALL,
    _SIDEBAR_FILTER_TOPIC_ALL,
)
from app.ui.continuity_bridge import course_scope_chip_ru, qa_fast_answer_question_placeholder_ru
from app.ui.helpers import ask_failure_recovery_hint_from_exception, format_request_error
from app.ui.latency_budget_sync import sync_latency_budget_from_debug
from app.ui.qa_wait_ux import (
    answer_qualifies_for_fast_success_reinforcement,
    fast_success_reinforcement_phrase,
    wait_runway_message_for_question,
)
from app.ui.query_tab_helpers import first_answer_examples
from app.ui.seed_questions import render_seed_question_chips
from app.ui.session_state import set_last_studied_document
from app.ui.study_scope import apply_scope_folder_rel, get_active_scope
from app.ui.widgets import render_chip_row
from app.ui.preflight import render_preflight_card
from app.ui_client import fetch_json, post_knowledge_workflow


def _set_seed_question_for_quick_answer(question: str) -> None:
    st.session_state["question_draft"] = str(question or "").strip()
    st.rerun()


def render_query_ask_panel(
    folder: str,
    folder_rel: str,
    file_name: str,
    relative_path: str,
    topic_quick: str,
    folder_quick: str,
) -> None:
    st.markdown(
        '<div class="step-strip"><span class="step-item"><strong>1.</strong> Сформулируйте вопрос</span><span class="step-item"><strong>2.</strong> При необходимости ограничьте область</span><span class="step-item"><strong>3.</strong> Изучите ответ и источники</span></div>',
        unsafe_allow_html=True,
    )
    render_preflight_card(quiet_ok=True)
    empty_question_state = not st.session_state.get("last_answer") and not str(st.session_state.get("question_draft") or "").strip()
    if empty_question_state and render_seed_question_chips(
        key_prefix="quick_answer_empty",
        navigate_to_question=_set_seed_question_for_quick_answer,
    ):
        pass
    else:
        st.markdown("#### Быстрый старт")
        qcols = st.columns(2)
        hero_examples = first_answer_examples(
            SUGGESTED_QUESTIONS,
            has_index_content=True,
        )
        for idx, suggestion in enumerate(hero_examples):
            with qcols[idx % 2]:
                if st.button(suggestion, key=f"suggest_{idx}", width="stretch", type="secondary"):
                    st.session_state["question_draft"] = suggestion
                    st.rerun()
    question = st.text_area(
        "Вопрос",
        height=170,
        key="question_draft",
        placeholder=qa_fast_answer_question_placeholder_ru(),
    )
    homework_mode = st.toggle(
        "Помощь с ДЗ",
        value=False,
        help="Включите, если хотите получить помощь по домашнему заданию с контролем глубины ответа.",
        key="homework_mode",
    )
    study_mode = st.toggle(
        "Продолжить по последнему ответу",
        value=False,
        help="Использует последний вопрос и ответ как контекст для follow-up запросов.",
        key="study_mode",
    )
    if homework_mode:
        st.caption(
            "Помощь с ДЗ: намёк, план решения, разбор ошибки или полное решение. "
            "Если нужен полноценный учебный диалог, лучше перейти в **чат с тьютором**; этот переключатель нужен для разового Q&A."
        )
    if study_mode:
        st.caption(
            "Продолжить по последнему ответу: новый ответ будет учитывать предыдущий вопрос и ответ, "
            "поэтому режим удобен для «объясни проще» и «приведи пример»."
        )
    if not homework_mode and not study_mode:
        st.caption("Оставьте оба переключателя выключенными для обычного поиска ответа по базе знаний.")
    assistance_level = "hint"
    if homework_mode:
        assistance_level = st.radio(
            "Уровень помощи",
            options=["hint", "plan", "error_review", "full_solution"],
            format_func=lambda value: {
                "hint": "Намек",
                "plan": "План решения",
                "error_review": "Разбор ошибки",
                "full_solution": "Полное решение",
            }.get(value, value),
            horizontal=True,
            key="homework_level",
        )
        st.caption(
            "Для самостоятельной работы обычно лучше начинать с мягких уровней помощи: `Намёк` или `План решения`."
        )
    study_scope = get_active_scope()
    if study_scope:
        scope_title = study_scope.get("title") or study_scope.get("folder_rel") or "Курс"
        st.info(course_scope_chip_ru(scope_title), icon=None)

    active_scope = []
    if folder:
        active_scope.append(f"folder={folder}")
    effective_folder_rel = (
        folder_quick
        if folder_quick and folder_quick not in (_SIDEBAR_FILTER_FOLDER_ALL, "— Все папки —")
        else folder_rel
    )
    effective_folder_rel = apply_scope_folder_rel(effective_folder_rel)
    effective_topic = (
        topic_quick if topic_quick and topic_quick not in (_SIDEBAR_FILTER_TOPIC_ALL, "— Все темы —") else None
    )
    if effective_folder_rel:
        active_scope.append(f"folder_rel={effective_folder_rel}")
    if effective_topic:
        active_scope.append(f"topic={effective_topic}")
    if file_name:
        active_scope.append(f"file={file_name}")
    if relative_path:
        active_scope.append(f"path={relative_path}")
    if active_scope:
        st.caption("Текущая область поиска")
        render_chip_row(active_scope)
    actions = st.columns([1.4, 1])
    with actions[0]:
        ask_clicked = st.button("Получить ответ", key="ask_btn", width="stretch", type="primary")
    with actions[1]:
        reindex_clicked = st.button("Переиндексировать", key="reindex_btn", width="stretch", type="secondary")
    if ask_clicked:
        try:
            prepared_request = prepare_ask_request(
                type(
                    "UiAskRequest",
                    (),
                    {
                        "question": question,
                        "folder": folder or None,
                        "folder_rel": effective_folder_rel or None,
                        "file_name": file_name or None,
                        "relative_path": relative_path or None,
                        "topic": effective_topic,
                        "homework_mode": homework_mode,
                        "assistance_level": assistance_level if homework_mode else None,
                        "study_mode": study_mode,
                        "followup_context": (
                            f"Previous question: {st.session_state.get('last_answer', {}).get('question', '')}\n"
                            f"Previous answer: {st.session_state.get('last_answer', {}).get('answer', '')[:1500]}"
                            if study_mode and st.session_state.get("last_answer")
                            else None
                        ),
                    },
                )()
            )
        except InputGuardrailError as exc:
            st.error(f"Ошибка вопроса [{exc.code}]: {exc}")
        else:
            try:
                wait_copy = wait_runway_message_for_question(prepared_request.question)
                with st.spinner(wait_copy):
                    data = fetch_json(
                        "POST",
                        "/ask",
                        timeout=120,
                        json={
                            "question": prepared_request.question,
                            "folder": prepared_request.options.folder,
                            "folder_rel": prepared_request.options.folder_rel,
                            "file_name": prepared_request.options.file_name,
                            "relative_path": prepared_request.options.relative_path,
                            "topic": prepared_request.options.topic,
                            "homework_mode": prepared_request.options.homework_mode,
                            "assistance_level": prepared_request.options.assistance_level,
                            "study_mode": prepared_request.options.study_mode,
                            "followup_context": prepared_request.options.followup_context,
                        },
                    )
                st.session_state["last_answer"] = {
                    "question": prepared_request.question,
                    "answer": data.get("answer", ""),
                    "sources": data.get("sources") or [],
                    "confidence": data.get("confidence") or {},
                    "request_id": (data.get("debug") or {}).get("request_id"),
                }
                try:
                    from app.ui.tutorial_guide import note_activation_checkpoint

                    note_activation_checkpoint("first_question_sent")
                except Exception:  # noqa: BLE001 - activation coach must not break Q&A
                    pass
                src_paths = source_paths_from_answer(st.session_state["last_answer"])
                if src_paths:
                    set_last_studied_document(src_paths[0])
                st.session_state["last_debug"] = data.get("debug") or {}
                sync_latency_budget_from_debug(st.session_state["last_debug"])
                debug = st.session_state["last_debug"]
                if answer_qualifies_for_fast_success_reinforcement(
                    total_answer_ms=debug.get("total_answer_ms"),
                    confidence=data.get("confidence"),
                    sources=data.get("sources"),
                ):
                    st.session_state["qa_reinforcement"] = {
                        "request_id": debug.get("request_id"),
                        "phrase": fast_success_reinforcement_phrase(prepared_request.question),
                    }
                else:
                    st.session_state.pop("qa_reinforcement", None)
                srcs = data.get("sources") or []
                if srcs:
                    doc_paths = source_paths_from_answer({"sources": srcs})
                    post_knowledge_workflow(
                        "qa_answer_with_sources",
                        {
                            "documents_used_count": len(doc_paths),
                        },
                        payload={"source_nodes": len(srcs)},
                    )
                st.session_state["history"] = [
                    {
                        "question": prepared_request.question,
                        "answer": data.get("answer", ""),
                        "sources": data.get("sources") or [],
                    }
                ] + st.session_state["history"][: MAX_HISTORY - 1]
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка запроса: {format_request_error(e)}")
                st.caption(ask_failure_recovery_hint_from_exception(e))
    if reindex_clicked:
        try:
            response = fetch_json("POST", "/reindex", timeout=30, params={"reset": False})
            st.session_state["poll_reindex_status"] = True
            st.success(response)
            st.rerun()
        except Exception as e:
            st.error(f"Ошибка переиндексации: {format_request_error(e)}")
