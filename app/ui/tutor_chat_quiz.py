"""Quiz surfaces for tutor chat."""

from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from app.ui.continuity_bridge import e24_five_min_closure_combined_ru
from app.ui.session_state import (
    MICRO_QUIZ_RECEIPT_BASELINES_KEY,
    PENDING_CURRENT_VIEW_KEY,
    PROGRESS_FOCUS_SECTION_KEY,
    PROGRESS_FOCUS_STREAK_WEEKLY,
    persist_tutor_mastery_level,
)
from app.ui.tutor_chat_actions import micro_quiz_letter_from_choice, micro_quiz_status_ru
from app.ui.tutor_chat_render import render_tutor_action_panel
from app.ui.tutor_mastery_ui import render_tutor_mastery_microbar


def apply_micro_quiz_progress_deferred_nav(session: dict) -> None:
    """Deferred Progress nav from micro-quiz receipt CTA (pure session dict, no Streamlit)."""
    session[PENDING_CURRENT_VIEW_KEY] = "Прогресс обучения"
    session[PROGRESS_FOCUS_SECTION_KEY] = PROGRESS_FOCUS_STREAK_WEEKLY


def _micro_quiz_receipt_baseline_valid(baseline: Any, scope_key: str) -> bool:
    from app.quiz_micro_receipt import MICRO_QUIZ_RECEIPT_BASELINE_TTL_SEC
    import time

    if not isinstance(baseline, dict):
        return False
    if str(baseline.get("scope_key") or "") != (scope_key or "").strip():
        return False
    try:
        age = time.time() - float(baseline.get("ts") or 0)
    except (TypeError, ValueError):
        return False
    return 0 <= age <= MICRO_QUIZ_RECEIPT_BASELINE_TTL_SEC


def _ensure_micro_quiz_receipt_baseline(scope_key: str, *, topic: str = "") -> None:
    from app.quiz_micro_receipt import capture_micro_quiz_receipt_baseline

    baselines = st.session_state.setdefault(MICRO_QUIZ_RECEIPT_BASELINES_KEY, {})
    if not isinstance(baselines, dict):
        baselines = {}
        st.session_state[MICRO_QUIZ_RECEIPT_BASELINES_KEY] = baselines
    existing = baselines.get(scope_key)
    if _micro_quiz_receipt_baseline_valid(existing, scope_key):
        return
    baselines[scope_key] = capture_micro_quiz_receipt_baseline(scope_key, topic=topic)


def _build_micro_quiz_after_metrics(
    *,
    topic: str,
    recommended_next: dict[str, Any] | None,
) -> dict[str, Any]:
    from app.quiz_micro_receipt import build_micro_quiz_metric_dict_live

    after = build_micro_quiz_metric_dict_live(topic=topic)
    if isinstance(recommended_next, dict):
        next_act = str(recommended_next.get("next_action") or "").strip()
        if next_act:
            after["plan_teaser"] = next_act
    return after


def _render_micro_quiz_progress_receipt_and_cta(
    *,
    scope_key: str,
    topic: str,
    feedback_status: str | None,
    recommended_next: dict[str, Any] | None,
    cta_key: str,
) -> None:
    from app.quiz_micro_receipt import (
        build_micro_quiz_receipt_html,
        build_micro_quiz_receipt_lines,
    )

    baselines = st.session_state.get(MICRO_QUIZ_RECEIPT_BASELINES_KEY)
    if not isinstance(baselines, dict):
        return
    baseline = baselines.get(scope_key)
    if not _micro_quiz_receipt_baseline_valid(baseline, scope_key):
        return

    after = _build_micro_quiz_after_metrics(topic=topic, recommended_next=recommended_next)
    lines, measurable = build_micro_quiz_receipt_lines(
        baseline,
        after,
        feedback_status=feedback_status,
    )
    receipt_html = build_micro_quiz_receipt_html(
        lines,
        measurable=measurable,
        feedback_status=feedback_status,
    )
    st.markdown(receipt_html, unsafe_allow_html=True)
    if st.button(
        "Посмотреть в Progress",
        key=cta_key,
        type="primary",
        width="stretch",
    ):
        apply_micro_quiz_progress_deferred_nav(st.session_state)
        st.rerun()
    baselines.pop(scope_key, None)


def _render_smart_study_after_failed_quiz(
    *,
    session_id: str,
    msg_idx: int,
    quiz_feedback: dict[str, Any] | None,
    topic_hint: str | None,
    key_prefix: str,
) -> None:
    """US-20: после неверного ответа — актуальный SSR с живым статусом квиза (до записи в resume)."""
    if not isinstance(quiz_feedback, dict):
        return
    st_norm = str(quiz_feedback.get("status") or "").strip().lower()
    if st_norm in ("correct", "ok", "good", "right"):
        return
    try:
        from app import user_state as _us
        from app.spaced_repetition import count_due_reviews as _cdr
        from app.ui.adaptive_plan_card import (
            build_smart_study_recommendation,
            render_smart_study_next_step_card,
        )

        fc_n = int(_us.count_due_flashcards())
        due_n = int(_cdr())
        qf = str(quiz_feedback.get("status") or "").strip() or None
        tt = str(st.session_state.get("current_topic") or "").strip() or None
        th = str(topic_hint or "").strip() or None
        focus = th or tt
        last_a = st.session_state.get("last_answer")
        has_qa = bool(
            isinstance(last_a, dict)
            and (
                str(last_a.get("question") or "").strip()
                or str(last_a.get("answer") or "").strip()
            )
        )
        from app.ui.resume_cards_smart_study import (
            ladder_kwargs_for_build,
            remember_ssr_primary_nav,
            render_concept_recovery_ladder_status_ui,
            seed_concept_recovery_ladder_on_quiz_failed,
        )

        seed_concept_recovery_ladder_on_quiz_failed(topic_anchor=focus)
        render_concept_recovery_ladder_status_ui()
        rec = build_smart_study_recommendation(
            surface="tutor_chat",
            flashcard_due_n=fc_n,
            sm2_due_n=due_n,
            quiz_feedback_status=qf,
            has_tutor_resume=bool(focus),
            tutor_topic=focus,
            has_last_answer_qa=has_qa,
            has_reading_resume=False,
            first_weak_concept=None,
            plan_primary_block=None,
            **ladder_kwargs_for_build(
                current_anchor=focus,
                quiz_feedback_status=qf,
            ),
        )
        remember_ssr_primary_nav(rec.primary_nav)
        render_smart_study_next_step_card(
            rec,
            key_prefix=f"{key_prefix}_ssr_fail_{msg_idx}",
            tutor_topic=focus,
            weak_concept=th,
            show_primary_button=True,
        )
    except Exception as exc:  # noqa: BLE001 - optional enrichment; не ломаем квиз.
        logging.getLogger(__name__).debug("smart study after failed quiz: %s", exc)


def render_unified_auto_quiz_card(
    auto_quiz: dict[str, Any],
    msg_idx: int,
    session_id: str,
) -> None:
    """Unified Auto-Loop: one micro-card after tutor answer."""
    from app.quiz_service import process_micro_quiz_outcome, topic_from_last_user_message
    from app.session_store import session_store

    raw = auto_quiz.get("quiz") or {}
    questions: list[dict[str, Any]] = []
    if isinstance(raw, dict) and isinstance(raw.get("questions"), list):
        questions = [q for q in raw["questions"] if isinstance(q, dict)]
    elif isinstance(raw, dict) and raw.get("question"):
        questions = [raw]
    if not questions:
        return

    qd = questions[0]
    opts = qd.get("options")
    if not isinstance(opts, list) or len(opts) != 4:
        return

    topic = topic_from_last_user_message(session_store.get(session_id)) or "general"
    mastery = str(st.session_state.get("tutor_mastery_level", "intermediate"))
    base = f"auto_quiz_u_{session_id[:12]}_{msg_idx}"
    sk = f"{base}_q0"
    state_keys = (f"{sk}_done", f"{sk}_fb", f"{sk}_full")

    def _queue_followup(prompt: str | None = None) -> None:
        if prompt and str(prompt).strip():
            st.session_state["tutor_pending_prompt"] = str(prompt).strip()
            st.session_state["tutor_pending_session_id"] = session_id
        for k in state_keys:
            st.session_state.pop(k, None)
        st.rerun()

    if st.session_state.pop(f"{base}_confetti", None):
        st.balloons()
        st.success("🔥 3 правильных подряд — супер стрик!")
    if st.session_state.pop(f"{base}_g_balloons", None):
        st.balloons()
        st.success("🎉 LEVEL UP! Новый уровень — загляните в «Мой прогресс».")
    _badge_list = st.session_state.pop(f"{base}_g_badges", None)
    if _badge_list:
        for _b in _badge_list:
            _lab = _b.get("label") if isinstance(_b, dict) else str(_b)
            try:
                st.toast(f"🏆 Новый бейдж: {_lab}")
            except Exception as exc:  # noqa: BLE001 - toast is optional.
                logging.getLogger(__name__).debug("Toast failed: %s", exc)
                st.caption(f"🏆 Новый бейдж: {_lab}")

    with st.container(border=True):
        st.caption("Unified Auto-Loop")
        mot = (auto_quiz.get("motivational_message") or "").strip()
        st.markdown("---")
        if mot:
            st.markdown(mot)
        next_level_hint = None
        full_hint = st.session_state.get(f"{sk}_full")
        if isinstance(full_hint, dict):
            rn_hint = full_hint.get("recommended_next")
            if isinstance(rn_hint, dict):
                next_level_hint = rn_hint.get("new_mastery_estimate")
        render_tutor_mastery_microbar(mastery, str(next_level_hint or mastery))
        st.markdown(f"**Вопрос:** {qd.get('question', '')}")

        done = bool(st.session_state.get(f"{sk}_done"))
        fb = st.session_state.get(f"{sk}_fb")
        full = st.session_state.get(f"{sk}_full")

        if done and isinstance(fb, dict):
            st.markdown(f"**Результат:** {micro_quiz_status_ru(fb.get('status'))}")
            if fb.get("status") == "correct":
                st.success(fb.get("message") or "Верно.")
            else:
                st.error(fb.get("message") or "Неверно.")
            if isinstance(full, dict) and full.get("retention_line"):
                st.info(full["retention_line"])
            expl = (qd.get("explanation") or "").strip()
            if expl:
                st.caption(f"Разбор: {expl}")
            rn = full.get("recommended_next") if isinstance(full, dict) else None
            if isinstance(rn, dict):
                next_act = str(rn.get("next_action") or "").strip()
                next_reason = str(rn.get("next_action_reason") or "").strip()
                if next_act or next_reason:
                    st.caption(
                        f"Что дальше: **{next_act or 'Продолжить'}**"
                        + (f" — {next_reason}" if next_reason else "")
                    )

            _render_micro_quiz_progress_receipt_and_cta(
                scope_key=sk,
                topic=topic,
                feedback_status=str(fb.get("status") or "").strip() or None,
                recommended_next=rn if isinstance(rn, dict) else None,
                cta_key=f"{sk}_progress_cta",
            )

            _render_smart_study_after_failed_quiz(
                session_id=session_id,
                msg_idx=msg_idx,
                quiz_feedback=fb,
                topic_hint=topic,
                key_prefix=f"auto_quiz_u_{session_id[:12]}_{msg_idx}",
            )

            _e11_unified_target = st.session_state.get("tutor_e11_five_min_unified_msg_idx")
            if _e11_unified_target is not None and int(_e11_unified_target) == int(msg_idx):
                try:
                    from app.user_state import get_weekly_goals_state

                    st.info(
                        e24_five_min_closure_combined_ru(
                            get_weekly_goals_state(),
                            tutor_goal_desired_outcome=st.session_state.get(
                                "tutor_goal_desired_outcome"
                            ),
                            current_topic=st.session_state.get("current_topic"),
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - UI fallback.
                    logging.getLogger(__name__).debug("Weekly goals fetch failed: %s", exc)
                    st.caption(
                        e24_five_min_closure_combined_ru(
                            None,
                            tutor_goal_desired_outcome=st.session_state.get(
                                "tutor_goal_desired_outcome"
                            ),
                            current_topic=st.session_state.get("current_topic"),
                        )
                    )
                st.session_state.pop("tutor_e11_five_min_unified_msg_idx", None)

            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("Вспомнил", key=f"{base}_remembered", width='stretch'):
                    _queue_followup(
                        "Задай ещё один короткий вопрос для самопроверки по теме только что обсуждённого, "
                        "чуть иначе и без повторения формулировки."
                    )
            with c2:
                if st.button("Понял", key=f"{base}_got", width='stretch', type="secondary"):
                    next_prompt = None
                    if isinstance(rn, dict):
                        next_prompt = str(rn.get("next_action") or "").strip() or None
                    _queue_followup(next_prompt or "Следующий шаг")
            with c3:
                if st.button("Трудно", key=f"{base}_hard", width='stretch'):
                    _queue_followup(
                        "Объясни эту идею ещё раз проще, коротко, с одним наглядным примером, "
                        "а потом задай один новый контрольный вопрос."
                    )
            return

        _ensure_micro_quiz_receipt_baseline(sk, topic=topic)

        choice = st.radio(
            "Варианты",
            [str(o) for o in opts],
            index=None,
            key=f"{sk}_radio",
            label_visibility="collapsed",
        )
        hint_flag_key = f"{sk}_hint_visible"
        expl_raw = (qd.get("explanation") or "").strip()
        hint_direct = (qd.get("hint") or "").strip()
        if st.button("Подсказка", key=f"{sk}_hint_btn", type="secondary"):
            st.session_state[hint_flag_key] = True
        if st.session_state.get(hint_flag_key):
            hint_body = hint_direct
            if not hint_body and expl_raw:
                hint_body = expl_raw.split(".")[0] + "." if "." in expl_raw else expl_raw[:140] + "…"
            if not hint_body:
                hint_body = "Сопоставьте вопрос с вариантами и исключите заведомо несовместимые ответы."
            st.info(f"💡 {hint_body}")
        st.caption("Подсказка не засчитывается как ответ (US-5.2).")

        if st.button("Ответить", key=f"{sk}_go", type="primary"):
            if choice is None:
                st.warning("Сначала выберите вариант ответа.")
            else:
                letter = micro_quiz_letter_from_choice(choice, [str(o) for o in opts])
                if not letter or letter not in "ABCD":
                    st.warning("Сначала выберите вариант ответа.")
                else:
                    full_out = process_micro_quiz_outcome(
                        qd,
                        letter,
                        current_topic=topic,
                        current_mastery=mastery,
                        session_id=session_id,
                    )
                    from app.ui.resume_cards_smart_study import (
                        maybe_clear_concept_recovery_ladder_on_variant_quiz_success,
                        seed_concept_recovery_ladder_on_quiz_failed,
                    )

                    _gam = full_out.get("gamification") or {}
                    if _gam.get("level_up"):
                        st.session_state[f"{base}_g_balloons"] = True
                    if _gam.get("new_badges"):
                        st.session_state[f"{base}_g_badges"] = _gam["new_badges"]
                    st.session_state[f"{sk}_done"] = True
                    st.session_state[f"{sk}_fb"] = full_out.get("quiz_feedback")
                    st.session_state[f"{sk}_full"] = full_out
                    qfb = full_out.get("quiz_feedback") or {}
                    if isinstance(qfb, dict) and str(qfb.get("status") or "").strip().lower() not in (
                        "correct",
                        "ok",
                        "good",
                        "right",
                    ):
                        seed_concept_recovery_ladder_on_quiz_failed(topic_anchor=topic)
                    maybe_clear_concept_recovery_ladder_on_variant_quiz_success(
                        quiz_feedback=qfb if isinstance(qfb, dict) else None,
                        quiz_concept=topic,
                    )
                    streak_key = f"tutor_unified_streak_{session_id}"
                    if qfb.get("status") == "correct":
                        nxt = int(st.session_state.get(streak_key, 0)) + 1
                        if nxt >= 3:
                            st.session_state[f"{base}_confetti"] = True
                            st.session_state[streak_key] = 0
                        else:
                            st.session_state[streak_key] = nxt
                    else:
                        st.session_state[streak_key] = 0
                    rn = full_out.get("recommended_next")
                    if isinstance(rn, dict):
                        nme = rn.get("new_mastery_estimate")
                        if nme:
                            persist_tutor_mastery_level(str(nme))
                    from app.ui.latency_budget_sync import sync_latency_budget_from_payload

                    sync_latency_budget_from_payload(full_out)
                    st.rerun()


def render_tutor_micro_quiz_block(active: dict[str, Any], session_id: str) -> None:
    """Single-question micro-quiz + outcome and next steps."""
    from app.quiz_service import process_micro_quiz_outcome
    from app.user_state import save_micro_quiz_outcome

    qd = active.get("quiz_data") or {}
    if not isinstance(qd, dict):
        st.warning("Нет данных мини-квиза.")
        return
    opts = qd.get("options")
    if not isinstance(opts, list) or len(opts) != 4:
        st.warning("Некорректный формат вопроса.")
        return

    topic = str(active.get("topic") or "general").strip() or "general"
    answered = bool(active.get("answered"))
    fb = active.get("feedback")
    rn = active.get("recommended_next")

    st.markdown("**Мини-проверка понимания**")
    st.write(qd.get("question") or "")

    if answered and isinstance(fb, dict):
        _sid8 = session_id[:8]
        if st.session_state.pop(f"tutor_mq_balloons_{_sid8}", None):
            st.balloons()
            st.success("🎉 LEVEL UP!")
        _tb = st.session_state.pop(f"tutor_mq_badges_{_sid8}", None)
        if _tb:
            for _b in _tb:
                _lab = _b.get("label") if isinstance(_b, dict) else str(_b)
                try:
                    st.toast(f"🏆 Новый бейдж: {_lab}")
                except Exception as exc:  # noqa: BLE001 - toast is optional.
                    logging.getLogger(__name__).debug("Toast failed: %s", exc)
                    st.caption(f"🏆 Новый бейдж: {_lab}")
        st.markdown(f"**Результат:** {micro_quiz_status_ru(fb.get('status'))}")
        if fb.get("status") == "correct":
            st.success(fb.get("message") or "Верно.")
        else:
            st.warning(fb.get("message") or "Неверно.")
            if fb.get("recommended_action"):
                st.caption(f"Подсказка: {fb['recommended_action']}")
        _qexpl = str(active.get("question_explanation") or "").strip()
        if _qexpl:
            st.caption(f"Пояснение к правильному ответу: {_qexpl}")
        _gline = (active.get("retention_line") or "").strip()
        if _gline:
            st.caption(_gline)
        if isinstance(rn, dict):
            st.info(
                f"**Что дальше:** {rn.get('next_action', '')}\n\n"
                f"{rn.get('next_action_reason', '')}"
            )
            tp = rn.get("topic_progress")
            if tp:
                st.caption(tp)
            ctas = rn.get("suggested_ctas")
            if isinstance(ctas, list) and ctas:
                render_tutor_action_panel(
                    ctas,
                    msg_idx=int(active.get("msg_idx", 0)),
                    session_id=session_id,
                    next_action=rn.get("next_action"),
                )
            if active.get("e11_five_min_loop"):
                try:
                    from app.user_state import get_weekly_goals_state

                    st.info(
                        e24_five_min_closure_combined_ru(
                            get_weekly_goals_state(),
                            tutor_goal_desired_outcome=st.session_state.get(
                                "tutor_goal_desired_outcome"
                            ),
                            current_topic=st.session_state.get("current_topic"),
                        )
                    )
                except Exception as exc:  # noqa: BLE001 - fallback copy only.
                    logging.getLogger(__name__).debug("Weekly goals fetch failed: %s", exc)
                    st.caption(
                        e24_five_min_closure_combined_ru(
                            None,
                            tutor_goal_desired_outcome=st.session_state.get(
                                "tutor_goal_desired_outcome"
                            ),
                            current_topic=st.session_state.get("current_topic"),
                        )
                    )
        _tutor_mq_scope = f"tutor_mq_{session_id[:8]}"
        _render_micro_quiz_progress_receipt_and_cta(
            scope_key=_tutor_mq_scope,
            topic=topic,
            feedback_status=str(fb.get("status") or "").strip() or None,
            recommended_next=rn if isinstance(rn, dict) else None,
            cta_key=f"tutor_mq_progress_cta_{session_id[:8]}",
        )
        _render_smart_study_after_failed_quiz(
            session_id=session_id,
            msg_idx=int(active.get("msg_idx", 0)),
            quiz_feedback=fb if isinstance(fb, dict) else None,
            topic_hint=topic,
            key_prefix=f"tutor_mq_{session_id[:8]}",
        )
        if st.button("Закрыть мини-проверку", key=f"tutor_mq_close_{session_id[:8]}"):
            st.session_state.pop("tutor_micro_quiz_active", None)
            st.rerun()
        return

    _ensure_micro_quiz_receipt_baseline(f"tutor_mq_{session_id[:8]}", topic=topic)

    mq_hint_key = f"tutor_mq_hint_{session_id[:8]}"
    expl_mq = (qd.get("explanation") or "").strip()
    hint_mq = (qd.get("hint") or "").strip()
    if st.button("Подсказка", key=f"tutor_mq_hint_btn_{session_id[:8]}", type="secondary"):
        st.session_state[mq_hint_key] = True
    if st.session_state.get(mq_hint_key):
        _hb = hint_mq
        if not _hb and expl_mq:
            _hb = expl_mq.split(".")[0] + "." if "." in expl_mq else expl_mq[:140] + "…"
        if not _hb:
            _hb = "Сопоставьте вопрос с вариантами и исключите заведомо несовместимые ответы."
        st.info(f"💡 {_hb}")
    st.caption("Подсказка не засчитывается как ответ (US-5.2).")

    choice = st.radio(
        "Выберите вариант:",
        [str(o) for o in opts],
        index=None,
        key=f"tutor_mq_radio_{session_id[:8]}",
    )
    if st.button("Ответить", type="primary", key=f"tutor_mq_submit_{session_id[:8]}"):
        if choice is None:
            st.warning("Сначала выберите вариант ответа.")
        else:
            letter = micro_quiz_letter_from_choice(choice, [str(o) for o in opts])
            if not letter or letter not in "ABCD":
                st.warning("Сначала выберите вариант ответа.")
            else:
                mastery = st.session_state.get("tutor_mastery_level", "intermediate")
                full = process_micro_quiz_outcome(
                    qd,
                    letter,
                    current_topic=topic,
                    current_mastery=str(mastery),
                    session_id=session_id,
                )
                from app.ui.resume_cards_smart_study import (
                    maybe_clear_concept_recovery_ladder_on_variant_quiz_success,
                    seed_concept_recovery_ladder_on_quiz_failed,
                )

                result = full["quiz_feedback"]
                if isinstance(result, dict) and str(result.get("status") or "").strip().lower() not in (
                    "correct",
                    "ok",
                    "good",
                    "right",
                ):
                    seed_concept_recovery_ladder_on_quiz_failed(topic_anchor=topic)
                maybe_clear_concept_recovery_ladder_on_variant_quiz_success(
                    quiz_feedback=result if isinstance(result, dict) else None,
                    quiz_concept=topic,
                )
                recommended_next = full["recommended_next"]
                _gam = full.get("gamification") or {}
                _sid8 = session_id[:8]
                if _gam.get("level_up"):
                    st.session_state[f"tutor_mq_balloons_{_sid8}"] = True
                if _gam.get("new_badges"):
                    st.session_state[f"tutor_mq_badges_{_sid8}"] = _gam["new_badges"]
                save_micro_quiz_outcome(
                    topic=topic,
                    quiz_feedback=result,
                    recommended_next=recommended_next,
                )
                active["answered"] = True
                active["feedback"] = result
                active["recommended_next"] = recommended_next
                active["retention_line"] = full.get("retention_line") or ""
                active["question_explanation"] = str(full.get("explanation") or "").strip()
                nme = recommended_next.get("new_mastery_estimate")
                if nme:
                    persist_tutor_mastery_level(str(nme))
                from app.ui.latency_budget_sync import sync_latency_budget_from_payload

                sync_latency_budget_from_payload(full)
                st.session_state["tutor_micro_quiz_active"] = active
                st.rerun()
