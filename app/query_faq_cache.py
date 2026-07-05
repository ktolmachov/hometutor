"""FAQ similarity cache lookup и сборка полного ответа при cache hit."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from app.logging_config import log_event
from app.models import QueryContext, QueryOptions
from app.rag_runtime_preferences import effective_settings
from app.query_metrics import (
    _build_retrieval_trace,
    _build_trace_schema_debug,
    _compute_answer_confidence,
    _record_answer_flow,
)
from app.query_rag_assembly import build_faq_cache_result
from app.query_session_persistence import persist_chat_session
from app.query_tutor_context import _normalize_tutor_answer_contract

logger = logging.getLogger(__name__)


def _source_rank_reason(score: object) -> str:
    """E9.5 / US-3.2: короткая причина ранга фрагмента (согласована с подсказкой score в UI)."""
    if score is None:
        return "оценка релевантности не передана"
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "оценка поиска по этому фрагменту"
    if s >= 0.75:
        return "высокая близость к формулировке вопроса"
    if s >= 0.45:
        return "умеренная близость — сверьте цитату в файле"
    return "низкий score — фрагмент слабее остальных; при сомнении откройте источник"


def _enrich_sources_provenance(sources: list[Any], *, route: str | None) -> None:
    """Дополняет источники cite_index, route и rank_reason (FAQ и legacy payloads)."""
    r = route if route is not None else "unknown"
    for i, raw in enumerate(sources):
        if not isinstance(raw, dict):
            continue
        if raw.get("cite_index") is None:
            raw["cite_index"] = i + 1
        if raw.get("route") is None:
            raw["route"] = r
        if not raw.get("rank_reason"):
            raw["rank_reason"] = _source_rank_reason(raw.get("score"))


def find_similar_faq_entries(effective_question: str, min_score: float) -> list[dict[str, Any]]:
    """Best-effort lookup в FAQ cache: ошибки не должны ронять основной ask-поток."""
    try:
        from app import faq_memory

        return faq_memory.find_similar_questions(
            question=effective_question,
            top_k=1,
            min_score=min_score,
        )
    except Exception as e:  # noqa: BLE001 - optional cache layer must not break answer flow
        log_event(
            logger,
            logging.WARNING,
            "faq_similar_questions_lookup_failed",
            error=str(e),
        )
        return []


def build_faq_cache_tutor_answer(ctx: QueryContext, cached: dict[str, Any]) -> dict[str, Any]:
    return _normalize_tutor_answer_contract(
        answer_text=cached.get("answer", ""),
        tutor_teaching=None,
        tutor_decision=None,
        auto_quiz_payload=None,
        inline_quiz=[],
        socratic_followup=None,
        learner_profile=None,
        query_context=ctx,
    )


def try_faq_cache(
    ctx: QueryContext,
    options: QueryOptions,
    execution_plan: Any,
    started_at: float,
    pipeline_ms: float,
    original_question: str,
    followup_context_used: bool,
    *,
    tutor_mode_debug_fn: Callable[[QueryContext | None, QueryOptions], dict[str, Any]],
) -> dict[str, Any] | None:
    """Поиск в FAQ cache. Если найден релевантный ответ, возвращает полный результат."""
    if not execution_plan.faq_cache_eligible:
        return None

    similar = find_similar_faq_entries(
        effective_question=ctx.effective_query,
        min_score=effective_settings().faq_min_score,
    )

    if not similar:
        return None

    cached = similar[0]
    sources = cached.get("sources") or []
    _enrich_sources_provenance(sources, route="faq_cache")
    total_ms = (time.perf_counter() - started_at) * 1000
    confidence = _compute_answer_confidence(
        sources,
        ctx.query_type,
        ctx.classify_confidence,
    )
    _record_answer_flow(
        cache_hit=True,
        engine_acquire_ms=0.0,
        query_execute_ms=0.0,
        total_ms=total_ms,
    )
    faq_retrieval_trace = _build_retrieval_trace(
        {
            "query_type": ctx.query_type,
            "retrieval_mode": "faq_cache",
            "enable_reranker": False,
            "similarity_top_k": None,
            "rerank_top_n": None,
            "filters": None,
        },
        sources,
        cache_hit=True,
        effective_query=ctx.effective_query,
        effective_query_source=ctx.effective_query_source,
    )
    trace_schema = _build_trace_schema_debug(ctx.trace, faq_retrieval_trace)
    tutor_answer = build_faq_cache_tutor_answer(ctx, cached)
    _sess_hist = persist_chat_session(
        session_id=options.session_id,
        user_question=original_question,
        assistant_answer=cached.get("answer", ""),
        confidence=confidence,
        sources=sources,
    )
    return build_faq_cache_result(
        options=options,
        ctx=ctx,
        execution_plan=execution_plan,
        cached=cached,
        sources=sources,
        confidence=confidence,
        pipeline_ms=pipeline_ms,
        total_ms=total_ms,
        followup_context_used=followup_context_used,
        trace_schema=trace_schema,
        faq_retrieval_trace=faq_retrieval_trace,
        tutor_answer=tutor_answer,
        session_history=_sess_hist,
        tutor_mode_debug=tutor_mode_debug_fn(ctx, options),
    )
