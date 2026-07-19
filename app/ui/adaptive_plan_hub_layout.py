"""Home hub layout for Adaptive Daily Plan."""
from __future__ import annotations

from typing import Any

import streamlit as st

from app.gamification_service import count_completed_plan_blocks, get_snapshot
from app.smart_study_router import (
    build_smart_study_evidence_ledger_lines,
    build_smart_study_recommendation,
)


def render_adaptive_plan_hub(
    user_id: str | None = None,
    *,
    key_prefix: str = "adp_hub",
    plan_override: dict[str, Any] | None = None,
    preview_limit: int = 4,
) -> None:
    from app.ui import adaptive_plan_card as _card

    """Главный CTA-блок дня для home: next action, прогресс, быстрые переходы."""
    uid = _card._session_user_id(user_id)
    with st.spinner("Собираем план на сегодня..."):
        try:
            plan = _card.get_adaptive_daily_plan(uid, plan_override=plan_override)
        except Exception as e:  # noqa: BLE001 - Streamlit plan loading fallback must render a retry state.
            st.error(f"Не удалось загрузить план: {e}")
            retry_col, _ = st.columns([1, 3])
            with retry_col:
                if st.button("Повторить", key=f"{key_prefix}_retry", width='stretch'):
                    st.rerun()
            return

    blocks = list(plan.get("blocks") or [])
    rendered_blocks = _card._iter_plan_blocks(blocks)
    primary_block = _card.get_primary_plan_block_from_plan(plan)
    entry_state = str(plan.get("entry_state") or "").strip() or (
        "actionable" if primary_block is not None else "empty"
    )
    progress = get_snapshot()
    total_blocks = len(rendered_blocks)
    progress_done = count_completed_plan_blocks(
        plan_date=str(plan.get("date") or ""),
        blocks=blocks,
    )
    ratio = min(1.0, progress_done / float(total_blocks)) if total_blocks > 0 else 0.0
    reviews = sum(1 for _, raw in rendered_blocks if str(raw.get("type") or "").strip() == "review")
    gaps = sum(1 for _, raw in rendered_blocks if str(raw.get("type") or "").strip() == "gap")
    new_topics = sum(1 for _, raw in rendered_blocks if str(raw.get("type") or "").strip() == "new")

    st.markdown('<div class="home-dash-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="home-dash-head home-dash-head-continue"><h3>📅 План на сегодня</h3></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="home-dash-body">', unsafe_allow_html=True)

    st.progress(ratio, text=f"Прогресс плана: {progress_done}/{total_blocks} блоков" if total_blocks > 0 else "Прогресс плана: шаги ещё не сформированы")
    st.caption(
        _card.build_plan_progress_summary(
            progress_done=progress_done,
            total_blocks=total_blocks,
            daily_xp=int(progress.get("daily_xp_today") or 0),
        )
    )
    # C1 bridge: show learning plan step context when available
    lp_ctx = plan.get("learning_plan_context")
    if lp_ctx:
        lp_title = str(lp_ctx.get("display_title") or "Программа обучения")
        lp_step = lp_ctx.get("step_index")
        lp_label = str(lp_ctx.get("step_label") or "")
        lp_progress = lp_ctx.get("progress")
        ctx_parts = [f"📖 {lp_title}"]
        if lp_step is not None:
            ctx_parts.append(f"шаг {int(lp_step) + 1}")
        if lp_label:
            ctx_parts.append(f"— {lp_label[:80]}")
        if lp_progress is not None:
            pct = min(1.0, max(0.0, float(lp_progress))) * 100
            ctx_parts.append(f"({pct:.0f}%)")
        st.caption(" · ".join(ctx_parts))

    if total_blocks > 0 and progress_done == 0:
        st.caption(
            "План на сегодня уже сформирован — начните с кнопки «Начать следующий шаг» (US-6.1)."
        )
    mot = str(plan.get("motivation_message") or "").strip()
    if mot:
        st.caption(mot)

    if primary_block is not None and entry_state != "empty":
        step_label = _card._BLOCK_LABEL.get(str(primary_block.get("type") or "").strip(), "Шаг")
        step_line = _card._block_concept_line(primary_block)
        badge = _card.block_badge_label(primary_block)
        title = f"**Следующий шаг:** {step_label}"
        if step_line:
            title += f" — {step_line}"
        st.caption(f"[{badge}]")
        st.markdown(title)
        st.caption(_card.build_plan_step_reason(primary_block))
    else:
        st.info("На сегодня в плане ещё нет готового шага. Можно начать с тьютора и собрать следующий шаг из текущей темы.")

    a1, a2, a3 = st.columns(3)
    with a1:
        if primary_block is not None and st.button(
            "Начать следующий шаг",
            key=f"{key_prefix}_start",
            type="primary",
            width='stretch',
        ):
            _card.launch_tutor_for_plan_block(primary_block, action_label="Adaptive Plan Hub")
        elif primary_block is None and st.button(
            "Открыть тьютора",
            key=f"{key_prefix}_open_tutor",
            type="primary",
            width='stretch',
        ):
            _card.go_tutor_with_prompt(
                "Помоги определить подходящий учебный шаг на сегодня.",
                None,
                action_label="Adaptive Plan Empty State",
            )
    with a2:
        if st.button("Развернуть план", key=f"{key_prefix}_open_full", width='stretch'):
            _card.request_home_full_plan_expanded()
            st.rerun()
    with a3:
        if st.button("📊 Мой прогресс", key=f"{key_prefix}_progress", width='stretch'):
            st.session_state["current_view"] = "Прогресс обучения"
            st.rerun()

    _fc_n = 0
    _due_sm2 = 0
    _quiz_fb = None
    _has_read_adp = False
    _weak_adp: list[str] = []
    _t_snap: dict[str, Any] | None = None
    _steer_local_adp: str | None = None
    try:
        from app import user_state as _user_state_adp
        from app.learner_state_scope import weak_concepts_for_kg as _weak_for_kg_adp
        from app.knowledge_service import get_active_knowledge_graph as _get_kg_adp
        from app.spaced_repetition import count_due_reviews as _count_due_sm2

        _kg_adp = _get_kg_adp()
        _fc_n = int(_user_state_adp.count_due_flashcards())
        _due_sm2 = int(_count_due_sm2())
        _t_snap = _user_state_adp.get_tutor_learning_resume()
        if isinstance(_t_snap, dict):
            _qf = _t_snap.get("quiz_feedback")
            if isinstance(_qf, dict):
                _quiz_fb = str(_qf.get("status") or "").strip() or None
        try:
            _has_read_adp = _user_state_adp.get_latest_resume() is not None
        except Exception:  # noqa: BLE001 - optional local resume lookup must not hide the hub.
            _has_read_adp = False
        _weak_adp = _weak_for_kg_adp(_kg_adp, threshold=60, limit=12)
        _steer_local_adp = _user_state_adp.get_smart_study_steering_preference() or None
    except Exception:  # noqa: BLE001 - optional SSR inputs must not block the plan hub.
        pass
    la_hub = st.session_state.get("last_answer")
    _has_qa_adp = bool(
        isinstance(la_hub, dict)
        and (
            str(la_hub.get("question") or "").strip()
            or str(la_hub.get("answer") or "").strip()
        )
    )
    _t_topic_adp = str((_t_snap or {}).get("topic") or "").strip()
    _t_sid_adp = str((_t_snap or {}).get("session_id") or "").strip()
    from app.ui.resume_cards_smart_study import (
        ladder_kwargs_for_build,
        remember_ssr_primary_nav,
        render_concept_recovery_ladder_status_ui,
    )

    render_concept_recovery_ladder_status_ui()
    _ss_plan = build_smart_study_recommendation(
        surface="adaptive_plan",
        flashcard_due_n=_fc_n,
        sm2_due_n=_due_sm2,
        quiz_feedback_status=_quiz_fb,
        has_tutor_resume=bool(_t_topic_adp),
        tutor_topic=_t_topic_adp or None,
        has_last_answer_qa=_has_qa_adp,
        has_reading_resume=_has_read_adp,
        first_weak_concept=_weak_adp[0] if _weak_adp else None,
        plan_primary_block=primary_block if isinstance(primary_block, dict) else None,
        **ladder_kwargs_for_build(
            current_anchor=_t_topic_adp or None,
            quiz_feedback_status=_quiz_fb,
        ),
    )
    remember_ssr_primary_nav(_ss_plan.primary_nav)
    _adp_evidence = build_smart_study_evidence_ledger_lines(
        flashcard_due_n=_fc_n,
        sm2_due_n=_due_sm2,
        quiz_feedback_status=_quiz_fb,
        has_last_answer_qa=_has_qa_adp,
        last_answer=la_hub if isinstance(la_hub, dict) else None,
        tutor_trust=None,
        defer_applied=False,
        trust_branch_applied=False,
        steering_local=_steer_local_adp,
        include_all=False,
    )
    # B2 compass: compact status line above plan route shell
    try:
        from app.ui.learning_compass import render_learning_compass
        render_learning_compass(_ss_plan)
    except Exception:  # noqa: BLE001
        pass
    _card.render_smart_study_next_step_card(
        _ss_plan,
        key_prefix=f"{key_prefix}_adp_ss",
        tutor_session_id=_t_sid_adp or None,
        tutor_topic=_t_topic_adp or None,
        plan_block=primary_block if isinstance(primary_block, dict) else None,
        weak_concept=_weak_adp[0] if _weak_adp else None,
        show_primary_button=True,
        evidence_ledger=_adp_evidence,
        has_last_answer_qa_for_steering=_has_qa_adp,
        defer_was_applied_for_steering=False,
    )

    if st.session_state.get("home_adp_full_expanded"):
        preview = rendered_blocks[: max(1, int(preview_limit))]
    else:
        preview = []
    if preview:
        _card.render_plan_concepts_delta_ui(plan)
        _card.render_recent_adaptive_plan_history()
        st.markdown("**Ближайшие шаги**")
        # W9b: at most 2 columns (not 4 narrow ones); XP internals stay out of preview.
        for row_start in range(0, len(preview), 2):
            chunk = preview[row_start : row_start + 2]
            cols = st.columns(len(chunk))
            for col, (block_index, raw) in zip(cols, chunk):
                bt = str(raw.get("type") or "").strip()
                title = _card._BLOCK_LABEL.get(bt, bt or "шаг")
                badge = _card.block_badge_label(raw)
                with col:
                    with st.container(border=True):
                        st.caption(f"[{badge}]")
                        st.markdown(f"**{block_index + 1}. {title}**")
                        line = _card._block_concept_line(raw)
                        if line:
                            st.caption(line[:90])
                        try:
                            from app.ui.source_address import address_from_mapping

                            addr = address_from_mapping(raw)
                            if addr and addr != "—":
                                st.caption(f"📍 {addr}")
                        except Exception:  # noqa: BLE001
                            pass
                        reason = str(
                            raw.get("worth_reason")
                            or raw.get("reason")
                            or raw.get("why")
                            or ""
                        ).strip()
                        if reason:
                            st.caption(f"потому что: {reason[:120]}")
                        st.caption(f"⏱ ~{raw.get('duration_min', 5)} мин")
                        if st.button(
                            "В чат",
                            key=f"{key_prefix}_preview_{block_index}",
                            width="stretch",
                        ):
                            _card.launch_tutor_for_plan_block(
                                raw, action_label="Adaptive Plan Hub"
                            )
    elif st.session_state.get("home_adp_full_expanded"):
        st.caption("На сегодня пока нет дополнительных шагов сверх главного next step.")

    st.markdown("</div></div>", unsafe_allow_html=True)
