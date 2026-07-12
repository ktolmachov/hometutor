"""Structured tutor response renderer."""
from __future__ import annotations

from typing import Any

import streamlit as st

from app.ui.helpers import build_tutor_orchestration_summary, esc_html
from app.ui.tutor_chat_render import (
    apply_smart_study_defer_from_session,
    apply_source_trust_smart_study_overlay,
    render_smart_study_trust_controls,
    render_teaching_summary_block,
    render_tutor_action_panel,
    render_tutor_trust_panel,
    render_tutor_visibility_badge,
)

def render_tutor_structured_response(
    data: dict[str, Any],
    *,
    msg_idx: int,
    session_id: str,
    tutor_meta: dict[str, Any] | None = None,
    message_sources: list[dict[str, Any]] | None = None,
) -> None:
    """Structured tutor response + action panel."""
    payload = data.get("tutor_data", data) if isinstance(data, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    meta = tutor_meta if isinstance(tutor_meta, dict) else {}

    render_tutor_visibility_badge(meta)

    lt = meta.get("learner_trace") if isinstance(meta, dict) else None
    if isinstance(lt, dict) and lt.get("concept"):
        st.caption(
            f"След записан: **{lt['concept']}** · "
            f"источников: {lt.get('source_count', 0)} · "
            f"mastery {float(lt.get('mastery_score', 0)):.0%}"
        )

    render_teaching_summary_block(payload.get("teaching_summary") or "")

    orchestration_summary = build_tutor_orchestration_summary(
        orchestration_state=meta.get("orchestration_state"),
        decision=meta.get("decision"),
        socratic=meta.get("socratic"),
        tutor_orchestration_pipeline=meta.get("tutor_orchestration_pipeline"),
        orchestration_phase=meta.get("orchestration_phase"),
        orchestration_decision_source=meta.get("orchestration_decision_source"),
        selected_agent=meta.get("selected_agent"),
        should_trigger_microquiz=meta.get("should_trigger_microquiz"),
        policy_clamped=meta.get("policy_clamped"),
        policy_clamp_reasons=meta.get("policy_clamp_reasons"),
    )
    if orchestration_summary:
        with st.expander("Контекст тьютора", expanded=False):
            for item in orchestration_summary:
                label = esc_html(item.get("label") or "")
                value = esc_html(item.get("value") or "")
                if label and value:
                    st.markdown(
                        f"<div><strong>{label}:</strong> {value}</div>",
                        unsafe_allow_html=True,
                    )

    steps = meta.get("tutor_pipeline")
    if isinstance(steps, list) and steps:
        with st.expander("Шаги оркестрации", expanded=False):
            for row in steps:
                if not isinstance(row, dict):
                    continue
                line = f"{row.get('step', '')} → {row.get('status', '')}"
                det = str(row.get("detail") or "").strip()
                if det:
                    line = f"{line} ({det})"
                st.caption(line)

    us = payload.get("understanding_state") or {}
    if not isinstance(us, dict):
        us = {}
    col1, col2, col3 = st.columns(3)
    with col1:
        st.success("Что ты уже понял")
        st.markdown(us.get("what_you_understood") or "—")
    with col2:
        st.warning("Риск пробела")
        st.markdown(us.get("risk_gaps") or "—")
    with col3:
        st.info("Что делать сейчас")
        st.markdown(us.get("what_to_do_now") or "—")

    na = (payload.get("next_action") or "").strip()
    nr = (payload.get("next_action_reason") or "").strip()
    if na or nr:
        st.markdown("**Следующий шаг**")
        if na:
            st.markdown(f"**{na}**")
        if nr:
            st.caption(nr)

    sc = payload.get("check_question") or payload.get("socratic_check")
    if sc is not None and str(sc).strip():
        st.markdown("**Проверь себя**")
        st.info(str(sc).strip())

    trust = payload.get("trust_signals") if isinstance(payload.get("trust_signals"), dict) else {}
    render_tutor_trust_panel(
        trust,
        payload,
        key_suffix=f"{session_id}_{msg_idx}",
        message_sources=message_sources,
    )

    render_tutor_action_panel(
        payload.get("suggested_ctas") or [],
        msg_idx=msg_idx,
        session_id=session_id,
        next_action=payload.get("next_action"),
    )

    if bool(meta.get("suppress_smart_study_overlay")):
        return

    try:
        from app import user_state as _user_state_ss
        from app.spaced_repetition import count_due_reviews as _count_due_ss
        from app.ui.adaptive_plan_card import (
            build_smart_study_recommendation,
            render_smart_study_next_step_card,
        )
        from app.ui.resume_cards_smart_study import (
            ladder_kwargs_for_build,
            remember_ssr_primary_nav,
            render_concept_recovery_ladder_status_ui,
        )

        _fc_ss = int(_user_state_ss.count_due_flashcards())
        _due_ss = int(_count_due_ss())
        _qf_ss: str | None = None
        try:
            _snap_ss = _user_state_ss.get_tutor_learning_resume()
            if isinstance(_snap_ss, dict):
                _qfi_ss = _snap_ss.get("quiz_feedback")
                if isinstance(_qfi_ss, dict):
                    _qf_ss = str(_qfi_ss.get("status") or "").strip() or None
        except Exception:  # noqa: BLE001 - robust optional read of tutor quiz feedback status
            pass
        tt_ss = str(st.session_state.get("current_topic") or "").strip() or None
        ost = meta.get("orchestration_state") if isinstance(meta.get("orchestration_state"), dict) else {}
        focus_ss = str((ost or {}).get("current_concept") or "").strip() or tt_ss
        last_a = st.session_state.get("last_answer")
        last_ad = last_a if isinstance(last_a, dict) else None
        has_qa_ss = bool(
            isinstance(last_a, dict)
            and (
                str(last_a.get("question") or "").strip()
                or str(last_a.get("answer") or "").strip()
            )
        )
        render_concept_recovery_ladder_status_ui()
        ss_tutor = build_smart_study_recommendation(
            surface="tutor_chat",
            flashcard_due_n=_fc_ss,
            sm2_due_n=_due_ss,
            quiz_feedback_status=_qf_ss,
            has_tutor_resume=bool(tt_ss),
            tutor_topic=focus_ss or tt_ss,
            has_last_answer_qa=has_qa_ss,
            has_reading_resume=False,
            first_weak_concept=None,
            plan_primary_block=None,
            **ladder_kwargs_for_build(
                current_anchor=focus_ss or tt_ss,
                quiz_feedback_status=_qf_ss,
            ),
        )
        remember_ssr_primary_nav(ss_tutor.primary_nav)
        ss_tutor, trust_applied = apply_source_trust_smart_study_overlay(
            ss_tutor,
            last_answer=last_ad,
            tutor_trust=trust if isinstance(trust, dict) else None,
        )
        ss_tutor, defer_applied = apply_smart_study_defer_from_session(ss_tutor)
        _tss_kp = f"tutor_ss_{session_id[:8]}_{msg_idx}"
        render_smart_study_next_step_card(
            ss_tutor,
            key_prefix=_tss_kp,
            tutor_topic=focus_ss or tt_ss,
            weak_concept=focus_ss,
            show_primary_button=True,
            has_last_answer_qa_for_steering=has_qa_ss,
            defer_was_applied_for_steering=defer_applied,
        )
        render_smart_study_trust_controls(
            ss_tutor,
            key_prefix=_tss_kp,
            trust_branch_applied=trust_applied,
            defer_applied=defer_applied,
        )
    except Exception:  # noqa: BLE001 - robust UI render, do not break tutor responses on smart study overlay failures
        pass


