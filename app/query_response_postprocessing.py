"""Post-processing helpers for RAG and tutor answers."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from app.config import get_settings
from app.flashcard_handoff import is_flashcard_handoff
from app.guardrails import redact_sensitive_text
from app.logging_config import log_event
from app.models import QueryContext, QueryOptions
from app.path_safety import resolve_data_relative_path
from app.usage_cost import extract_token_usage
from app.utils import safe_preview


def source_rank_reason(score: object) -> str:
    """Return the short source-ranking explanation shown in UI source cards."""
    if score is None:
        return "оценка релевантности не передана"
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "оценка поиска по этому фрагменту"
    if value >= 0.75:
        return "высокая близость к формулировке вопроса"
    if value >= 0.45:
        return "умеренная близость - сверьте цитату в файле"
    return "низкий score - фрагмент слабее остальных; при сомнении откройте источник"


_LINE_RANGE_SUPPORTED_EXTS = frozenset({".md", ".txt", ".html"})
_LINE_RANGE_MAX_BYTES = 200_000
_LINE_RANGE_MAX_SOURCES = 5


def _compute_text_line_range(*, relative_path: object, snippet: object) -> tuple[int, int] | None:
    rel = str(relative_path or "").strip()
    if not rel:
        return None
    low = rel.lower()
    if not any(low.endswith(ext) for ext in _LINE_RANGE_SUPPORTED_EXTS):
        return None

    frag = str(snippet or "").strip()
    if not frag:
        return None

    frag = re.sub(r"\s+", " ", frag).strip()
    if len(frag) < 8:
        return None
    probe = frag[:120]
    try:
        path = resolve_data_relative_path(rel)
        if not path.exists() or not path.is_file():
            return None
        size = path.stat().st_size
        if size <= 0 or size > _LINE_RANGE_MAX_BYTES:
            return None
        text = path.read_text(encoding="utf-8", errors="ignore")
        if not text:
            return None
        norm = re.sub(r"\s+", " ", text)
        pos = norm.find(probe)
        if pos < 0:
            return None
        raw_pos = text.find(probe)
        if raw_pos < 0:
            raw_pos = text.find(probe.replace(" ", "\n"))
        if raw_pos < 0:
            return None
        start_line = text.count("\n", 0, raw_pos) + 1
        snippet_lines = max(1, str(snippet).count("\n") + 1)
        end_line = max(start_line, start_line + snippet_lines - 1)
        return start_line, end_line
    except Exception:  # noqa: BLE001 - provenance line-range is best-effort and must never break answers.
        return None


def tutor_rag_snippet_from_response(response: Any, *, max_chars: int = 6000) -> str:
    """Build a compact context excerpt for the optional inline quiz call."""
    nodes = getattr(response, "source_nodes", None) or []
    parts: list[str] = []
    n = 0
    for node in nodes:
        if n >= max_chars:
            break
        text_value = getattr(node, "text", None)
        if text_value is None and hasattr(node, "node"):
            text_value = getattr(node.node, "text", None)
        chunk = (str(text_value or "")).strip()[:900]
        if not chunk:
            continue
        parts.append(chunk)
        n += len(chunk)
    return "\n---\n".join(parts)[:max_chars]


def normalize_inline_numeric_citations(answer_text: str, source_count: int) -> tuple[str, dict[str, Any]]:
    """Keep inline numeric citations aligned with returned source cards."""
    text = str(answer_text or "")
    if not text:
        return text, {"changed": False, "invalid_indices": []}

    invalid: set[int] = set()
    changed = False

    def repl(match: re.Match[str]) -> str:
        nonlocal changed
        raw = match.group(1)
        indices: list[int] = []
        for part in raw.split(","):
            value = part.strip()
            if value.isdigit():
                indices.append(int(value))
        if not indices:
            return match.group(0)

        valid = sorted({idx for idx in indices if 1 <= idx <= source_count})
        for idx in indices:
            if idx < 1 or idx > source_count:
                invalid.add(idx)

        if valid:
            normalized = "[" + ", ".join(str(idx) for idx in valid) + "]"
        elif source_count > 0:
            normalized = "[1]"
        else:
            normalized = ""

        if normalized != match.group(0):
            changed = True
        return normalized

    normalized = re.sub(r"\[(\d+(?:\s*,\s*\d+)*)\]", repl, text)
    return normalized, {"changed": changed, "invalid_indices": sorted(invalid)}


def process_rag_response(
    response: Any,
    ctx: QueryContext,
    options: QueryOptions,
    retrieval_sc: dict[str, Any],
    pipeline_params: dict[str, Any],
    accumulated_rag_generation_usage: Any,
    original_question: str,
    *,
    logger: logging.Logger,
) -> dict[str, Any]:
    """Post-process a RAG answer into text, sources, tutor payloads, and usage."""
    answer_text = str(response)
    if retrieval_sc.get("weak_context"):
        disclaimer = get_settings().retrieval_weak_context_disclaimer.strip()
        if disclaimer:
            answer_text = disclaimer + "\n\n" + answer_text

    generation_usage = accumulated_rag_generation_usage or extract_token_usage(response)

    log_event(
        logger,
        logging.INFO,
        "answer_received",
        answer_preview=redact_sensitive_text(safe_preview(answer_text, 500)),
        answer_length=len(answer_text),
    )

    inline_quiz: list[dict[str, Any]] = []
    socratic_followup: dict[str, Any] | None = None
    tutor_teaching: dict[str, Any] | None = None
    inline_quiz_ms: float | None = None

    if (
        (options.query_mode or "").strip().lower() == "tutor"
        and not options.homework_mode
        and not is_flashcard_handoff(options)
    ):
        # Flashcard handoff emits plain friendly prose (not v2 JSON), so we skip the
        # tutor-v2 parser entirely. Otherwise a partial/quirky answer could be misread
        # as JSON; prose is displayed verbatim and degrades gracefully if token-capped.
        from app.quiz_service import parse_tutor_rag_response

        answer_text, socratic_followup, inline_quiz, tutor_teaching = (
            parse_tutor_rag_response(answer_text)
        )

    sources = []
    source_nodes = getattr(response, "source_nodes", None)

    if source_nodes is None:
        log_event(logger, logging.WARNING, "response_source_nodes_missing")
    else:
        log_event(
            logger,
            logging.INFO,
            "response_source_summary",
            similarity_top_k=pipeline_params.get("similarity_top_k"),
            rerank_enabled=pipeline_params.get("enable_reranker"),
            rerank_top_n=pipeline_params.get("rerank_top_n")
            if pipeline_params.get("enable_reranker")
            else None,
            returned_source_nodes=len(source_nodes),
        )

        for idx, node in enumerate(source_nodes, start=1):
            try:
                metadata = getattr(node, "metadata", {}) or {}
                score = getattr(node, "score", None)

                text_value = getattr(node, "text", None)
                if text_value is None and hasattr(node, "node"):
                    text_value = getattr(node.node, "text", None)

                retrieval_mode = pipeline_params.get("retrieval_mode")
                source_info = {
                    "cite_index": idx,
                    "file_name": metadata.get("file_name"),
                    "folder_name": metadata.get("folder_name"),
                    "folder_rel": metadata.get("folder_rel"),
                    "relative_path": metadata.get("relative_path"),
                    "page": metadata.get("page_label", "?"),
                    "score": score,
                    "route": retrieval_mode,
                    "rank_reason": source_rank_reason(score),
                    "text": (text_value or "")[:500],
                }
                rs = metadata.get("retrieval_source")
                if rs is not None:
                    source_info["retrieval_source"] = str(rs)
                ge = metadata.get("graph_evidence")
                if ge is not None:
                    source_info["graph_evidence"] = ge
                if idx <= _LINE_RANGE_MAX_SOURCES:
                    rng = _compute_text_line_range(
                        relative_path=source_info.get("relative_path"),
                        snippet=source_info.get("text"),
                    )
                    if rng:
                        source_info["line_start"], source_info["line_end"] = rng
                sources.append(source_info)

                log_event(
                    logger,
                    logging.INFO,
                    "response_source_node_parsed",
                    index=idx,
                    relative_path=source_info["relative_path"],
                    page=source_info["page"],
                    score=source_info["score"],
                    text_preview=redact_sensitive_text(
                        safe_preview(source_info["text"], 250)
                    ),
                )
            except Exception:  # noqa: BLE001 - source parsing is best-effort.
                log_event(
                    logger,
                    logging.ERROR,
                    "response_source_node_parse_failed",
                    index=idx,
                )

    answer_text, citation_normalization = normalize_inline_numeric_citations(
        answer_text,
        len(sources),
    )
    if citation_normalization["changed"]:
        log_event(
            logger,
            logging.INFO,
            "answer_inline_citations_normalized",
            source_count=len(sources),
            invalid_indices=citation_normalization["invalid_indices"],
        )

    if tutor_teaching is not None:
        answer_text, inline_quiz, tutor_teaching, inline_quiz_ms = _apply_tutor_teaching_postprocessing(
            response=response,
            ctx=ctx,
            options=options,
            sources=sources,
            tutor_teaching=tutor_teaching,
            inline_quiz=inline_quiz,
            original_question=original_question,
            logger=logger,
        )

    if (
        (options.query_mode or "").strip().lower() == "tutor"
        and not options.homework_mode
        and ctx is not None
        and ctx.metadata.get("tutor_decision") is None
    ):
        from app.tutor_orchestrator import decide_tutor_next_action
        from app.user_state import update_tutor_learner_profile_from_session

        tutor_decision = decide_tutor_next_action(
            current_topic=str(ctx.metadata.get("current_topic") or "general"),
            mastery_level=str(ctx.metadata.get("mastery_level") or "intermediate"),
            preferred_style=str(ctx.metadata.get("preferred_style") or "balanced"),
            learning_goal=str(ctx.metadata.get("learning_goal") or "understand_topic"),
            quiz_difficulty=str(ctx.metadata.get("quiz_difficulty") or "recognition"),
            session_state=ctx.metadata,
        )
        po = ctx.metadata.get("pedagogical_orchestrator")
        if isinstance(po, dict):
            tutor_decision = {**tutor_decision, "pedagogical_orchestrator": po}
        ctx.metadata["tutor_decision"] = tutor_decision
        ctx.metadata["persisted_learner_profile"] = (
            update_tutor_learner_profile_from_session(ctx.metadata)
        )

    auto_quiz_payload: dict[str, Any] | None = None
    auto_quiz_ms: float | None = None
    _defer_sync_quiz = is_flashcard_handoff(options)
    if (
        not _defer_sync_quiz
        and ctx is not None
        and (options.query_mode or "").strip().lower() == "tutor"
        and not options.homework_mode
        and get_settings().enable_tutor_auto_quiz_loop
    ):
        from app.quiz_service import generate_and_attach_micro_quiz

        try:
            _aq_start = time.perf_counter()
            auto_quiz_payload = generate_and_attach_micro_quiz(ctx)
            auto_quiz_ms = round((time.perf_counter() - _aq_start) * 1000, 3)
        except Exception:  # noqa: BLE001 - auto quiz is optional graceful degradation.
            logger.exception("auto_quiz_loop_failed")
            auto_quiz_payload = None
            auto_quiz_ms = None

    return {
        "answer_text": answer_text,
        "sources": sources,
        "generation_usage": generation_usage,
        "inline_quiz": inline_quiz,
        "socratic_followup": socratic_followup,
        "tutor_teaching": tutor_teaching,
        "auto_quiz_payload": auto_quiz_payload,
        "auto_quiz_ms": auto_quiz_ms,
        "inline_quiz_ms": inline_quiz_ms,
    }


def _apply_tutor_teaching_postprocessing(
    *,
    response: Any,
    ctx: QueryContext,
    options: QueryOptions,
    sources: list[dict[str, Any]],
    tutor_teaching: dict[str, Any],
    inline_quiz: list[dict[str, Any]],
    original_question: str,
    logger: logging.Logger,
) -> tuple[str, list[dict[str, Any]], dict[str, Any], float | None]:
    from app.knowledge_graph import get_graph_prerequisites_health
    from app.quiz_service import format_tutor_v2_markdown
    from app.tutor_orchestrator import (
        apply_tutor_self_correction,
        decide_tutor_next_action,
    )
    from app.user_state import update_tutor_learner_profile_from_session

    graph_health: dict | None = None
    try:
        graph_health = get_graph_prerequisites_health()
    except Exception:  # noqa: BLE001 - graph health is optional tutor context.
        logger.warning("tutor_graph_prerequisites_health_failed", exc_info=True)

    tutor_teaching = apply_tutor_self_correction(
        tutor_teaching,
        session_state=(ctx.metadata if ctx is not None else None),
        source_count=len(sources),
        graph_prerequisites_health=graph_health,
    )
    inline_quiz_ms: float | None = None
    _defer_sync_quiz = is_flashcard_handoff(options)
    if (
        not _defer_sync_quiz
        and get_settings().enable_tutor_inline_quiz
        and get_settings().tutor_inline_quiz_separate_llm_call
    ):
        from app.quiz_service import generate_tutor_inline_quiz_questions

        metadata = (ctx.metadata or {}) if ctx is not None else {}
        user_question = str(ctx.effective_query if ctx is not None else original_question)
        learning_mode_raw = metadata.get("quiz_learning_mode") or metadata.get(
            "learning_goal"
        )
        _iq_start = time.perf_counter()
        generated_questions = generate_tutor_inline_quiz_questions(
            teaching=tutor_teaching,
            user_question=user_question,
            context_excerpt=tutor_rag_snippet_from_response(response),
            quiz_difficulty=str(metadata.get("quiz_difficulty") or "recognition"),
            learning_mode=str(learning_mode_raw) if learning_mode_raw else None,
        )
        inline_quiz_ms = round((time.perf_counter() - _iq_start) * 1000, 3)
        if generated_questions:
            inline_quiz = generated_questions
    try:
        from app.learner_model_service import update_learner_model_after_interaction

        metadata = (ctx.metadata or {}) if ctx is not None else {}
        topic = str(
            metadata.get("orchestrator_quiz_topic")
            or metadata.get("current_topic")
            or metadata.get("topic")
            or "general"
        ).strip() or "general"
        mastery_hint = 0.48 if sources else 0.42
        update_outcome = {
            "mastery_gain": 0.06 if sources else 0.03,
            "mastery_score": mastery_hint,
            "concept_gains": {topic: mastery_hint},
            "concept": topic,
            "source_count": len(sources),
            "cognitive_load_delta": -0.04 if sources else -0.02,
            "confidence_delta": 0.02 if sources else 0.0,
            "session_id": getattr(options, "session_id", None),
        }
        update_learner_model_after_interaction(
            "local",
            "tutor",
            update_outcome,
            session_id=getattr(options, "session_id", None),
        )
        if ctx is not None:
            ctx.metadata["learner_trace"] = {
                "concept": topic,
                "mastery_score": mastery_hint,
                "source_count": len(sources),
                "cognitive_load_delta": update_outcome.get("cognitive_load_delta"),
                "confidence_delta": update_outcome.get("confidence_delta"),
            }
    except Exception:  # noqa: BLE001 - learner model update is best-effort.
        logger.warning(
            "update_learner_model_after_interaction tutor failed",
            exc_info=True,
        )
    tutor_decision = decide_tutor_next_action(
        current_topic=str(
            (ctx.metadata if ctx is not None else {}).get("current_topic")
            or "general"
        ),
        mastery_level=str(
            (ctx.metadata if ctx is not None else {}).get("mastery_level")
            or "intermediate"
        ),
        preferred_style=str(
            (ctx.metadata if ctx is not None else {}).get("preferred_style")
            or "balanced"
        ),
        learning_goal=str(
            (ctx.metadata if ctx is not None else {}).get("learning_goal")
            or "understand_topic"
        ),
        quiz_difficulty=str(
            (ctx.metadata if ctx is not None else {}).get("quiz_difficulty")
            or "recognition"
        ),
        session_state=(ctx.metadata if ctx is not None else None),
    )
    if ctx is not None:
        pedagogical_orchestrator = ctx.metadata.get("pedagogical_orchestrator")
        if isinstance(pedagogical_orchestrator, dict):
            tutor_decision = {
                **tutor_decision,
                "pedagogical_orchestrator": pedagogical_orchestrator,
            }
        ctx.metadata["tutor_decision"] = tutor_decision
        ctx.metadata["persisted_learner_profile"] = (
            update_tutor_learner_profile_from_session(ctx.metadata)
        )
    trust_signals = tutor_teaching.get("trust_signals")
    if not isinstance(trust_signals, dict):
        trust_signals = {}
        tutor_teaching["trust_signals"] = trust_signals
    trust_signals["sources_used"] = len(sources)
    return format_tutor_v2_markdown(tutor_teaching), inline_quiz, tutor_teaching, inline_quiz_ms


__all__ = [
    "process_rag_response",
    "source_rank_reason",
    "tutor_rag_snippet_from_response",
]
