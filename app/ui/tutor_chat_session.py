"""Session/query helpers and tutor chat tab orchestration."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from app.tutor_pipeline_contract import qa_handoff_context_lines_for_preview
from app.ui.answer_helpers import source_paths_from_answer
import app.ui.continuity_bridge as continuity_bridge
from app.ui.helpers import format_request_error as _format_request_error
import app.ui.resume_cards as resume_cards
import app.ui.session_state as ui_session_state
import app.ui.tutor_chat_actions as tutor_chat_actions
import app.ui.tutor_chat_controls as tutor_chat_controls
import app.ui.tutor_chat_footer as tutor_chat_footer
import app.ui.tutor_chat_header as tutor_chat_header
import app.ui.tutor_chat_quiz as tutor_chat_quiz
import app.ui.tutor_chat_render as tutor_chat_render
from app.flashcard_handoff import (
    FLASHCARD_HANDOFF_ENTRYPOINT,
    FLASHCARD_HANDOFF_SEED_ROUTE,
    clear_flashcard_handoff_session_fields,
)
from app.flashcard_handoff_timing import (
    handoff_active,
    log_handoff_answer_ready,
    record_handoff_tutor_mount,
)
from app.ui.flashcard_handoff_source_actions import render_flashcard_handoff_source_actions

logger = logging.getLogger(__name__)

_FLASHCARD_HANDOFF_EXPLANATION_ANCHOR = "flashcard-tutor-explanation"
_FLASHCARD_HANDOFF_SCROLL_PENDING_KEY = "tutor_handoff_scroll_to_answer_pending"


def _apply_qa_handoff_context() -> None:
    """Hydrate tutor startup state from QA continuity payload."""
    payload = continuity_bridge.load_qa_tutor_handoff_context(st.session_state)
    if not payload:
        return
    topic = (payload.get("topic") or "").strip()
    last_question = (payload.get("last_question") or "").strip()
    if topic and not st.session_state.get("current_topic"):
        st.session_state["current_topic"] = topic
    if topic and not st.session_state.get("tutor_goal_subtopic"):
        st.session_state["tutor_goal_subtopic"] = topic[:120]
    if topic and not st.session_state.get("tutor_goal_desired_outcome"):
        st.session_state["tutor_goal_desired_outcome"] = f"Разобраться с «{topic[:80]}»"
    if last_question and not st.session_state.get("learning_goal"):
        st.session_state["learning_goal"] = last_question[:240]


def build_tutor_query_options(
    session_id: str,
    *,
    homework_mode: bool = False,
    assistance_level: str | None = None,
) -> Any:
    """QueryOptions for tutor mode: goal + depth + preferences."""
    from app.models import QueryOptions
    from app.ui.study_scope import scope_folder_rel as _scope_folder_rel
    from app.user_state import get_preferred_style

    _apply_qa_handoff_context()

    _qlm_raw = (st.session_state.get("quiz_learning_mode") or "auto").strip().lower()
    _quiz_lm = None if _qlm_raw in ("", "auto") else _qlm_raw

    _entrypoint = (st.session_state.get("tutor_entrypoint") or "").strip() or None
    _from_fc = _entrypoint == FLASHCARD_HANDOFF_ENTRYPOINT
    _depth = "short" if _from_fc else st.session_state.get("tutor_answer_depth", "examples")

    return QueryOptions(
        session_id=session_id,
        query_mode="tutor",
        folder_rel=_scope_folder_rel(),
        homework_mode=homework_mode,
        assistance_level=assistance_level,
        tutor_learning_goal=st.session_state.get("learning_goal"),
        tutor_answer_depth=_depth,
        tutor_preferred_style=get_preferred_style(),
        tutor_mastery_level=st.session_state.get("tutor_mastery_level", "intermediate"),
        quiz_learning_mode=_quiz_lm,
        tutor_goal_subtopic=st.session_state.get("tutor_goal_subtopic"),
        tutor_goal_target_level=st.session_state.get("tutor_goal_target_level"),
        tutor_goal_desired_outcome=st.session_state.get("tutor_goal_desired_outcome"),
        tutor_goal_time_budget_min=st.session_state.get("tutor_goal_time_budget_min"),
        tutor_entrypoint=_entrypoint,
        rag_profile="fast" if _from_fc else None,
    )


def _render_qa_tutor_handoff_transition_styles() -> None:
    """US-19.2: 300–500 ms intro motion + визуальная связь с Q&A (MoT #3)."""
    st.markdown(
        """
        <style>
        @keyframes qaTutorHandoffIn {
            from { opacity: 0.42; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        div.qa-tutor-handoff-shell {
            animation: qaTutorHandoffIn 0.42s ease-out;
            border-left: 4px solid #2e7d32;
            padding-left: 0.65rem;
            margin-bottom: 0.75rem;
        }
        div.qa-tutor-handoff-bridge {
            border: 1px dashed rgba(46, 125, 50, 0.38);
            border-radius: 12px;
            padding: 0.45rem 0.65rem;
            margin-top: 0.35rem;
            background: rgba(46, 125, 50, 0.04);
            font-size: 0.92rem;
        }
        @media (prefers-reduced-motion: reduce) {
            div.qa-tutor-handoff-shell {
                animation: none !important;
                transform: none !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_qa_handoff_incomplete_from_qa_flow() -> None:
    """AC6 US-19.2: запрос недостающего вопроса, если payload не сохранился."""
    if str(st.session_state.get("tutor_e11_loop_origin") or "") != "qa":
        return
    if continuity_bridge.load_qa_tutor_handoff_context(st.session_state):
        return
    st.warning(
        "Контекст перехода из «Быстрого ответа» неполный: не зафиксирован вопрос. "
        "Введите его — контекст будет собран и передастся в тьютор.",
    )
    with st.form("qa_handoff_missing_question_form"):
        mq = st.text_input("Вопрос к базе (как в Q&A)", placeholder="Например: Что такое RAG?")
        submitted = st.form_submit_button("Сохранить контекст и продолжить", type="primary")
        if not submitted:
            return
        mq_s = (mq or "").strip()
        if not mq_s:
            st.error("Вопрос не может быть пустым.")
            return
        topic_guess = str(st.session_state.get("current_topic") or "").strip() or mq_s[:120]
        la = st.session_state.get("last_answer")
        summary_raw = ""
        if isinstance(la, dict):
            summary_raw = str(la.get("answer") or "").strip()
        ok = continuity_bridge.store_qa_tutor_handoff_context(
            st.session_state,
            topic=topic_guess,
            last_question=mq_s,
            answer_summary=summary_raw[:500] if summary_raw else None,
            source="quick_answer_cta_ac6",
        )
        if not ok:
            st.error("Не удалось сохранить контекст — попробуйте короче сформулировать вопрос.")
            return
        st.session_state["tutor_pending_prompt"] = (
            f"Объясни тему «{topic_guess}»: {mq_s}" if topic_guess else mq_s
        )
        st.session_state["tutor_pending_session_id"] = str(
            st.session_state.get("tutor_session_id") or ""
        )
        st.rerun()


def _render_qa_tutor_handoff_summary_card(
    handoff: dict[str, Any],
    *,
    last_answer: dict[str, Any] | None,
) -> None:
    st.markdown('<div class="qa-tutor-handoff-shell">', unsafe_allow_html=True)
    st.caption("Переход из **Быстрый ответ** (MoT #3)")
    preview = qa_handoff_context_lines_for_preview(handoff, last_answer=last_answer)
    for line in preview:
        st.markdown(line)
    paths = source_paths_from_answer(last_answer) if last_answer else []
    if paths:
        st.caption("Пути источников (срез): " + ", ".join(paths[:8]))
    st.markdown(
        '<div class="qa-tutor-handoff-bridge">'
        "Связь с исходным ответом: тьютор ниже продолжает эту же линию рассуждений и резюме выше."
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


def _render_tutor_depth_switcher() -> None:
    tutor_chat_controls.render_tutor_depth_switcher()


def _render_nba_card(nba: dict[str, Any] | None) -> None:
    """Render Next Best Action card."""
    if not isinstance(nba, dict):
        return
    _nba_c = str(nba.get("concept") or "").strip()
    _nba_r = str(nba.get("reason") or "").strip()
    _nba_a = str(nba.get("action") or "").strip()
    if _nba_c or _nba_r or _nba_a:
        st.markdown(
            f'<div class="tutor-nba-card"><strong>Следующий шаг</strong><br/>'
            f"{_nba_c} — {_nba_r} "
            f'<span style="opacity:0.75">({_nba_a})</span></div>',
            unsafe_allow_html=True,
        )
        if _nba_c and st.button("Показать концепт для копирования", key="tutor_copy_concept"):
            st.code(_nba_c, language="text")


def _handle_tutor_cta_click(action: str, session_id: str, msg_idx: int) -> None:
    tutor_chat_actions.handle_tutor_cta_click(action, session_id, msg_idx)


def _micro_quiz_letter_from_choice(choice: str, options: list[str]) -> str:
    return tutor_chat_actions.micro_quiz_letter_from_choice(choice, options)


def _micro_quiz_status_ru(status: str | None) -> str:
    return tutor_chat_actions.micro_quiz_status_ru(status)


def _render_unified_auto_quiz_card(
    auto_quiz: dict[str, Any],
    msg_idx: int,
    session_id: str,
) -> None:
    tutor_chat_quiz.render_unified_auto_quiz_card(auto_quiz, msg_idx, session_id)


def _render_tutor_micro_quiz_block(active: dict[str, Any], session_id: str) -> None:
    tutor_chat_quiz.render_tutor_micro_quiz_block(active, session_id)


def _render_tutor_action_panel(
    ctas: list[Any],
    *,
    msg_idx: int,
    session_id: str,
    next_action: str | None = None,
) -> None:
    tutor_chat_render.render_tutor_action_panel(
        ctas,
        msg_idx=msg_idx,
        session_id=session_id,
        next_action=next_action,
    )


def _render_tutor_visibility_badge(meta: dict[str, Any]) -> None:
    tutor_chat_render.render_tutor_visibility_badge(meta)


def _render_tutor_trust_panel(
    trust: dict[str, Any],
    payload: dict[str, Any],
    *,
    key_suffix: str = "",
    message_sources: list[dict[str, Any]] | None = None,
) -> None:
    tutor_chat_render.render_tutor_trust_panel(
        trust,
        payload,
        key_suffix=key_suffix,
        message_sources=message_sources,
    )


def _render_tutor_structured_response(
    data: dict[str, Any],
    *,
    msg_idx: int,
    session_id: str,
    tutor_meta: dict[str, Any] | None = None,
    message_sources: list[dict[str, Any]] | None = None,
) -> None:
    tutor_chat_render.render_tutor_structured_response(
        data,
        msg_idx=msg_idx,
        session_id=session_id,
        tutor_meta=tutor_meta,
        message_sources=message_sources,
    )


def _nba_from_tutor_decision(decision: dict[str, Any] | None) -> dict[str, Any] | None:
    return tutor_chat_render.nba_from_tutor_decision(decision)


def _tutor_query_options(
    session_id: str,
    *,
    homework_mode: bool = False,
    assistance_level: str | None = None,
) -> Any:
    return build_tutor_query_options(
        session_id,
        homework_mode=homework_mode,
        assistance_level=assistance_level,
    )



def _handle_completed_tutor_result(
    result: dict[str, Any],
    session_id: str,
    graph_summary: str,
    session_store: Any,
) -> None:
    from app.ui.latency_budget_sync import sync_latency_budget_from_debug

    sync_latency_budget_from_debug(result.get("debug"))

    if handoff_active(st.session_state):
        _dbg = dict(result.get("debug") or {})
        _engine = _dbg.get("engine_acquire_ms")
        log_handoff_answer_ready(
            st.session_state,
            api_debug={
                **_dbg,
                "engine_build_ms": _engine,
                "retrieval_ms": _dbg.get("retrieval_ms"),
                "llm_ms": _dbg.get("llm_ms") or _dbg.get("llm_latency_ms"),
                "post_processing_ms": _dbg.get("post_processing_ms"),
                "auto_quiz_ms": _dbg.get("auto_quiz_ms"),
                "inline_quiz_ms": _dbg.get("inline_quiz_ms"),
            },
        )

    tutor_payload = result.get("tutor") or {}
    dbg = result.get("debug") or {}
    st.session_state["tutor_last_nba"] = _nba_from_tutor_decision(
        tutor_payload.get("decision")
    ) or dbg.get("tutor_next_best_action")
    st.session_state["tutor_last_graph"] = graph_summary
    st.session_state["tutor_show_quiz_tpl"] = False

    if st.session_state.get("tutor_entrypoint") == FLASHCARD_HANDOFF_ENTRYPOINT:
        msgs_u = session_store.get(session_id)
        idx_u = continuity_bridge.last_assistant_message_index(msgs_u)
        st.session_state["tutor_handoff_check_self_pending"] = True
        st.session_state["tutor_handoff_quiz_msg_idx"] = idx_u
        clear_flashcard_handoff_session_fields(st.session_state)

    te = tutor_payload.get("teaching")
    if isinstance(te, dict) and te.get("depth_level"):
        ui_session_state.persist_tutor_mastery_level(str(te["depth_level"]))
    resume_cards.persist_tutor_resume_after_tutor_answer(
        session_id,
        st.session_state.get("_ui_index_stats_tab"),
    )

    if st.session_state.pop("tutor_e11_five_min_loop", False):
        import app.config as app_config

        if result.get("timed_out"):
            st.warning("Тьютор не успел ответить — попробуйте ещё раз.")
            return
        auto = tutor_payload.get("auto_quiz")
        unified_ok = bool(
            app_config.get_settings().enable_tutor_auto_quiz_loop
            and isinstance(auto, dict)
            and auto.get("show_immediately")
        )
        msgs_u = session_store.get(session_id)
        idx_u = continuity_bridge.last_assistant_message_index(msgs_u)
        if unified_ok:
            st.session_state["tutor_e11_five_min_unified_msg_idx"] = idx_u
        else:
            st.session_state.pop("tutor_micro_quiz_e11_loop", None)
            st.session_state.pop("tutor_micro_quiz_start", None)


def _process_tutor_reply(question: str | None, session_id: str, graph_summary: str) -> None:
    """Run answer_question in a background thread so the Streamlit UI stays responsive."""
    import concurrent.futures as _cf
    import contextvars
    import time

    import app.guardrails as guardrails
    import app.query_service as query_service
    import app.tutor_prompts as tutor_prompts
    from app.session_store import session_store

    _FUTURE_KEY = "_tutor_llm_future"
    _EXEC_KEY = "_tutor_llm_executor"
    _POLL_SEC = 0.3

    if question is not None and _FUTURE_KEY not in st.session_state:
        hw = tutor_prompts.infer_homework_level_from_message(question)
        opts = _tutor_query_options(session_id, homework_mode=bool(hw), assistance_level=hw)
        validated_q = guardrails.validate_question(question)
        executor = _cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="tutor_llm")
        ctx = contextvars.copy_context()
        future = executor.submit(ctx.run, query_service.answer_question, validated_q, opts)
        st.session_state[_FUTURE_KEY] = future
        st.session_state[_EXEC_KEY] = executor

    future = st.session_state.get(_FUTURE_KEY)
    if future is None:
        return

    if not future.done():
        with st.status("Тьютор отвечает…", expanded=True):
            time.sleep(_POLL_SEC)
        st.rerun()
        return

    executor = st.session_state.pop(_EXEC_KEY, None)
    st.session_state.pop(_FUTURE_KEY, None)
    if executor:
        executor.shutdown(wait=False)

    try:
        result = future.result()
    except Exception as e:  # noqa: BLE001 - UI request path must render a user-facing error.
        st.session_state.pop("tutor_e11_five_min_loop", None)
        if st.session_state.get("tutor_entrypoint") == FLASHCARD_HANDOFF_ENTRYPOINT:
            clear_flashcard_handoff_session_fields(st.session_state)
        st.error(_format_request_error(e))
        return

    _handle_completed_tutor_result(result, session_id, graph_summary, session_store)
    st.rerun()


def _render_e11_loop_fallback(session_id: str) -> None:
    """Fallback next-step panel when quiz branch is unavailable."""
    from app.session_store import session_store

    if not bool(st.session_state.get("tutor_e11_loop_active")):
        return
    if str(st.session_state.get("tutor_e11_loop_origin") or "") != "qa":
        return
    if st.session_state.get("tutor_e11_five_min_unified_msg_idx") is not None:
        return
    mq = st.session_state.get("tutor_micro_quiz_active")
    if isinstance(mq, dict) and mq.get("sid") == session_id:
        return
    history_now = session_store.get(session_id)
    if not any(getattr(m, "role", None) == "assistant" for m in history_now):
        return
    topic = str(st.session_state.get("current_topic") or "").strip()
    with st.container(border=True):
        st.caption("Завершение 5-минутной сессии")
        _render_tutor_checkpoint(
            session_id=session_id,
            topic=topic,
            key_prefix="tutor_e11_fallback",
        )


def _session_has_assistant_reply(session_id: str) -> bool:
    try:
        from app.session_store import session_store

        if session_store is None:
            return False
        for msg in session_store.get(session_id) or []:
            if getattr(msg, "role", None) == "assistant":
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _render_tutor_intro() -> str:
    tutor_chat_header.render_tutor_chat_styles()
    _render_qa_tutor_handoff_transition_styles()
    st.markdown('<div class="panel">', unsafe_allow_html=True)

    sid = st.session_state.get("tutor_session_id") or str(uuid.uuid4())
    st.session_state["tutor_session_id"] = sid
    has_reply = _session_has_assistant_reply(sid)
    tutor_chat_header.render_tutor_chat_intro(has_assistant_reply=has_reply)
    tutor_chat_header.render_tutor_active_goal()
    _render_tutor_depth_switcher()

    if st.session_state.get("flashcard_review_return") and handoff_active(st.session_state):
        record_handoff_tutor_mount(st.session_state)
    _render_qa_handoff_incomplete_from_qa_flow()
    _render_tutor_handoff_context()
    tutor_chat_controls.render_tutor_extra_controls(session_id=sid)
    _render_tutor_plan_expander()
    return sid


def _render_tutor_handoff_context() -> None:
    la_raw = st.session_state.get("last_answer")
    last_answer_d = la_raw if isinstance(la_raw, dict) else None
    handoff = continuity_bridge.load_qa_tutor_handoff_context(st.session_state)
    if not isinstance(handoff, dict):
        return
    topic = str(handoff.get("topic") or "").strip()
    reason = continuity_bridge.tutor_reason_line_ru()
    next_step = continuity_bridge.continuity_next_step_line_ru(topic=topic)
    _render_qa_tutor_handoff_summary_card(handoff, last_answer=last_answer_d)
    with st.container(border=True):
        st.caption("Текущий учебный контекст")
        st.caption(f"Почему это подходит: {reason}")
        st.caption(next_step)

    # B1 completion: предложение закрыть вопрос из Живого конспекта после ответа
    if handoff.get("source") == "living_konspekt_open_question":
        row_key = st.session_state.get("pending_living_konspekt_close_row")
        if row_key:
            st.markdown("---")
            if st.button("✅ Закрыть этот вопрос в Живом конспекте", key="b1_close_from_tutor"):
                try:
                    from app.ui.living_konspekt_state import set_open_question_in_workbench
                    from app.ui.continuity_bridge import clear_qa_tutor_handoff_context
                    set_open_question_in_workbench(row_key, None)
                    st.session_state.pop("pending_living_konspekt_close_row", None)
                    clear_qa_tutor_handoff_context(st.session_state)
                    st.toast("Вопрос закрыт в конспекте.", icon="✅")
                    # Optional: exposure trace hint (can be expanded later)
                except Exception:  # noqa: BLE001
                    st.toast("Не удалось закрыть вопрос.", icon="⚠️")
                st.rerun()


def _render_tutor_plan_expander() -> None:
    with st.expander("Адаптивный план и прогноз (Mastery Forecast)", expanded=False):
        import app.ui.adaptive_plan_widgets as adaptive_plan_widgets
        import app.ui.tutor_mastery_forecast_panel as tutor_mastery_forecast_panel

        tutor_mastery_forecast_panel.render_tutor_mastery_forecast_panel()
        st.divider()
        adaptive_plan_widgets.render_adaptive_daily_plan_section()


def _render_tutor_progress() -> str:
    import app.knowledge_service as knowledge_service

    learned = list(st.session_state.get("tutor_learned_concepts") or [])
    graph_summary = knowledge_service.knowledge_graph.get_graph_summary(learned)
    pct = 0
    m_pct = re.search(r"(\d+)%", graph_summary)
    if m_pct:
        pct = min(100, int(m_pct.group(1)))
    try:
        ms = knowledge_service.knowledge_graph.get_progress_stats()
        mp = float(ms.get("mastery_percent") or 0)
    except Exception:  # noqa: BLE001 - graph progress stats are optional UI context.
        logger.warning("tutor_progress_stats_failed", exc_info=True)
        mp = 0.0

    prev_m = st.session_state.get("tutor_prev_mastery_pct")
    if prev_m is not None and float(prev_m) < 80.0 <= mp:
        st.balloons()
        st.success("Level Up! Mastery по графу ≥ 80%")
    st.session_state["tutor_prev_mastery_pct"] = mp

    tutor_chat_controls.render_tutor_progress_bar(pct, mp)
    if not st.session_state.get("tutor_focus_mode"):
        with st.expander("Текстовая сводка по графу", expanded=False):
            st.caption(graph_summary)
    return graph_summary


def _handle_pending_tutor_prompt(sid: str, graph_summary: str) -> None:
    if "_tutor_llm_future" in st.session_state:
        _process_tutor_reply(None, sid, graph_summary)
        return
    pending = st.session_state.pop("tutor_pending_prompt", None)
    pending_sid = st.session_state.pop("tutor_pending_session_id", None)
    if pending and pending_sid == sid:
        _process_tutor_reply(pending, sid, graph_summary)


def _maybe_start_tutor_micro_quiz(sid: str) -> None:
    from app.session_store import session_store
    import app.quiz_service as quiz_service
    import app.user_state as user_state

    mq_start = st.session_state.pop("tutor_micro_quiz_start", None)
    if not (isinstance(mq_start, dict) and mq_start.get("sid") == sid):
        return

    msgs = session_store.get(sid)
    topic = (
        quiz_service.topic_from_last_user_message(msgs)
        or (st.session_state.get("tutor_last_nba") or {}).get("concept")
        or ""
    )
    e11_loop = bool(st.session_state.get("tutor_micro_quiz_e11_loop"))
    if e11_loop and not topic:
        st.session_state.pop("tutor_micro_quiz_e11_loop", None)
        st.info("Не удалось определить тему для мини-проверки. Уточните тему или задайте конкретный вопрос.")
        return

    topic = topic or "Общая тема"
    mastery = st.session_state.get("tutor_mastery_level", "intermediate")
    recent = user_state.get_recent_quiz_levels_low_score(topic)
    try:
        with st.spinner("Готовим мини-проверку…"):
            _raw_m = st.session_state.get("quiz_learning_mode", "auto")
            _lm = None if str(_raw_m).strip().lower() in ("auto", "") else str(_raw_m).strip().lower()
            qd = quiz_service.generate_micro_quiz(
                topic,
                mastery,
                recent_errors=recent,
                learning_mode=_lm,
                topic_concept=topic,
            )
    except Exception as e:  # noqa: BLE001 - UI quiz generation must render a user-facing error.
        st.error(_format_request_error(e))
        return

    from app.ui.latency_budget_sync import sync_latency_budget_from_payload

    sync_latency_budget_from_payload(qd)
    e11_loop = bool(st.session_state.pop("tutor_micro_quiz_e11_loop", False))
    st.session_state["tutor_micro_quiz_active"] = {
        "sid": sid, "msg_idx": int(mq_start.get("msg_idx", 0)), "quiz_data": qd,
        "topic": topic, "answered": False, "feedback": None, "e11_five_min_loop": e11_loop,
    }
    st.rerun()


def _is_flashcard_handoff_seed_message(msg: Any) -> bool:
    meta = getattr(msg, "metadata", None)
    if not isinstance(meta, dict):
        return False
    debug = meta.get("debug") if isinstance(meta.get("debug"), dict) else {}
    if bool(debug.get("flashcard_handoff_seed")):
        return True
    sources = meta.get("sources")
    if isinstance(sources, list):
        return any(
            isinstance(source, dict) and source.get("route") == FLASHCARD_HANDOFF_SEED_ROUTE
            for source in sources
        )
    return False


def _render_flashcard_handoff_explanation_anchor() -> None:
    st.markdown(
        (
            f'<div id="{_FLASHCARD_HANDOFF_EXPLANATION_ANCHOR}" '
            'style="scroll-margin-top:5.5rem"></div>'
        ),
        unsafe_allow_html=True,
    )
    if not st.session_state.pop(_FLASHCARD_HANDOFF_SCROLL_PENDING_KEY, False):
        return
    components.html(
        f"""
        <script>
        try {{
          const target = window.parent.document.getElementById("{_FLASHCARD_HANDOFF_EXPLANATION_ANCHOR}");
          if (target) {{
            target.scrollIntoView({{behavior: "smooth", block: "start"}});
          }}
        }} catch (error) {{
          // Fallback link remains visible below the tutor response.
        }}
        </script>
        """,
        height=0,
    )


def _render_flashcard_handoff_source_actions(
    sources: list[dict[str, Any]] | None,
) -> None:
    if not sources:
        return
    source = next(
        (
            item
            for item in sources
            if isinstance(item, dict) and item.get("route") == FLASHCARD_HANDOFF_SEED_ROUTE
        ),
        None,
    )
    if not isinstance(source, dict):
        return
    render_flashcard_handoff_source_actions(source)


def _render_tutor_history(sid: str, history: list[Any]) -> None:
    for idx, msg in enumerate(history):
        if msg.role == "assistant" and _is_flashcard_handoff_seed_message(msg):
            _render_flashcard_handoff_explanation_anchor()
        with st.chat_message(msg.role):
            meta = msg.metadata or {}
            tutor_meta = meta.get("tutor") if isinstance(meta, dict) else {}
            tutor_answer = meta.get("tutor_answer") if isinstance(meta, dict) else None
            tv2 = tutor_meta.get("teaching") if isinstance(tutor_meta, dict) else None
            auto_q = tutor_meta.get("auto_quiz") if isinstance(tutor_meta, dict) else None
            msg_sources = meta.get("sources") if isinstance(meta.get("sources"), list) else None

            if msg.role == "assistant" and (isinstance(tutor_answer, dict) or isinstance(tv2, dict)):
                _render_tutor_structured_response(
                    tutor_answer or tv2, msg_idx=idx, session_id=sid,
                    tutor_meta=tutor_meta, message_sources=msg_sources,
                )
            else:
                st.markdown(msg.content)

            if msg.role == "assistant" and isinstance(auto_q, dict) and auto_q.get("show_immediately"):
                _render_unified_auto_quiz_card(auto_q, idx, sid)
            if msg.role == "assistant" and _is_flashcard_handoff_seed_message(msg):
                _render_flashcard_handoff_source_actions(msg_sources)


def _render_tutor_followups(sid: str) -> None:
    mqa = st.session_state.get("tutor_micro_quiz_active")
    if isinstance(mqa, dict) and mqa.get("sid") == sid:
        with st.chat_message("assistant"):
            _render_tutor_micro_quiz_block(mqa, sid)
        return
    if st.session_state.get("tutor_handoff_check_self_pending"):
        _idx = int(st.session_state.get("tutor_handoff_quiz_msg_idx") or 0)
        st.markdown(
            f'<a href="#{_FLASHCARD_HANDOFF_EXPLANATION_ANCHOR}">↑ К объяснению карточки</a>',
            unsafe_allow_html=True,
        )
        if st.button("Проверить себя", key="tutor_handoff_check_self", type="secondary"):
            st.session_state.pop("tutor_handoff_check_self_pending", None)
            st.session_state.pop("tutor_handoff_quiz_msg_idx", None)
            st.session_state["tutor_micro_quiz_start"] = {"sid": sid, "msg_idx": _idx}
            st.rerun()
    _render_e11_loop_fallback(sid)


def _render_tutor_dev_tools() -> None:
    import app.config as app_config

    if not app_config.get_settings().show_tutor_dev_tools:
        return
    if st.button("Сгенерировать quiz (шаблон)", key="tutor_quiz_btn"):
        st.session_state["tutor_show_quiz_tpl"] = True
    if st.session_state.get("tutor_show_quiz_tpl"):
        with st.expander("Шаблон промпта квиза", expanded=True):
            import app.prompts as prompts

            _raw = str(st.session_state.get("quiz_learning_mode", "auto")).strip().lower()
            _eff = st.session_state.get("learning_goal") if _raw in ("auto", "") else st.session_state.get("quiz_learning_mode")
            st.code(
                prompts.QUIZ_PROMPT.format(
                    mode_instructions=prompts.quiz_interactive_mode_block(_eff),
                    topic="RAG", user_level="средний", learned_concepts="—",
                    recent_history="—", concept_names="RAG, Chunking",
                ),
                language="markdown",
            )


def render_tutor_chat_tab() -> None:
    """Multi-turn чат: session store, query_mode=tutor, прогресс графа, экспорт, карточка NBA."""
    from app.session_store import session_store
    import app.knowledge_service as knowledge_service

    sid = _render_tutor_intro()
    sessions = session_store.list_sessions(limit=30)
    sid = tutor_chat_controls.render_tutor_session_selector(sessions, sid)
    graph_summary = _render_tutor_progress()
    _handle_pending_tutor_prompt(sid, graph_summary)
    _maybe_start_tutor_micro_quiz(sid)

    # W9 order: history + followups + input first; exports/expert after the learning loop.
    history = session_store.get(sid)
    _render_tutor_history(sid, history)
    _render_tutor_followups(sid)
    _render_nba_card(st.session_state.get("tutor_last_nba"))

    if not st.session_state.get("tutor_focus_mode"):
        gs = st.session_state.get("tutor_last_graph")
        if gs:
            st.caption(gs)

    _render_tutor_dev_tools()
    prompt = st.chat_input("Спросите тьютора…", key="tutor_chat_input")
    if prompt:
        _process_tutor_reply(prompt, sid, graph_summary)

    with st.expander("Экспорт и эксперт", expanded=False):
        tutor_chat_footer.render_tutor_chat_exports(sid, history)
        tutor_chat_footer.render_tutor_chat_footer(
            sid,
            len(sessions),
            len(knowledge_service.knowledge_graph.get_concepts()),
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _render_tutor_checkpoint(
    *,
    session_id: str,
    topic: str | None = None,
    key_prefix: str,  # noqa: ARG001 - used by checkpoint button keys
) -> None:
    """B1: after tutor micro-step completion, render unified checkpoint."""
    import logging as _logging  # noqa: BLE001

    _log = _logging.getLogger(__name__)

    try:
        from app.ui.checkpoint import render_checkpoint
        from app.smart_study_router import build_smart_study_recommendation
        from app.ui.resume_cards_smart_study import gather_smart_study_router_session_context, _get_saved_plan_primary_block
    except Exception as _exc:  # noqa: BLE001
        _log.debug("checkpoint import failed: %s", _exc)
        _render_fallback_buttons(key_prefix, session_id)
        return
    try:
        ctx = gather_smart_study_router_session_context(index_stats=None)
    except Exception as _exc:  # noqa: BLE001
        _log.debug("checkpoint context gather failed: %s", _exc)
        _render_fallback_buttons(key_prefix, session_id)
        return
    if ctx is None:
        _render_fallback_buttons(key_prefix, session_id)
        return

    plan_block = _get_saved_plan_primary_block()
    rec = build_smart_study_recommendation(
        surface="tutor_chat",
        flashcard_due_n=ctx.flashcard_due_n,
        sm2_due_n=ctx.sm2_due_n,
        quiz_feedback_status=None,
        has_tutor_resume=bool(ctx.effective_tutor_snap),
        tutor_topic=ctx.tutor_topic or topic,
        has_last_answer_qa=ctx.has_last_answer_qa,
        has_reading_resume=ctx.has_reading,
        first_weak_concept=ctx.weak_concepts[0] if ctx.weak_concepts else None,
        plan_primary_block=plan_block,
    )

    def _on_tutor_checkpoint_action():
        st.session_state["tutor_e11_loop_active"] = False
        st.session_state.pop("tutor_e11_loop_origin", None)

    render_checkpoint(
        rec,
        surface="tutor",
        origin="tutor",
        return_view=st.session_state.get(
            "home_breadcrumb_origin",
            st.session_state.get("current_view", "Mission Control"),
        ),
        key_prefix=key_prefix,
        completion_key=f"tutor:e11:{session_id}:{ctx.tutor_topic or topic or ''}",
        tutor_session_id=session_id,
        tutor_topic=ctx.tutor_topic or topic,
        weak_concept=ctx.weak_concepts[0] if ctx.weak_concepts else None,
        plan_block=plan_block,
        on_finish=_on_tutor_checkpoint_action,
    )


def _render_fallback_buttons(key_prefix: str, session_id: str) -> None:
    """Fallback: simple continue/finish buttons when checkpoint cannot render."""
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Продолжить 1 шаг", key=f"{key_prefix}_fb_continue", width="stretch", type="primary"):
            st.session_state["tutor_pending_prompt"] = "Следующий шаг"
            st.session_state["tutor_pending_session_id"] = session_id
            st.rerun()
    with c2:
        if st.button("Готово на сегодня", key=f"{key_prefix}_fb_done", width="stretch", type="secondary"):
            st.session_state["tutor_e11_loop_active"] = False
            st.session_state.pop("tutor_e11_loop_origin", None)
            st.success("Сессию можно завершить: следующий шаг сохранён в контексте.")
