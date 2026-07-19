"""Smart Study Router card renderer."""
from __future__ import annotations

from typing import Any

import streamlit as st

from app.smart_study_router import SmartStudyRecommendation, finalize_smart_study_confidence_ledger_lines
from app.smart_study_route_simulator import (
    SimulatedRoute,
    simulate_what_if,
)
from app.ui.adaptive_plan_llm_enrichment import _ssr_why_now_for_card, stream_ssr_explanation  # noqa: F401
from app.ui_preferences import feature_visible_by_id


_emitted_route_ids: set[tuple[str, str]] = set()


def _emit_route_offered_if_needed(rec: SmartStudyRecommendation, key_prefix: str) -> None:
    """Emit session-tape route_offered once per (session_id, decision_id)."""
    did = str(rec.decision_id)
    if not did:
        return
    try:
        sid = str(st.session_state.get("_session_tape_id") or "").strip()
        if not sid:
            return
    except Exception:  # noqa: BLE001 - tape must never block UI
        return
    dedupe_key = (sid, did)
    if dedupe_key in _emitted_route_ids:
        return
    _emitted_route_ids.add(dedupe_key)
    try:
        from app.session_tape import append_event

        surface = rec.origin or "home"
        append_event(sid, "route_offered", {
            "surface": surface,
            "primary_nav": str(rec.primary_nav),
            "hint_kind": str(rec.hint_kind),
            "decision_id": did,
            "phase": str(rec.phase),
        })
    except Exception:  # noqa: BLE001 - tape must never block UI
        pass


def render_smart_study_next_step_card(
    rec: SmartStudyRecommendation,
    *,
    key_prefix: str,
    primary_topic_hint: str | None = None,
    tutor_session_id: str | None = None,
    tutor_topic: str | None = None,
    plan_block: dict[str, Any] | None = None,
    weak_concept: str | None = None,
    show_primary_button: bool = False,
    evidence_ledger: list[str] | None = None,
    has_last_answer_qa_for_steering: bool | None = None,
    defer_was_applied_for_steering: bool = False,
    auto_apply_saved_steering: bool = True,
    enable_what_if_preview: bool = True,
) -> None:
    from app.ui import adaptive_plan_card as _card
    from app.ui.adaptive_plan_card import render_ssr_why_now_streaming
    from app.ui.ssr_feedback import render_ssr_feedback_widget

    """Общая explainable-карточка следующего шага (cross-loop UI surfaces)."""
    import html as html_stdlib
    import re

    rec_render = rec
    if auto_apply_saved_steering:
        from app import user_state as _uss

        _hq = has_last_answer_qa_for_steering
        if _hq is None:
            _hq = _card._session_has_last_answer_qa()
        rec_render, _ = _card.apply_smart_study_steering_preference(
            rec,
            steering=_uss.get_smart_study_steering_preference(),
            has_last_answer_qa=bool(_hq),
            defer_was_applied=defer_was_applied_for_steering,
        )

    slot_hint = str(primary_topic_hint or tutor_topic or weak_concept or "").strip() or None

    _emit_route_offered_if_needed(rec_render, key_prefix)

    safe_primary = html_stdlib.escape(rec_render.primary_label_ru)
    safe_hint = html_stdlib.escape(str(rec_render.hint_kind))
    ladder_step_markup = ""
    audit_for_step = str(rec_render.ml_audit_ru or "")
    step_match = re.search(r"recovery_ladder_step=(\d+)", audit_for_step)
    if step_match:
        safe_step = html_stdlib.escape(step_match.group(1))
        ladder_step_markup = (
            f'<span data-testid="e2e-ssr-recovery-ladder-step" '
            f'data-recovery-ladder-step="{safe_step}"></span>'
        )
    dom_base = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in key_prefix)[:48] or "ssr"
    title_id = f"{dom_base}_ssr_title"
    contrast_id = f"{dom_base}_ssr_contrast"
    whynot_id = f"{dom_base}_ssr_why_not_others"
    evidence_id = f"{dom_base}_ssr_evidence"
    pedagogy_line = str(rec_render.route_pedagogy_ru or "").strip()
    pedagogy_id = f"{dom_base}_ssr_pedagogy"
    pedagogy_html = ""
    if pedagogy_line:
        safe_pedagogy = html_stdlib.escape(pedagogy_line)
        pedagogy_html = (
            f'<p id="{pedagogy_id}" data-testid="e2e-ssr-route-pedagogy" '
            'style="opacity:0.94;font-size:0.88rem;margin:0 0 0.35rem 0;">'
            f"<strong>Зачем такой маршрут:</strong> {safe_pedagogy}</p>"
        )
    safe_contrast = html_stdlib.escape(_card.smart_study_contrastive_explanation(rec_render))
    contrast_html = (
        f'<p id="{contrast_id}" data-testid="e2e-ssr-contrast" style="opacity:0.88;font-size:0.85rem;">'
        f"<strong>Если выбрать иначе:</strong> {safe_contrast}</p>"
    )
    safe_whynot = html_stdlib.escape(_card.smart_study_why_not_others_ru(rec_render))
    whynot_html = (
        f'<div id="{whynot_id}" data-testid="e2e-ssr-why-not-others">'
        f'<p style="opacity:0.88;font-size:0.84rem;margin-top:0.2rem;">'
        "<strong>Что с другими режимами:</strong> "
        f"{safe_whynot}</p></div>"
    )
    ledger_lines = list(evidence_ledger or [])
    audit_tail = str(rec_render.ml_audit_ru or "").strip()
    if audit_tail:
        ledger_lines.append(audit_tail)
    ledger_lines = finalize_smart_study_confidence_ledger_lines(
        ledger_lines,
        hint_kind=str(rec_render.hint_kind),
        primary_nav=str(rec_render.primary_nav),
        weak_concept=weak_concept,
    )
    ledger_html = ""
    if ledger_lines and feature_visible_by_id("panel:debug_summary", context_ok=True):
        items_li = "".join(
            f'<li style="margin:0.12rem 0;line-height:1.35;">{html_stdlib.escape(line)}</li>'
            for line in ledger_lines
        )
        ledger_html = (
            f'<div id="{evidence_id}" data-testid="e2e-ssr-evidence" '
            'style="opacity:0.9;font-size:0.82rem;margin-top:0;">'
            "<p style=\"margin:0 0 0.25rem 0;\"><strong>Локальные сигналы подсказки</strong> "
            "(это устройство и индекс; не облачный скоринг и не внешний профиль):</p>"
            f'<ul style="margin:0;padding-left:1.1rem;">{items_li}</ul></div>'
        )

    # ── Part 1: card shell + header + optional primary label + pedagogy ──────
    pre_html = (
        f'<div class="home-dash-card smart-study-next-step" role="region" '
        f'aria-labelledby="{title_id}" data-testid="e2e-smart-study-next-step" '
        f'data-router-hint="{safe_hint}">'
        f'{ladder_step_markup}'
        f'<div class="home-dash-head home-dash-head-continue">'
        f'<h4 id="{title_id}" style="margin:0;">🧭 С чего можно продолжить</h4></div>'
        '<div class="home-dash-body">'
    )
    if not show_primary_button:
        pre_html += f"<p><strong>{safe_primary}</strong></p>"
    pre_html += pedagogy_html
    st.html(pre_html)

    # ── Part 2: streaming short reason ───────────────────────────────────────
    why_now_text = render_ssr_why_now_streaming(
        rec_render,
        evidence_ledger=ledger_lines,
        tutor_topic=tutor_topic,
        weak_concept=weak_concept,
        primary_topic_hint=primary_topic_hint,
    )

    # ── Part 3: contrast + explicit deferred surfaces + evidence ledger ─────
    if contrast_html or whynot_html:
        st.html(contrast_html + whynot_html)
    if ledger_html:
        with st.expander("Локальные сигналы уверенности (confidence ledger)", expanded=False):
            st.html(ledger_html)

    # ── Feedback widget (👍/👎) ───────────────────────────────────────────────
    render_ssr_feedback_widget(
        rec_render, key_prefix=key_prefix, why_now_text=why_now_text, weak_concept=weak_concept
    )

    # ── Primary button ────────────────────────────────────────────────────────
    if show_primary_button:
        btn_label = rec_render.primary_label_ru.strip() or "Продолжить обучение"
        if st.button(
            btn_label,
            key=f"{key_prefix}_ss_primary",
            type="primary",
            width="stretch",
            help=why_now_text,
        ):
            _card.apply_smart_study_primary_navigation(
                rec_render,
                tutor_session_id=tutor_session_id,
                tutor_topic=tutor_topic,
                plan_block=plan_block,
                weak_concept=weak_concept,
            )
    if rec_render.secondaries:
        st.caption(
            "Можно выбрать и другой режим: быстрый ответ, тьютор, quiz, flashcards и прогресс остаются рядом."
        )

        n_sec = len(rec_render.secondaries)
        cols = st.columns(min(4, n_sec))
        for idx, (col, sec) in enumerate(zip(cols, rec_render.secondaries)):
            ss_key = f"{key_prefix}_ss_{sec.action_id}"
            with col:
                if st.button(sec.label_ru, key=ss_key, width="stretch"):
                    _card.apply_smart_study_secondary_navigation(sec.action_id, topic_hint=slot_hint)

        # ── What-if preview row (❓ buttons) ─────────────────────────────────
        if enable_what_if_preview and rec_render.secondaries:
            preview_cols = st.columns(min(4, n_sec))
            for idx2, (pcol, sec) in enumerate(zip(preview_cols, rec_render.secondaries)):
                whatif_key = f"{key_prefix}_ssr_whatif_btn_{sec.action_id}"
                state_key = f"{key_prefix}_ssr_whatif_{sec.action_id}"
                with pcol:
                    is_open = st.session_state.get(state_key, False)
                    icon_label = "✕" if is_open else "❓"
                    if st.button(
                        icon_label,
                        key=whatif_key,
                        help=f"Посмотреть, что будет, если выбрать «{sec.label_ru}»",
                        use_container_width=True,
                    ):
                        # Toggle: close other previews, open this one
                        for other_sec in rec_render.secondaries:
                            other_key = f"{key_prefix}_ssr_whatif_{other_sec.action_id}"
                            st.session_state[other_key] = False
                        st.session_state[state_key] = not st.session_state.get(state_key, False)
                        st.rerun()

            # ── Render active preview ─────────────────────────────────────────
            for sec in rec_render.secondaries:
                state_key = f"{key_prefix}_ssr_whatif_{sec.action_id}"
                if st.session_state.get(state_key, False):
                    sim_result = simulate_what_if(rec_render, sec.action_id)
                    if sim_result.limitation_reason:
                        st.info(sim_result.limitation_reason)
                    else:
                        st.info(
                            f"**Что если выбрать «{sec.label_ru}»:**  \n"
                            f"Рекомендация: **{sim_result.counterfactual_primary_label_ru}**  \n"
                            f"{sim_result.reason_ru}"
                        )
                    # Only show one preview at a time (first match found is shown)
                    break

    st.html("</div></div>")
