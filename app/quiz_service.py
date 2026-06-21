"""Generate short self-check quizzes from study material via LLM (JSON output)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import get_settings
from app.llm_resilience import complete_with_resilience
from app.prompts import (
    QUIZ_EVALUATION_PROMPT,
    QUIZ_PROMPT,
    QUIZ_SELF_CHECK_PROMPT,
    QUIZ_TUTOR_INLINE_QUIZ_FOLLOWUP_PROMPT,
    normalize_quiz_learning_mode,
    quiz_interactive_mode_block,
    quiz_mc_mode_block,
)
from app.provider import get_evaluate_llm
from app.quiz_micro import (
    InvalidMicroQuizQuestionError,
    generate_and_attach_micro_quiz,
    generate_micro_quiz,
    normalize_quiz_question_for_evaluation,
    process_micro_quiz_outcome,
    topic_from_last_user_message,
)
from app.quiz_parse import (
    TUTOR_INLINE_QUIZ_MARKER,
    TUTOR_SOCRATIC_MARKER,
    _MAX_CONTEXT_CHARS,
    _coerce_quiz_correct_index,
    _normalize_inline_questions,
    _strip_code_fence,
    build_flashcard_deck_request_from_interactive_quiz,
    format_correct_for_export,
    format_tutor_v2_markdown,
    parse_quiz_json,
    parse_tutor_quiz_llm_json,
    parse_tutor_rag_response,
    quiz_answer_correct,
    split_tutor_answer_and_quiz,
)
from app.quiz_scoped import (
    _scoped_adaptive_profile_hint,
    estimate_mastery_percent,
    generate_scoped_quiz,
    parse_scoped_quiz_json,
    scoped_quiz_xp_reward,
    weak_spot_scoped_quiz_params,
)
from app.retrieval_cache import get_cached_quiz_llm

logger = logging.getLogger(__name__)


def get_quiz_llm_for_generation():
    """
    LLM для квизов: общий кэш с RAG (retrieval_cache), если базовые сервисы подняты;
    иначе — прямой вызов provider (например Streamlit без индекса).
    """
    try:
        return get_cached_quiz_llm()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        from app.provider import get_quiz_llm

        return get_quiz_llm()


def generate_interactive_quiz(
    *,
    topic: str,
    user_level: str,
    learned_concepts: str,
    recent_history: str,
    concept_names: str,
    learning_mode: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    from app.config import get_settings
    n_questions = get_settings().quiz_interactive_question_count
    prompt = QUIZ_PROMPT.format(
        mode_instructions=quiz_interactive_mode_block(learning_mode),
        topic=topic,
        user_level=user_level,
        learned_concepts=learned_concepts,
        recent_history=recent_history,
        concept_names=concept_names,
        n_questions=n_questions,
    )
    llm = get_quiz_llm_for_generation()
    response = complete_with_resilience(
        llm,
        prompt,
        stage="quiz.interactive.generate",
        temperature=0.2,
    )
    raw_text = (response.text or "").strip()
    return parse_tutor_quiz_llm_json(raw_text, n_questions=n_questions)


def generate_tutor_inline_quiz_questions(
    *,
    teaching: dict[str, Any],
    user_question: str,
    context_excerpt: str,
    quiz_difficulty: str = "recognition",
    learning_mode: str | None = None,
) -> list[dict[str, Any]]:
    """
    Второй вызов LLM (get_quiz_llm / кэш): только блок inline-quiz, без основного teaching JSON.
    """
    raw_diff = (quiz_difficulty or "recognition").strip().lower()
    if raw_diff not in ("recognition", "recall", "transfer"):
        raw_diff = "recognition"
    slim = {
        "teaching_summary": teaching.get("teaching_summary"),
        "understanding_state": teaching.get("understanding_state"),
        "next_action": teaching.get("next_action"),
        "depth_level": teaching.get("depth_level"),
        "trust_signals": teaching.get("trust_signals"),
    }
    try:
        teaching_excerpt = json.dumps(slim, ensure_ascii=False)[:3800]
    except (TypeError, ValueError):
        teaching_excerpt = str(teaching.get("teaching_summary") or "")[:3800]
    lm = normalize_quiz_learning_mode(learning_mode)
    mode_block = quiz_interactive_mode_block(lm)
    prompt = QUIZ_TUTOR_INLINE_QUIZ_FOLLOWUP_PROMPT.format(
        mode_block=mode_block,
        user_question=(user_question or "").strip() or "—",
        context_excerpt=(context_excerpt or "").strip()[:12000] or "—",
        teaching_excerpt=teaching_excerpt,
        quiz_difficulty=raw_diff,
    )
    try:
        llm = get_quiz_llm_for_generation()
        response = complete_with_resilience(
            llm,
            prompt,
            stage="quiz.inline.followup",
            temperature=0.25,
        )
        text = (response.text or "").strip()
        cleaned = _strip_code_fence(text)
        data = json.loads(cleaned)
        qs = data.get("questions") if isinstance(data, dict) else None
        if not isinstance(qs, list):
            return []
        return _normalize_inline_questions(qs)
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.exception("generate_tutor_inline_quiz_questions failed")
        return []


def _resolve_inline_mc_correct_index(question: dict[str, Any]) -> int | None:
    ci = _coerce_quiz_correct_index(question.get("correct_index"))
    if ci is not None:
        return ci
    letter = str(question.get("correct_option") or question.get("correct") or "").strip().upper()[:1]
    if letter in ("A", "B", "C", "D"):
        return ord(letter) - ord("A")
    return None


def _parse_inline_mc_user_index(user_answer: str) -> int | None:
    """Индекс выбранного варианта 0..3 из буквы A–D или числа 0–3."""
    line = ((user_answer or "").strip().splitlines() or [""])[0].strip().upper()
    if not line:
        return None
    if len(line) == 1 and line in "ABCD":
        return ord(line) - ord("A")
    m = re.match(r"^([A-D])\b", line)
    if m:
        return ord(m.group(1)) - ord("A")
    if line.isdigit():
        i = int(line)
        if 0 <= i <= 3:
            return i
    return None


def evaluate_inline_quiz_answer(
    question: dict[str, Any],
    user_answer: str,
) -> dict[str, Any]:
    """Оценка ответа на inline-вопрос (0..1) и запись в ``quiz_results``."""
    from app.user_state import save_quiz_result

    qtype = str(question.get("type") or "short_answer").strip().lower()
    use_llm = True
    score = 0.0

    if qtype == "multiple_choice":
        correct_idx = _resolve_inline_mc_correct_index(question)
        if correct_idx is not None:
            use_llm = False
            user_idx = _parse_inline_mc_user_index(user_answer)
            score = 1.0 if user_idx is not None and user_idx == correct_idx else 0.0

    if use_llm:
        q = (question.get("question") or "").strip()
        prompt = QUIZ_EVALUATION_PROMPT.format(
            question=q,
            user_answer=(user_answer or "").strip(),
        )
        try:
            llm = get_evaluate_llm()
            response = complete_with_resilience(
                llm,
                prompt,
                stage="quiz.inline.evaluate",
                temperature=0.0,
            )
            line = (response.text or "").strip().splitlines()[0] if response.text else "0"
            score = float(line.replace(",", ".").replace(" ", ""))
        except (ValueError, IndexError, TypeError):
            score = 0.0

    score = max(0.0, min(1.0, score))
    concept_str = str(question.get("concept") or "unknown")
    row_id = save_quiz_result(
        concept=concept_str,
        level=str(question.get("difficulty") or "recall"),
        score=score,
    )
    quality = max(0, min(5, int(round(score * 5))))
    from app.fact_source_binding import apply_quiz_outcome_to_learner_state

    outcome = apply_quiz_outcome_to_learner_state(
        concept=concept_str,
        score=score,
        level=str(question.get("difficulty") or "recall"),
        quiz_result_id=row_id,
    )
    sr = outcome["spaced_repetition"]
    adaptive = outcome["quiz_adaptive"]
    return {
        "concept": question.get("concept"),
        "level": question.get("difficulty"),
        "score": score,
        "quiz_result_id": row_id,
        "quality_sm2": quality,
        "spaced_repetition": sr,
        "quiz_adaptive": adaptive,
        "provenance": outcome.get("provenance"),
    }


def generate_self_check_quiz(
    material: str,
    *,
    title: str = "",
    learning_mode: str | None = None,
    topic_concept: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """
    Build 5 questions with 4 options each. Returns (questions, error_message).

    ``topic_concept`` — концепт для adaptive profile из ``quiz_mastery`` (как scoped quiz).
    """
    ctx = (material or "").strip()
    if len(ctx) < 120:
        return [], "Слишком мало текста для генерации quiz (нужно хотя бы ~120 символов)."
    trimmed = ctx[:_MAX_CONTEXT_CHARS]
    mode_key = normalize_quiz_learning_mode(
        learning_mode or get_settings().quiz_learning_mode_default
    )
    ident = (topic_concept or title or "").strip()
    if ident:
        from app.quiz_adaptive import get_adaptive_difficulty

        adaptive_profile = _scoped_adaptive_profile_hint(get_adaptive_difficulty("adaptive", ident))
    else:
        adaptive_profile = (
            "Сбалансированный микс: часть вопросов на узнавание, "
            "часть на воспроизведение и короткое применение."
        )
    prompt = QUIZ_SELF_CHECK_PROMPT.format(
        mode_block=quiz_mc_mode_block(mode_key),
        title=(title or "без названия").strip() or "без названия",
        context_str=trimmed,
        adaptive_profile=adaptive_profile,
    )
    try:
        llm = get_quiz_llm_for_generation()
        response = complete_with_resilience(
            llm,
            prompt,
            stage="quiz.self_check.generate",
        )
        text = (response.text or "").strip()
    except Exception as e:  # noqa: BLE001 - quiz generation LLM/resilience failures handled gracefully and returned as error message
        logger.exception("quiz generation failed")
        return [], f"Ошибка LLM: {e}"
    return parse_quiz_json(text)

def generate_document_quiz(
    content: str,
    title: str,
    *,
    learning_mode: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Scoped quiz: материал — текст документа (например content_preview)."""
    return generate_self_check_quiz(
        content, title=title, learning_mode=learning_mode, topic_concept=title
    )


def generate_topic_quiz(
    topic_id: str,
    *,
    learning_mode: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Scoped quiz по теме: опирается на synthesis summary."""
    from app.knowledge_service import synthesize_topic

    res = synthesize_topic(topic_id=topic_id)
    summary = (res.get("summary") or "").strip()
    if len(summary) < 120:
        return [], "Недостаточно текста саммари по теме для quiz (соберите synthesis или проверьте индекс)."
    return generate_self_check_quiz(
        summary, title=topic_id, learning_mode=learning_mode, topic_concept=topic_id
    )


__all__ = [
    "InvalidMicroQuizQuestionError",
    "build_flashcard_deck_request_from_interactive_quiz",
    "format_correct_for_export",
    "normalize_quiz_question_for_evaluation",
    "evaluate_inline_quiz_answer",
    "format_tutor_v2_markdown",
    "estimate_mastery_percent",
    "weak_spot_scoped_quiz_params",
    "generate_and_attach_micro_quiz",
    "generate_interactive_quiz",
    "generate_tutor_inline_quiz_questions",
    "get_quiz_llm_for_generation",
    "generate_document_quiz",
    "generate_micro_quiz",
    "generate_scoped_quiz",
    "generate_self_check_quiz",
    "generate_topic_quiz",
    "parse_scoped_quiz_json",
    "scoped_quiz_xp_reward",
    "process_micro_quiz_outcome",
    "quiz_answer_correct",
    "topic_from_last_user_message",
    "parse_quiz_json",
    "parse_tutor_quiz_llm_json",
    "parse_tutor_rag_response",
    "split_tutor_answer_and_quiz",
    "TUTOR_INLINE_QUIZ_MARKER",
    "TUTOR_SOCRATIC_MARKER",
]
