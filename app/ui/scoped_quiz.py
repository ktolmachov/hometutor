"""Scoped self-check quiz (MC) после генерации из API."""
from __future__ import annotations

from typing import Any

import streamlit as st

from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
from app.ui.quiz_panel import (
    _cta_route_for_status,
    render_stable_feedback_block,
    short_feedback_explanation,
)
from app.ui_client import fetch_json
import json
import hashlib

_LOOP_METRICS_LABEL = "five_min_loop"


def _record_loop_transition(
    *,
    source_key: str,
    stage: str,
    route: str,
    status: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Best-effort product metric for deterministic loop routing."""
    try:
        from app.metrics import record_knowledge_workflow_event
    except Exception:  # noqa: BLE001 - optional import can fail in tests/offline modes without blocking execution
        return
    event_payload: dict[str, Any] = {
        "metrics_label": _LOOP_METRICS_LABEL,
        "source_key": source_key,
        "stage": stage,
        "route": route,
    }
    if status:
        event_payload["status"] = status
    if isinstance(payload, dict):
        event_payload.update(payload)
    record_knowledge_workflow_event(
        action="learning_loop.next_step",
        knowledge_product_trace={
            "workflow_label": _LOOP_METRICS_LABEL,
            "deterministic_next_step": True,
            "dead_end": False,
        },
        payload=event_payload,
    )

def _status_for_submission(*, is_correct: bool, hint_used: bool) -> str:
    if is_correct:
        return "correct"
    if hint_used:
        return "partial"
    return "incorrect"


def _apply_feedback_cta(route: str, *, source_key: str, question_idx: int) -> None:
    _record_loop_transition(
        source_key=source_key,
        stage="question_feedback",
        route=route,
        payload={"question_idx": question_idx},
    )
    if route == "retry":
        st.session_state[f"{source_key}_next_cta_route"] = "retry"
        st.session_state.pop(f"{source_key}_scoped_{question_idx}", None)
        st.session_state.pop(f"{source_key}_result_{question_idx}", None)
        st.rerun()
    st.session_state[f"{source_key}_next_cta_route"] = route
    if route == "continue_tutor":
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
        st.info("Продолжаем разбор с тьютором.")
        st.rerun()
    elif route == "review":
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Прогресс обучения"
        st.info("Откройте блок повторения, чтобы закрепить тему.")
        st.rerun()
    elif route == "progress":
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Прогресс обучения"
        st.info("Переходим к вашему прогрессу.")
        st.rerun()


def _completion_cta_route(*, pct: int) -> str:
    if pct >= 80:
        return "progress"
    if pct >= 50:
        return "review"
    return "retry"


def render_scoped_self_check_quiz(
    questions: list,
    *,
    source_key: str,
    quiz_meta: dict | None = None,
) -> None:
    """Показ scoped self-check (5–8 MC); по завершении — mastery, SR, streak, XP."""
    if not questions:
        return
    meta = quiz_meta if isinstance(quiz_meta, dict) else {}
    quiz_hash = hashlib.md5(
        json.dumps(questions, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()[:12]
    _stored_hash = st.session_state.get(f"{source_key}_quiz_content_hash")
    if _stored_hash and _stored_hash != quiz_hash:
        _reset_quiz_state_for_source(source_key)
    st.session_state[f"{source_key}_quiz_content_hash"] = quiz_hash
    mot = (meta.get("motivation") or "").strip()
    if mot:
        st.info(mot)
    detail = (meta.get("motivation_detail") or "").strip()
    if detail:
        st.caption(detail)

    submitted_count = 0
    correct_submissions = 0
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            continue
        opts = q.get("options") or []
        try:
            ok_idx = int(q.get("correct_index", 0))
        except (TypeError, ValueError):
            ok_idx = -1
        diff = (q.get("difficulty") or "").strip()
        head = f"**{i + 1}.** {q.get('question', '')}"
        if diff:
            head += f" `({diff})`"
        st.markdown(head)

        # Hint button
        expl = (q.get("explanation") or "").strip()
        hint_key = f"{source_key}_hint_{i}"
        if hint_key not in st.session_state:
            st.session_state[hint_key] = False
        if not st.session_state[hint_key] and expl:
            if st.button("💡 Подсказка", key=f"{source_key}_hint_btn_{i}"):
                st.session_state[hint_key] = True
                st.rerun()
        if st.session_state[hint_key] and expl:
            # Keep hint useful but avoid revealing full explanation before submit.
            hint_text = expl[:max(30, len(expl) // 3)].rstrip() + "..."
            st.info(f"💡 {hint_text}")

        choice_key = f"{source_key}_scoped_{i}"
        choice = st.radio(
            "Варианты",
            list(range(len(opts))),
            index=None,
            format_func=lambda j, o=opts: o[j] if j < len(o) else "",
            key=choice_key,
            label_visibility="collapsed",
        )
        submit_key = f"{source_key}_submit_{i}"
        result_key = f"{source_key}_result_{i}"
        if st.button("Ответить", key=submit_key, type="secondary", width="stretch"):
            if choice is None:
                st.warning("Выберите вариант ответа перед отправкой.")
            else:
                with st.spinner("Проверяем ответ..."):
                    is_correct = choice == ok_idx and ok_idx >= 0
                    status = _status_for_submission(
                        is_correct=is_correct,
                        hint_used=bool(st.session_state.get(hint_key)),
                    )
                    explanation_source = expl
                    if is_correct:
                        explanation_source = "Отлично, это правильный выбор."
                    explanation = short_feedback_explanation(
                        explanation_source,
                        fallback="Сверьтесь с разбором и сделайте следующий шаг.",
                    )
                    st.session_state[result_key] = {
                        "status": status,
                        "explanation": explanation,
                        "cta_route": _cta_route_for_status(status),
                    }
                st.rerun()

        result = st.session_state.get(result_key)
        if isinstance(result, dict):
            submitted_count += 1
            if result.get("status") == "correct":
                correct_submissions += 1
            cta_clicked = render_stable_feedback_block(
                block_key=f"{source_key}_{i}",
                status=str(result.get("status") or "incorrect"),
                explanation=str(result.get("explanation") or ""),
                cta_route=str(result.get("cta_route") or "retry"),
                cta_type="secondary",
            )
            if cta_clicked:
                _apply_feedback_cta(
                    str(result.get("cta_route") or "retry"),
                    source_key=source_key,
                    question_idx=i,
                )
        elif expl:
            # If not answered yet, keep explanation in expander
            with st.expander(f"Разбор вопроса {i + 1}", expanded=False):
                st.caption(expl)

    total = len([x for x in questions if isinstance(x, dict)])
    if submitted_count > 0:
        pct = int(100 * correct_submissions / submitted_count) if submitted_count else 0
        if pct >= 80:
            st.success(
                f"🎯 Результат: **{correct_submissions}** из {submitted_count} ({pct}%) — отличный результат!"
            )
            if st.button("Открыть прогресс", key=f"{source_key}_goto_progress", type="primary"):
                st.session_state[PENDING_CURRENT_VIEW_KEY] = "Прогресс обучения"
                st.session_state[f"{source_key}_next_cta_route"] = "progress"
                st.rerun()
        elif pct >= 50:
            st.warning(
                f"📊 Результат: **{correct_submissions}** из {submitted_count} ({pct}%) — есть над чем поработать."
            )
        else:
            st.error(
                f"📊 Результат: **{correct_submissions}** из {submitted_count} ({pct}%) — рекомендуем повторить тему."
            )
        if submitted_count >= total and total > 0:
            st.divider()
            # W4b: return to Mnemonopolis after full quiz completion (quiz channel).
            try:
                from app.ui.mnemo_nav import render_return_to_mnemo_cta

                if render_return_to_mnemo_cta(
                    key=f"{source_key}_return_mnemo",
                    return_from="quiz",
                    caption=(
                        "Квиз завершён · в мире обновится quiz-след (✓ / рассвет), "
                        "не «всё, что вы сделали»."
                    ),
                ):
                    st.rerun()
            except Exception:  # noqa: BLE001 - optional CTA
                pass
            st.markdown("##### Карточки для повторения")
            qid = str(meta.get("identifier") or meta.get("relative_path") or "").strip()
            deck_label = qid[:48] if qid else "квиз"
            if st.button(
                "Создать карточки из этих вопросов",
                key=f"{source_key}_create_fc_from_quiz",
                type="primary",
                width="stretch",
            ):
                from app.flashcard_service import cards_from_scoped_quiz_items  # lazy: avoids llama_index at Topics-tab import time
                raw_cards = cards_from_scoped_quiz_items([q for q in questions if isinstance(q, dict)])
                if not raw_cards:
                    st.error("Не удалось собрать карточки из вопросов квиза.")
                else:
                    try:
                        payload = {
                            "name": f"Quiz: {deck_label}",
                            "source_identifier": qid or None,
                            "cards": raw_cards,
                        }
                        r = fetch_json("POST", "/flashcards/decks/import-quiz", json=payload, timeout=120)
                        did = int(r.get("deck_id") or 0)
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Не удалось сохранить колоду: {exc}")
                    else:
                        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Flashcards"
                        st.session_state["fc_quiz_deck_success_id"] = did
                        from app.ui.flashcards_sections import FC_MAIN_SECTION_DECKS, set_flashcards_section

                        set_flashcards_section(FC_MAIN_SECTION_DECKS)
                        st.rerun()
            completion_route = _completion_cta_route(pct=pct)
            completion_metric_key = f"{source_key}_completion_metric_emitted"
            if not bool(st.session_state.get(completion_metric_key)):
                _record_loop_transition(
                    source_key=source_key,
                    stage="completion",
                    route=completion_route,
                    status="correct" if pct >= 80 else ("partial" if pct >= 50 else "incorrect"),
                    payload={"primary_cta_count": 1, "submitted_count": submitted_count, "total": total},
                )
                st.session_state[completion_metric_key] = True
            completion_explanation = (
                "Квиз завершен: выберите следующий шаг, чтобы продолжить 5-минутный цикл без паузы."
            )
            completion_clicked = render_stable_feedback_block(
                block_key=f"{source_key}_completion",
                status="correct" if pct >= 80 else ("partial" if pct >= 50 else "incorrect"),
                explanation=completion_explanation,
                cta_route=completion_route,
            )
            if completion_clicked:
                _apply_feedback_cta(
                    completion_route,
                    source_key=source_key,
                    question_idx=-1,
                )
    else:
        st.caption(f"Отправьте ответы по вопросам выше ({total} вопросов).")

    fin_key = f"{source_key}_scoped_finish"
    if st.button("Завершить и сохранить прогресс", key=fin_key, type="secondary"):
        try:
            from app.fact_source_binding import apply_quiz_outcome_to_learner_state
            from app.gamification_service import record_quiz_activity
            from app.quiz_stats import record_quiz_session_completed
            from app.user_state import increment_weekly_progress, save_quiz_result
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            return
        concept = str(meta.get("identifier") or "general").strip() or "general"
        score = float(correct_submissions) / float(total) if total else 0.0
        try:
            row_id = save_quiz_result(concept=concept, level="scoped_quiz", score=score)
            apply_quiz_outcome_to_learner_state(
                concept=concept,
                score=score,
                level="scoped_quiz",
                quiz_result_id=row_id,
            )
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            pass
        try:
            increment_weekly_progress("quizzes", 1)
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            pass
        try:
            record_quiz_session_completed(total_questions=total, correct=correct_submissions)
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            pass
        scope_raw = str(meta.get("scope") or "").strip().lower()
        if scope_raw == "topic":
            gscope = "topic"
        elif scope_raw == "document":
            gscope = "document"
        else:
            gscope = "scoped"
        try:
            gam = record_quiz_activity(score_0_1=score, scope=gscope)
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            gam = {}
        xp = int(gam.get("xp_gained") or 0)
        if gam.get("level_up"):
            st.balloons()
            st.success(
                f"🎉 LEVEL UP! **{gam.get('level_title', '')}** (ур. {gam.get('level', '')}) · "
                f"+{xp} XP · прогресс и расписание повторений обновлены."
            )
        else:
            st.success(
                f"Сохранено: прогресс и расписание повторений обновлены · **+{xp} XP** "
                f"({gam.get('level_title', '')}, ур. {gam.get('level', '?')}) · streak в статистике квизов."
            )
        for _b in gam.get("new_badges") or []:
            _lab = _b.get("label") if isinstance(_b, dict) else str(_b)
            try:
                st.toast(f"🏆 Новый бейдж: {_lab}")
            except Exception as _exc:  # noqa: BLE001
                import logging  # noqa: BLE001
                logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                st.caption(f"🏆 Новый бейдж: {_lab}")
        saved_key = f"{source_key}_{quiz_hash}_quiz_saved"
        st.session_state[saved_key] = True
        st.session_state[f"{source_key}_{quiz_hash}_attempt_id"] = row_id
        st.rerun()

    saved_key = f"{source_key}_{quiz_hash}_quiz_saved"
    if submitted_count >= total and total > 0 and st.session_state.get(saved_key):
        _render_quiz_checkpoint_if_due(
            source_key=source_key,
            quiz_hash=quiz_hash,
            quiz_feedback_status="correct" if pct >= 80 else ("partial" if pct >= 50 else "incorrect"),
            topic_hint=str(meta.get("identifier") or meta.get("relative_path") or "").strip() or None,
        )


def _render_quiz_checkpoint_if_due(
    *,
    source_key: str,
    quiz_feedback_status: str | None = None,
    topic_hint: str | None = None,
    quiz_hash: str | None = None,
) -> None:
    """B1: after quiz save completes, render unified checkpoint (no auto-start)."""
    try:
        from app.ui.checkpoint import render_checkpoint
        from app.smart_study_router import build_smart_study_recommendation
        from app.ui.resume_cards_smart_study import gather_smart_study_router_session_context, _get_saved_plan_primary_block
    except Exception as _exc:  # noqa: BLE001 - optional checkpoint
        import logging as _logging  # noqa: BLE001
        _logging.getLogger(__name__).debug("checkpoint import failed: %s", _exc)
        return
    try:
        ctx = gather_smart_study_router_session_context(index_stats=None)
    except Exception as _exc:  # noqa: BLE001
        import logging as _logging  # noqa: BLE001
        _logging.getLogger(__name__).debug("checkpoint context gather failed: %s", _exc)
        return
    plan_block = _get_saved_plan_primary_block()
    rec = build_smart_study_recommendation(
        surface="home",
        flashcard_due_n=ctx.flashcard_due_n,
        sm2_due_n=ctx.sm2_due_n,
        quiz_feedback_status=quiz_feedback_status,
        has_tutor_resume=bool(ctx.effective_tutor_snap),
        tutor_topic=ctx.tutor_topic,
        has_last_answer_qa=ctx.has_last_answer_qa,
        has_reading_resume=ctx.has_reading,
        first_weak_concept=ctx.weak_concepts[0] if ctx.weak_concepts else None,
        plan_primary_block=plan_block,
    )
    render_checkpoint(
        rec,
        surface="quiz",
        origin="quiz",
        return_view=st.session_state.get("current_view", "Mission Control"),
        key_prefix=source_key,
        completion_key=f"quiz:{source_key}:{quiz_hash or ''}:{st.session_state.get(f'{source_key}_{quiz_hash}_attempt_id', 0)}",
        tutor_topic=topic_hint,
        weak_concept=ctx.weak_concepts[0] if ctx.weak_concepts else None,
        plan_block=plan_block,
    )


def _reset_quiz_state_for_source(source_key: str) -> None:
    """Clear stale quiz answer/results when quiz content hash changes."""
    for i in range(20):
        st.session_state.pop(f"{source_key}_result_{i}", None)
        st.session_state.pop(f"{source_key}_scoped_{i}", None)
        st.session_state.pop(f"{source_key}_submit_{i}", None)
        st.session_state.pop(f"{source_key}_hint_{i}", None)
    st.session_state.pop(f"{source_key}_completion_metric_emitted", None)
    st.session_state.pop(f"{source_key}_next_cta_route", None)
    st.session_state.pop(f"{source_key}_quiz_content_hash", None)
