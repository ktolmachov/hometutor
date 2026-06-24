"""Tutor and reading resume cards for the home surface."""
from __future__ import annotations

import uuid
from typing import Any

import streamlit as st

from app import user_state
from app.due_queue_display import due_queue_preview_caption
from app.knowledge_service import get_active_knowledge_graph
from app.learner_state_scope import count_due_reviews_for_kg
from app.ui.helpers import build_tutor_orchestration_summary, esc_html
from app.ui.index_labels import index_version_label
from app.ui.resume_cards_due import _due_queue_preview_rows
from app.ui.resume_cards_smart_study import (
    gather_smart_study_router_session_context,
    render_smart_study_router_strip_from_session_context,
)

def topic_id_from_resume(resume: dict) -> str | None:
    rid = resume.get("resource_id") or ""
    rt = resume.get("resource_type")
    if rt == "topic" and isinstance(rid, str) and rid.startswith("topic:"):
        return rid.split(":", 1)[1]
    if rt == "learning_plan" and isinstance(rid, str) and rid.startswith("plan:"):
        return rid.split(":", 1)[1]
    return None



def recommended_next_from_tutor_decision(decision: dict[str, Any]) -> dict[str, Any]:
    action = decision.get("action") if isinstance(decision.get("action"), dict) else {}
    ctas = action.get("suggested_ctas")
    if not isinstance(ctas, list):
        ctas = []
    mastery = str(action.get("new_mastery_estimate") or "intermediate").strip().lower()
    if mastery not in ("beginner", "intermediate", "advanced"):
        mastery = "intermediate"
    return {
        "next_action": str(action.get("next_action") or "").strip() or "Продолжить диалог",
        "next_action_reason": str(action.get("next_action_reason") or "").strip(),
        "suggested_ctas": [str(x).strip() for x in ctas if str(x).strip()],
        "new_mastery_estimate": mastery,
    }


def _enrich_resume_recommended_next_with_orchestration(
    recommended_next: dict[str, Any],
    tutor_payload: dict[str, Any],
) -> dict[str, Any]:
    summary = build_tutor_orchestration_summary(
        orchestration_state=tutor_payload.get("orchestration_state"),
        decision=tutor_payload.get("decision"),
        socratic=tutor_payload.get("socratic"),
        tutor_orchestration_pipeline=tutor_payload.get("tutor_orchestration_pipeline"),
        orchestration_phase=tutor_payload.get("orchestration_phase"),
        orchestration_decision_source=tutor_payload.get("orchestration_decision_source"),
        selected_agent=tutor_payload.get("selected_agent"),
        should_trigger_microquiz=tutor_payload.get("should_trigger_microquiz"),
        policy_clamped=tutor_payload.get("policy_clamped"),
        policy_clamp_reasons=tutor_payload.get("policy_clamp_reasons"),
    )
    out = dict(recommended_next)
    if summary:
        out["orchestration_summary"] = summary
    decision = tutor_payload.get("decision") if isinstance(tutor_payload.get("decision"), dict) else {}
    route = str(decision.get("route") or "").strip()
    focus = str(
        (tutor_payload.get("orchestration_state") or {}).get("current_concept")
        or decision.get("focus_topic")
        or ""
    ).strip()
    if route:
        out["orchestration_route"] = route
    if focus:
        out["orchestration_focus"] = focus
    return out


def persist_tutor_resume_after_tutor_answer(sid: str, index_stats: dict | None = None) -> None:
    """Снимок для главного экрана после ответа тьютора (история уже в session_store)."""
    from app.quiz_service import topic_from_last_user_message
    from app.session_store import session_store
    from app.ui.index_labels import index_version_label
    from app.user_state import upsert_tutor_learning_resume

    if index_stats is None:
        try:
            from app.ui_client import load_index_stats

            index_stats = load_index_stats()
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            index_stats = None
    iv_label = index_version_label(index_stats) or None

    msgs = session_store.get(sid)
    topic = (topic_from_last_user_message(msgs) or "").strip() or "Общая тема"
    mastery = st.session_state.get("tutor_mastery_level", "intermediate")
    rn: dict[str, Any] | None = None
    for m in reversed(msgs):
        if m.role == "assistant" and isinstance(m.metadata, dict):
            tutor = m.metadata.get("tutor")
            if isinstance(tutor, dict):
                td2 = tutor.get("decision")
                if isinstance(td2, dict):
                    rn = recommended_next_from_tutor_decision(td2)
                    rn = _enrich_resume_recommended_next_with_orchestration(rn, tutor)
                    break
    if rn is None:
        rn = {
            "next_action": "Продолжить диалог",
            "next_action_reason": "",
            "suggested_ctas": [],
            "new_mastery_estimate": str(mastery),
        }
    due_n = count_due_reviews_for_kg(get_active_knowledge_graph())
    upsert_tutor_learning_resume(
        session_id=sid,
        topic=topic,
        mastery_level=str(mastery),
        last_action_kind="tutor_answer",
        last_action_label="Получен ответ тьютора",
        quiz_feedback=None,
        recommended_next=rn,
        due_reviews_count=due_n,
        index_version=iv_label,
    )


def render_home_continue_unified(index_stats: dict | None) -> None:
    """E9.7 / US-7.3 / E11: один блок с одним primary CTA — guided_primary_home_cta_ru."""
    from app.ui.continuity_bridge import (
        due_reviews_home_teaser_ru,
        guided_primary_home_cta_ru,
        home_continue_priority_lines_ru,
    )

    st.session_state.pop("_e8_hero_resume_active", None)
    st.session_state["_e9_home_continue_shown"] = True

    ctx_ssr = gather_smart_study_router_session_context(index_stats=index_stats)
    kg = ctx_ssr.kg
    due_n = ctx_ssr.sm2_due_n
    flashcard_due_n = ctx_ssr.flashcard_due_n
    effective_tutor_snap = ctx_ssr.effective_tutor_snap
    stale_tutor = ctx_ssr.stale_tutor
    last_ans = ctx_ssr.last_answer
    has_qa = ctx_ssr.has_last_answer_qa
    latest_resume = ctx_ssr.latest_resume
    has_reading = ctx_ssr.has_reading
    weak_concepts = ctx_ssr.weak_concepts
    tutor_topic = ctx_ssr.tutor_topic

    has_mastery_gap = bool(has_reading or has_qa or weak_concepts)

    cta_label, cta_kind = guided_primary_home_cta_ru(
        flashcard_due_n=flashcard_due_n,
        has_tutor_resume=bool(effective_tutor_snap),
        due_n=due_n,
        has_mastery_gap=has_mastery_gap,
    )

    main_pri, sec_pri = home_continue_priority_lines_ru(
        due_n=due_n,
        tutor_topic=tutor_topic,
        has_last_qa=has_qa,
        has_reading=has_reading,
    )
    due_teaser = due_reviews_home_teaser_ru(due_n)

    due_preview_rows: list[dict[str, Any]] = []
    due_preview_text = ""
    first_due_concept = ""
    if due_n > 0:
        due_preview_rows = _due_queue_preview_rows(kg)
        due_preview_text = due_queue_preview_caption(due_preview_rows, due_n)
        if due_preview_rows:
            first_due_concept = str(due_preview_rows[0].get("concept") or "").strip()

    st.markdown(
        """
        <div class="home-dash-card" style="margin-top:0.5rem;margin-bottom:0.75rem;">
        <div class="home-dash-head home-dash-head-continue"><h3 style="margin:0;">📍 Следующий шаг</h3></div>
        <div class="home-dash-body">
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f"**Сейчас важнее:** {main_pri}")
    if sec_pri:
        st.caption(sec_pri)
    if due_teaser:
        st.caption(due_teaser)

    sid = str(effective_tutor_snap.get("session_id") or "").strip() if effective_tutor_snap else ""

    c1, c2 = st.columns([2, 1])
    with c1:
        if cta_kind == "resume" and effective_tutor_snap:
            where = str(effective_tutor_snap.get("last_action_label") or "").strip() or "—"
            tt = esc_html(tutor_topic or "—")
            st.markdown(
                f"**Тьютор:** {tt}  \n**Последнее действие:** {esc_html(where)}",
                unsafe_allow_html=True,
            )
        elif cta_kind == "flashcard_due":
            st.markdown(
                f"**Flashcards:** к повторению **{flashcard_due_n}** карточек — "
                "сессия во вкладке **Flashcards**.",
                unsafe_allow_html=True,
            )
        elif cta_kind == "due_review":
            fc = esc_html(first_due_concept or "—")
            st.markdown(
                f"**Очередь повторений:** **{due_n}** тем(а).  \n"
                f"Следующий по приоритету: **{fc}**.",
                unsafe_allow_html=True,
            )
            if due_preview_text:
                st.caption(f"Короткая очередь: {due_preview_text}")
            elif due_n > 0:
                st.caption("Очередь повторений скоро обновится — можно безопасно продолжить через tutor.")
        elif cta_kind == "mastery_gap" and has_reading and latest_resume:
            resume = latest_resume
            title = str(resume.get("display_title") or "Тема / план")
            rt = resume.get("resource_type")
            body = "Сохранённый прогресс по теме или плану."
            if rt == "learning_plan" and resume.get("step_index") is not None:
                body = f"Остановились на шаге **{int(resume['step_index']) + 1}**."
            elif rt == "topic" and resume.get("progress") is not None:
                pct = round(float(resume["progress"]) * 100)
                body = f"Прогресс по теме: **{pct}%**."
            st.markdown(f"**{esc_html(title)}**  \n{body}", unsafe_allow_html=True)
        elif cta_kind == "mastery_gap" and has_qa and isinstance(last_ans, dict):
            qq = str(last_ans.get("question") or "").strip()
            prev = qq[:120] + ("…" if len(qq) > 120 else "")
            st.markdown(
                f"**Последний вопрос (Q&A):** {esc_html(prev or '—')}",
                unsafe_allow_html=True,
            )
        elif cta_kind == "mastery_gap" and weak_concepts:
            wc = esc_html(weak_concepts[0])
            st.markdown(
                f"Есть зона роста по квизам — начните с концепта **{wc}**.",
                unsafe_allow_html=True,
            )
        else:
            st.info(
                "Короткая сессия без лишнего: **5 минут** на один понятный шаг во вкладке "
                "**Чат с тьютором** (или пример вопроса выше и **Быстрый ответ**)."
            )

    with c2:
        if st.button(
            cta_label,
            key="home_continue_primary",
            width='stretch',
            type="primary",
        ):
            st.session_state["guided_home_primary_action"] = cta_kind
            if cta_kind == "flashcard_due":
                st.session_state["current_view"] = "Flashcards"
                st.session_state["flashcards_subview"] = "review"
                st.session_state["flashcards_review_queue"] = []
                st.rerun()
            elif cta_kind == "resume":
                try:
                    from app.ui_events import track_resume_clicked

                    track_resume_clicked()
                except Exception as _exc:  # noqa: BLE001
                    import logging  # noqa: BLE001
                    logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                    pass
                if sid:
                    st.session_state["tutor_session_id"] = sid
                st.session_state["tutor_cta_action"] = "resume"
                st.session_state["current_topic"] = tutor_topic
                st.session_state["current_view"] = "Чат с тьютором"
                st.rerun()
            elif cta_kind == "due_review":
                try:
                    from app.ui_events import track_due_review_started

                    if first_due_concept:
                        track_due_review_started(first_due_concept)
                except Exception as _exc:  # noqa: BLE001
                    import logging  # noqa: BLE001
                    logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                    pass
                try:
                    from app.user_state import increment_weekly_progress

                    increment_weekly_progress("reviews", 1)
                except Exception as _exc:  # noqa: BLE001
                    import logging  # noqa: BLE001
                    logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                    pass
                if "tutor_session_id" not in st.session_state:
                    st.session_state["tutor_session_id"] = str(uuid.uuid4())
                st.session_state["current_view"] = "Чат с тьютором"
                c = first_due_concept or "текущий концепт"
                st.session_state["tutor_pending_prompt"] = (
                    f"Помоги коротко повторить тему «{c}» (она в очереди интервальных повторений)."
                )
                st.session_state["tutor_pending_session_id"] = st.session_state["tutor_session_id"]
                st.session_state["tutor_cta_action"] = "Повторить сейчас"
                st.session_state["current_topic"] = c
                st.rerun()
            elif cta_kind == "mastery_gap":
                if has_reading and latest_resume:
                    tid = topic_id_from_resume(latest_resume)
                    if tid:
                        st.session_state["active_topic_id"] = tid
                    st.session_state["current_view"] = "Темы"
                    st.session_state["tutor_cta_action"] = "mastery_gap_topics"
                    st.rerun()
                elif has_qa:
                    st.session_state["current_view"] = "Быстрый ответ"
                    st.session_state["tutor_cta_action"] = "mastery_gap_qa"
                    st.rerun()
                else:
                    if "tutor_session_id" not in st.session_state:
                        st.session_state["tutor_session_id"] = str(uuid.uuid4())
                    wc = weak_concepts[0] if weak_concepts else "текущую тему"
                    st.session_state["current_view"] = "Чат с тьютором"
                    st.session_state["tutor_pending_prompt"] = (
                        f"Помоги освоить следующий шаг по концепту «{wc}»: кратко объясни суть и дай одно упражнение."
                    )
                    st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
                    st.session_state["tutor_cta_action"] = "mastery_gap_concept"
                    st.session_state["current_topic"] = wc
                    st.rerun()
            else:
                if "tutor_session_id" not in st.session_state:
                    st.session_state["tutor_session_id"] = str(uuid.uuid4())
                st.session_state["current_view"] = "Чат с тьютором"
                st.session_state["tutor_pending_prompt"] = (
                    "Сделай короткую учебную сессию на 5 минут по одной теме: один концепт, "
                    "микро-пояснение и одно простое упражнение без длинного вступления."
                )
                st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
                st.session_state["tutor_e11_five_min_loop"] = True
                st.session_state["tutor_cta_action"] = "safe_starter_5min"
                st.rerun()

    render_smart_study_router_strip_from_session_context(ctx_ssr, key_prefix="home_ssr")

    if stale_tutor:
        st.warning(
            "Индекс менялся после сохранения снимка — перепроверьте источники при необходимости."
        )
    st.markdown("</div></div>", unsafe_allow_html=True)


def _render_tutor_resume_secondary_only(snap: dict[str, Any], index_stats: dict | None) -> None:
    """После hero-strip: только доп. действия без дублирования основного блока."""
    topic = str(snap.get("topic") or "").strip() or "—"
    sid = str(snap.get("session_id") or "").strip()
    iv = index_version_label(index_stats)
    snap_iv = str(snap.get("index_version") or "").strip()
    stale = bool(iv and snap_iv and snap_iv != iv)

    st.markdown('<div class="home-dash-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="home-dash-head home-dash-head-continue"><h3>🎯 Сессия тьютора</h3></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="home-dash-body">', unsafe_allow_html=True)
    st.caption("Основное действие — кнопка в блоке «Продолжить» на главной выше.")
    if stale:
        st.warning(
            "Индекс менялся после сохранения этого снимка — перепроверьте источники и при необходимости переиндексируйте."
        )
    elif snap_iv:
        st.caption(f"Индекс на момент снимка: `{esc_html(snap_iv)}`")
    st.markdown("</div>", unsafe_allow_html=True)

    c2, c3 = st.columns(2)
    with c2:
        if st.button("🔄 Быстро повторить", key="resume_col_quick", width='stretch'):
            if sid:
                st.session_state["tutor_session_id"] = sid
            st.session_state["current_view"] = "Чат с тьютором"
            st.session_state["tutor_pending_prompt"] = (
                f"Кратко повтори ключевые идеи по теме «{topic}» (без длинного вступления)."
            )
            st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
            st.session_state["tutor_cta_action"] = "Повторить сейчас"
            st.rerun()
    with c3:
        if st.button("🔄 Сменить тему", key="resume_col_new_topic", width='stretch'):
            if sid:
                st.session_state["tutor_session_id"] = sid
            try:
                user_state.clear_tutor_learning_resume()
            except Exception as _exc:  # noqa: BLE001
                import logging  # noqa: BLE001
                logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                pass
            st.session_state["current_topic"] = None
            st.session_state["current_view"] = "Чат с тьютором"
            st.session_state["tutor_pending_prompt"] = (
                "Хочу начать новую тему: с чего начать и какие ключевые понятия разобрать первыми?"
            )
            st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
            st.rerun()
    with st.expander("Начать диалог с чистого листа", expanded=False):
        if st.button("Начать заново (новая сессия чата)", key="resume_col_fresh"):
            try:
                user_state.clear_tutor_learning_resume()
            except Exception as _exc:  # noqa: BLE001
                import logging  # noqa: BLE001
                logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                pass
            st.session_state["tutor_session_id"] = str(uuid.uuid4())
            st.session_state.pop("tutor_micro_quiz_active", None)
            st.session_state.pop("tutor_pending_prompt", None)
            st.session_state.pop("tutor_pending_session_id", None)
            st.session_state["current_view"] = "Чат с тьютором"
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)



def render_tutor_learning_resume_card(index_stats: dict | None) -> None:
    """Карточка «Продолжить чат с тьютором»: снимок из get_tutor_learning_resume() + SQLite."""
    try:
        snap = user_state.get_tutor_learning_resume()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return
    if not snap:
        return

    # Если strip уже показан в hero — не дублируем блок; оставляем вторичные действия.
    if st.session_state.get("_e8_hero_resume_active"):
        _render_tutor_resume_secondary_only(snap, index_stats)
        return

    topic = str(snap.get("topic") or "").strip() or "—"
    where = str(snap.get("last_action_label") or "").strip() or "—"
    mastery = str(snap.get("mastery_level") or "intermediate")
    due_n = int(snap.get("due_reviews_count") or 0)
    due_preview_rows: list[dict[str, Any]] = []
    rn = snap.get("recommended_next") if isinstance(snap.get("recommended_next"), dict) else {}
    next_act = str(rn.get("next_action") or "").strip()
    next_reason = str(rn.get("next_action_reason") or "").strip()
    sid = str(snap.get("session_id") or "").strip()
    qf = snap.get("quiz_feedback") if isinstance(snap.get("quiz_feedback"), dict) else {}
    qstat = str(qf.get("status") or "").strip() or "—"
    iv = index_version_label(index_stats)
    snap_iv = str(snap.get("index_version") or "").strip()
    stale = bool(iv and snap_iv and snap_iv != iv)

    st.markdown('<div class="home-dash-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="home-dash-head home-dash-head-continue"><h3>🎯 Продолжить чат с тьютором</h3></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="home-dash-body">', unsafe_allow_html=True)
    st.markdown(
        f"<p><strong>Тема:</strong> {esc_html(topic)}<br/>"
        f"<strong>Остановились на:</strong> {esc_html(where)}</p>",
        unsafe_allow_html=True,
    )
    if next_act:
        st.caption(f"Рекомендуемое действие: **{next_act}**")
    if next_reason:
        st.caption(next_reason)
    orchestration_summary = rn.get("orchestration_summary")
    if isinstance(orchestration_summary, list) and orchestration_summary:
        preview = []
        for item in orchestration_summary[:4]:
            if not isinstance(item, dict):
                continue
            lbl = str(item.get("label") or "").strip()
            val = str(item.get("value") or "").strip()
            if lbl and val:
                preview.append(f"{esc_html(lbl)}: **{esc_html(val)}**")
        if preview:
            st.caption("Оркестрация (последний ответ): " + " · ".join(preview))
    st.caption(
        f"Mastery (UI): **{esc_html(mastery)}** · К повторению: **{due_n}** · "
        f"Последний мини-quiz: **{esc_html(qstat)}**"
    )
    if due_n > 0:
        due_preview_rows = _due_queue_preview_rows(get_active_knowledge_graph())
        due_preview_text = due_queue_preview_caption(due_preview_rows, due_n)
        if due_preview_text:
            st.caption(f"Короткая очередь: {due_preview_text}")
        else:
            st.caption("Очередь повторений скоро обновится — продолжение с tutor остаётся доступным.")
    if sid:
        st.caption(f"Сессия чата: `{esc_html(sid[:8])}…`")
    if stale:
        st.warning(
            "Индекс менялся после сохранения этого снимка — перепроверьте источники и при необходимости переиндексируйте."
        )
    elif snap_iv:
        st.caption(f"Индекс на момент снимка: `{esc_html(snap_iv)}`")
    st.markdown("</div>", unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("▶️ Продолжить", key="resume_tutor_continue", width='stretch', type="primary"):
            try:
                from app.ui_events import track_resume_clicked

                track_resume_clicked()
            except Exception as _exc:  # noqa: BLE001
                import logging  # noqa: BLE001
                logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                pass
            if sid:
                st.session_state["tutor_session_id"] = sid
            st.session_state["tutor_cta_action"] = "resume"
            st.session_state["current_topic"] = topic
            st.session_state["current_view"] = "Чат с тьютором"
            st.rerun()
    with c2:
        if st.button("🔄 Быстро повторить", key="resume_tutor_quick", width='stretch'):
            if sid:
                st.session_state["tutor_session_id"] = sid
            st.session_state["current_view"] = "Чат с тьютором"
            st.session_state["tutor_pending_prompt"] = (
                f"Кратко повтори ключевые идеи по теме «{topic}» (без длинного вступления)."
            )
            st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
            st.session_state["tutor_cta_action"] = "Повторить сейчас"
            st.rerun()
    with c3:
        if st.button("🔄 Сменить тему", key="resume_tutor_new_topic", width='stretch'):
            if sid:
                st.session_state["tutor_session_id"] = sid
            try:
                user_state.clear_tutor_learning_resume()
            except Exception as _exc:  # noqa: BLE001
                import logging  # noqa: BLE001
                logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                pass
            st.session_state["current_topic"] = None
            st.session_state["current_view"] = "Чат с тьютором"
            st.session_state["tutor_pending_prompt"] = (
                "Хочу начать новую тему: с чего начать и какие ключевые понятия разобрать первыми?"
            )
            st.session_state["tutor_pending_session_id"] = st.session_state.get("tutor_session_id")
            st.rerun()
    with st.expander("Начать диалог с чистого листа", expanded=False):
        if st.button("Начать заново (новая сессия чата)", key="resume_tutor_fresh"):
            try:
                user_state.clear_tutor_learning_resume()
            except Exception as _exc:  # noqa: BLE001
                import logging  # noqa: BLE001
                logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                pass
            st.session_state["tutor_session_id"] = str(uuid.uuid4())
            st.session_state.pop("tutor_micro_quiz_active", None)
            st.session_state.pop("tutor_pending_prompt", None)
            st.session_state.pop("tutor_pending_session_id", None)
            st.session_state["current_view"] = "Чат с тьютором"
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_reading_resume_card(index_stats: dict | None) -> None:
    try:
        resume = user_state.get_latest_resume()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return
    if not resume:
        return
    iv = index_version_label(index_stats)
    stale = bool(iv and resume.get("index_version") and resume.get("index_version") != iv)
    title = str(resume.get("display_title") or "Прогресс обучения")
    rt = resume.get("resource_type")
    step_i = resume.get("step_index")
    label = (resume.get("step_label") or "").strip()
    if rt == "learning_plan" and step_i is not None:
        body = f"Вы остановились на шаге **{int(step_i) + 1}**"
        if label:
            preview = label.replace("\n", " ")[:140]
            body += f": {preview}"
        body += "."
    elif rt == "topic" and resume.get("progress") is not None:
        pct = round(float(resume["progress"]) * 100)
        body = f"Сохранён прогресс по теме: **{pct}%**."
    else:
        body = "Есть сохранённый прогресс — откройте вкладку «Темы», чтобы продолжить."

    st.markdown('<div class="home-dash-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="home-dash-head home-dash-head-continue"><h3>🎯 Продолжить тему или план</h3></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="home-dash-body">', unsafe_allow_html=True)
    st.markdown(f"**{title}**  \n{body}")
    if stale:
        st.caption("Индекс менялся после сохранения — перепроверьте материалы.")
    st.markdown("</div>", unsafe_allow_html=True)
    tid = topic_id_from_resume(resume)
    if st.button("Открыть «Темы»", key="resume_goto_topics", width='stretch', type="primary"):
        if tid:
            st.session_state["active_topic_id"] = tid
        st.session_state["current_view"] = "Темы"
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_continue_empty_card() -> None:
    """Нет tutor-снимка и нет reading resume — приглашение в чат."""
    st.markdown('<div class="home-dash-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="home-dash-head home-dash-head-continue"><h3>🎯 Продолжить обучение</h3></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="home-dash-body">', unsafe_allow_html=True)
    st.info(
        "Пока нет сохранённого прогресса. Для учебного сценария начните с чата с тьютором, "
        "а для широкой темы можно сразу открыть вкладку «Темы»."
    )
    st.markdown("</div>", unsafe_allow_html=True)
    if st.button("🚀 Начать с чата с тьютором", key="resume_empty_goto_tutor", width='stretch', type="primary"):
        if "tutor_session_id" not in st.session_state:
            st.session_state["tutor_session_id"] = str(uuid.uuid4())
        st.session_state["current_view"] = "Чат с тьютором"
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def render_resume_cards(index_stats: dict | None) -> None:
    """Legacy wrapper: на home теперь показываем только continuity-card."""
    render_resume_card(index_stats)


def render_resume_card(index_stats: dict | None) -> None:
    """После E9.7 unified: только доп. действия тьютора; остальное — в ``render_home_continue_unified``."""
    st.session_state.pop("_e8_hero_resume_active", None)
    from app.course_cache import load_last_closed_promise

    lp = load_last_closed_promise()
    if isinstance(lp, dict) and str(lp.get("promise_text") or "").strip():
        st.info(f"**Следующая сессия (курс):** {lp['promise_text']}")
    try:
        snap = user_state.get_tutor_learning_resume()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        snap = None
    if snap:
        _render_tutor_resume_secondary_only(snap, index_stats)


