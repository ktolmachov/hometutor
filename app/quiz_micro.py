"""Micro-quiz generation and outcome processing (split from ``app.quiz_service``)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.config import get_settings
from app.latency_budget import budget_meta_to_session_event, maybe_append_budget_tape_event, with_budget
from app.llm_resilience import chat_with_resilience
from app.prompts import (
    build_quiz_micro_chat_messages,
    normalize_quiz_learning_mode,
    quiz_mc_mode_block,
)
from app.quiz_parse import _coerce_quiz_correct_index, _extract_first_json_object

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.models import QueryContext

def _validate_micro_quiz_payload(data: dict[str, Any]) -> bool:
    q = (data.get("question") or "").strip()
    opts = data.get("options")
    co = (data.get("correct_option") or "").strip().upper()
    if not q or not isinstance(opts, list) or len(opts) != 4:
        return False
    if not all(isinstance(o, str) and o.strip() for o in opts):
        return False
    if co not in ("A", "B", "C", "D"):
        return False
    diff = str(data.get("difficulty") or "").strip().lower()
    if diff not in ("easy", "medium", "hard"):
        return False
    qt = str(data.get("type") or "").strip().lower()
    if qt not in ("recognition", "recall", "application"):
        return False
    return True


def _normalize_micro_quiz_payload(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    out["question"] = str(out.get("question") or "").strip()
    out["options"] = [str(o).strip() for o in (out.get("options") or [])][:4]
    out["correct_option"] = str(out.get("correct_option") or "A").strip().upper()[:1]
    out["explanation"] = str(out.get("explanation") or "").strip()
    out["difficulty"] = str(out.get("difficulty") or "medium").strip().lower()
    out["type"] = str(out.get("type") or "application").strip().lower()
    return out


def topic_from_last_user_message(messages: list[Any], *, max_len: int = 160) -> str | None:
    """
    Тема для micro-quiz: последнее сообщение пользователя в сессии (сжатое).
    Поддерживает ``app.models.Message`` и словари с полями role/content.
    """
    for m in reversed(messages or []):
        role = getattr(m, "role", None)
        if role is None and isinstance(m, dict):
            role = m.get("role")
        if str(role or "").strip().lower() != "user":
            continue
        content = getattr(m, "content", None)
        if content is None and isinstance(m, dict):
            content = m.get("content")
        text = str(content or "").strip()
        if not text:
            continue
        line = " ".join(text.split())
        if max_len > 0 and len(line) > max_len:
            line = line[: max_len - 1].rstrip() + "…"
        return line
    return None


def _micro_quiz_force_offline() -> bool:
    return bool(get_settings().home_rag_micro_quiz_offline)


def _fallback_micro_quiz(topic: str, band: str) -> dict[str, Any]:
    t = (topic or "тема").strip() or "тема"
    b = band if band in ("easy", "medium", "hard") else "medium"
    return {
        "question": f"Что из перечисленного лучше всего описывает ключевую идею «{t}»?",
        "options": [
            "A) Случайный факт без связи с практикой",
            "B) Рабочее определение и типичный сценарий применения",
            "C) Только название без содержания",
            "D) Противоречащий контексту вывод",
        ],
        "correct_option": "B",
        "explanation": "Нужно связать термин с типичным применением, а не только с формулировкой.",
        "difficulty": b,
        "type": "application",
    }


def _resolve_quiz_learning_mode_for_ctx(ctx: "QueryContext") -> str:
    md = ctx.metadata or {}
    if md.get("quiz_learning_mode"):
        return normalize_quiz_learning_mode(str(md.get("quiz_learning_mode")))
    if md.get("learning_goal"):
        return normalize_quiz_learning_mode(str(md.get("learning_goal")))
    return normalize_quiz_learning_mode(get_settings().quiz_learning_mode_default)


def generate_micro_quiz(
    topic: str,
    mastery_level: str = "intermediate",
    recent_errors: list[str] | None = None,
    *,
    use_llm: bool = True,
    learning_mode: str | None = None,
    topic_concept: str | None = None,
) -> dict[str, Any]:
    """
    Один адаптивный вопрос (4 варианта) для inline-проверки в чате.
    Возвращает словарь: question, options, correct_option, explanation, difficulty, type.

    ``topic_concept`` — идентификатор концепта для ``quiz_mastery``; задаёт vector-level
    (recognition/recall/transfer) и полосу сложности вместе с tutor ``mastery_level``.

    ``use_llm=False`` или env ``HOME_RAG_MICRO_QUIZ_OFFLINE=1`` — только шаблонный вопрос без вызова LLM (тесты, офлайн).
    """
    from app.quiz_adaptive import choose_micro_quiz_difficulty, get_recommended_difficulty, mastery_label_from_vector_level

    vector_level: str | None = None
    tc = (topic_concept or "").strip()
    if tc:
        try:
            vector_level = get_recommended_difficulty(tc)
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            logger.debug("generate_micro_quiz: get_recommended_difficulty failed", exc_info=True)

    band = choose_micro_quiz_difficulty(mastery_level, recent_errors, vector_level=vector_level)
    label = mastery_label_from_vector_level(vector_level)
    mastery_prompt = label if label else (mastery_level or "intermediate").strip() or "intermediate"
    if not use_llm or _micro_quiz_force_offline():
        return _fallback_micro_quiz(topic, band)

    def _generate_body() -> dict[str, Any]:
        hints = ", ".join(str(x) for x in (recent_errors or []) if str(x).strip()) or "—"
        mode_key = normalize_quiz_learning_mode(learning_mode)
        topic_text = (topic or "общая тема").strip() or "общая тема"
        messages = build_quiz_micro_chat_messages(
            mode_block=quiz_mc_mode_block(mode_key),
            topic=topic_text,
            mastery_level=mastery_prompt,
            difficulty_band=band,
            hints=hints,
        )
        try:
            from app.quiz_service import get_quiz_llm_for_generation as _quiz_llm

            llm = _quiz_llm()
            response = chat_with_resilience(
                llm,
                messages,
                stage="quiz.micro.generate",
                temperature=0.35,
            )
            text = (response.message.content or "").strip()
            data = _extract_first_json_object(text)
            if isinstance(data, dict) and _validate_micro_quiz_payload(data):
                return _normalize_micro_quiz_payload(data)
            logger.warning("generate_micro_quiz: invalid or empty JSON from model, using fallback")
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            logger.exception("generate_micro_quiz failed")
        return _fallback_micro_quiz(topic, band)

    budget = with_budget("quiz_gen", _generate_body)
    payload = dict(budget.result)
    payload["latency_budget"] = budget_meta_to_session_event(budget.meta)
    return payload


class InvalidMicroQuizQuestionError(ValueError):
    """Нет валидного correct_option / correct_index для MC micro-quiz."""


def normalize_quiz_question_for_evaluation(question: dict[str, Any]) -> dict[str, Any]:
    """Привести correct_option из буквы A–D или correct_index (0–3, в т.ч. 2.0)."""
    q = dict(question or {})
    correct_option = str(q.get("correct_option") or "").strip().upper()[:1]
    if correct_option in ("A", "B", "C", "D"):
        return q

    idx = _coerce_quiz_correct_index(q.get("correct_index"))
    if idx is not None:
        q["correct_option"] = "ABCD"[idx]
    return q


def process_micro_quiz_outcome(
    quiz_data: dict[str, Any],
    user_answer_letter: str,
    *,
    current_topic: str,
    current_mastery: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Диагностика ответа, обновление spaced repetition (SM-2), рекомендация шага (learning_plan).
    Quiz mastery + quiz_results — здесь же (единая точка для Unified Loop).
    """
    from app.learning_plan_service import get_recommended_next_step_after_micro_quiz
    from app.quiz_adaptive import diagnose_quiz_result
    from app.spaced_repetition import count_due_reviews
    from app.user_state import get_preferred_style, increment_weekly_progress, save_quiz_result

    q = normalize_quiz_question_for_evaluation(quiz_data)
    correct = str(q.get("correct_option") or "").strip().upper()[:1]
    if correct not in ("A", "B", "C", "D"):
        raise InvalidMicroQuizQuestionError(
            "quiz_question must include valid correct_option (A–D) or correct_index (0–3)"
        )

    def _submit_body() -> dict[str, Any]:
        qtype = str(q.get("type") or "application").strip().lower()
        feedback = diagnose_quiz_result(user_answer_letter, correct, qtype)
        ok = feedback.get("status") == "correct"
        from app.tutor_cycle import map_quiz_outcome_to_diagnostic

        diagnostic_feedback_status = map_quiz_outcome_to_diagnostic(
            is_correct=bool(ok),
            question_type=qtype,
        )
        score = 1.0 if ok else 0.35
        concept = (current_topic or "general").strip() or "general"
        row_id = save_quiz_result(
            concept=concept,
            level=qtype,
            score=score,
        )
        from app.fact_source_binding import apply_quiz_outcome_to_learner_state

        outcome = apply_quiz_outcome_to_learner_state(
            concept=concept,
            score=score,
            level=qtype,
            quiz_result_id=row_id,
        )
        sr = outcome["spaced_repetition"]
        mastery_adaptive = outcome["quiz_adaptive"]
        due_n = count_due_reviews()
        recommended_next = get_recommended_next_step_after_micro_quiz(
            current_topic=current_topic,
            mastery_level=current_mastery,
            last_quiz_feedback=feedback,
            quiz_question_type=qtype,
            due_reviews_count=due_n,
            preferred_style=get_preferred_style(),
        )
        try:
            increment_weekly_progress("quizzes", 1)
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            logger.debug("increment_weekly_progress(quizzes) failed", exc_info=True)
        sid = (session_id or "").strip()
        if sid:
            from app.user_state import upsert_tutor_learning_resume

            upsert_tutor_learning_resume(
                session_id=sid,
                topic=(current_topic or "").strip() or "general",
                mastery_level=current_mastery,
                last_action_kind="micro_quiz",
                last_action_label=f"Мини-проверка: {feedback.get('status', '')}",
                quiz_feedback=feedback,
                recommended_next=recommended_next,
                due_reviews_count=due_n,
            )
        try:
            from app.event_tracking import track_quiz_completed

            track_quiz_completed(str(feedback.get("status") or ""))
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            logger.debug("track_quiz_completed failed", exc_info=True)

        days = max(1, int(sr.get("interval_days") or 1))
        mastery_hint = "+3%" if ok else "0%"
        gam: dict[str, Any] = {}
        try:
            from app.gamification_service import record_quiz_activity

            gam = record_quiz_activity(score_0_1=score, scope="micro")
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            logger.debug("gamification record_quiz_activity failed", exc_info=True)
        xp_gain = int(gam.get("xp_gained") or (15 if ok else 4))
        retention_line = (
            f"+{xp_gain} XP · {gam.get('level_title', '?')} (ур. {gam.get('level', '?')})"
            f" • Mastery {mastery_hint} • Повтор через {days} дн."
        )

        try:
            from app.learner_model_service import update_learner_model_after_interaction

            topic_key = (current_topic or "general").strip() or "general"
            update_learner_model_after_interaction(
                "local",
                "quiz",
                {
                    "mastery_gain": float(score),
                    "concept_gains": {topic_key: float(score)},
                    "session_id": session_id,
                },
                session_id=session_id,
            )
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            logger.debug("update_learner_model_after_interaction quiz failed", exc_info=True)

        if ok:
            try:
                from app.gamification_service import award_xp_for_block

                pdate = datetime.now(timezone.utc).date().isoformat()
                award_xp_for_block(
                    "local",
                    {
                        "type": "auto_loop",
                        "duration_min": 5,
                        "xp_base": 10,
                        "description": "Micro-quiz / Auto-loop",
                    },
                    block_index=-1,
                    plan_date=pdate,
                    session_id=session_id,
                )
            except Exception as _exc:  # noqa: BLE001
                import logging  # noqa: BLE001
                logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                logger.debug("award_xp_for_block auto_loop failed", exc_info=True)

        return {
            "quiz_feedback": feedback,
            "diagnostic_feedback_status": diagnostic_feedback_status,
            "recommended_next": recommended_next,
            "spaced_repetition_due_count": due_n,
            "xp": xp_gain,
            "mastery_adaptive": mastery_adaptive,
            "spaced_repetition": sr,
            "retention_line": retention_line,
            "gamification": gam,
            "explanation": str(q.get("explanation") or "").strip(),
        }

    budget = with_budget("quiz_submit", _submit_body)
    payload = dict(budget.result)
    payload["latency_budget"] = budget_meta_to_session_event(budget.meta)
    maybe_append_budget_tape_event(session_id, budget.meta)
    return payload


def generate_and_attach_micro_quiz(ctx: "QueryContext") -> dict[str, Any] | None:
    """
    Unified Auto-Loop (P0): один короткий вопрос сразу после ответа тьютора.
    ``ctx.metadata`` — ``current_topic``, ``mastery_level`` (выставляет query_service).
    """
    from app.user_state import get_recent_quiz_levels_low_score

    if ctx.metadata.get("pedagogical_orchestrator_applied") and ctx.metadata.get(
        "orchestrator_trigger_microquiz"
    ) is False:
        return None

    topic = (
        ctx.metadata.get("orchestrator_quiz_topic")
        or ctx.metadata.get("current_topic")
        or "общая тема"
    ).strip() or "общая тема"
    mastery = (ctx.metadata.get("mastery_level") or "intermediate").strip() or "intermediate"
    recent = get_recent_quiz_levels_low_score(topic)
    q1 = generate_micro_quiz(
        topic,
        mastery_level=mastery,
        recent_errors=recent,
        learning_mode=_resolve_quiz_learning_mode_for_ctx(ctx),
        topic_concept=topic,
    )
    auto_id = f"auto_{uuid.uuid4().hex[:12]}"
    learner_profile = ctx.metadata.get("learner_profile")
    route = ""
    if isinstance(learner_profile, dict):
        route = str(learner_profile.get("route") or "").strip()
    route_note = f" Маршрут: {route}." if route else ""
    return {
        "quiz": {"questions": [q1]},
        "show_immediately": True,
        "motivational_message": f"🚀 Быстрая проверка по **{topic}** — готов?{route_note}",
        "auto_quiz_id": auto_id,
        "target_topic": topic,
        "route": route or None,
    }
