"""LLM explanation generation for Smart Study Router cards."""
from __future__ import annotations

import logging
import time
from typing import Any

from app.smart_study_router import SmartStudyRecommendation
from app.ssr_explanation_cache import (
    _SSR_LLM_EXPLANATION_CACHE,
    _SSR_LLM_EXPLANATION_CACHE_TTL_SEC,
    _cache_get_exact,
    _cache_put_exact,
    _clip_ssr_explanation,
    _ssr_feedback_ctx_reset,
    _ssr_feedback_ctx_set,
)
from app.ui.adaptive_plan_llm_enrichment import (
    _SSR_LLM_EXPLANATION_TIMEOUT_SEC,
    _SSR_LLM_EXPLANATION_TOKEN_FALLBACK,
    _SSR_LLM_EXPLANATION_TOKEN_WARN,
    _extract_llm_token_cost,
    _finalize_ssr_explanation_metrics,
    _ssr_explanation_cache_key,
)
from app.provider import get_ssr_llm_resolved, ssr_llm_shares_main_api_base

logger = logging.getLogger(__name__)

def _generate_llm_explanation(
    rec: SmartStudyRecommendation,
    learning_context: dict[str, Any] | None = None,
    *,
    llm: Any | None = None,
    now_monotonic: float | None = None,
) -> str:
    """Generate a personalized SSR reason; preserve template fallback on any quality/latency miss."""
    from app.ssr_llm_profiling import record_ssr_llm_profile

    _ssr_feedback_ctx_reset()
    ctx = learning_context or {}
    fallback = rec.why_now_ru
    now = time.monotonic() if now_monotonic is None else float(now_monotonic)
    key = _ssr_explanation_cache_key(rec, ctx)
    cached = _cache_get_exact(key)
    if cached and now - cached[0] < _SSR_LLM_EXPLANATION_CACHE_TTL_SEC:
        record_ssr_llm_profile(
            outcome="cache_hit",
            latency_ms=0.0,
            hint_kind=rec.hint_kind,
            primary_nav=str(rec.primary_nav),
        )
        _ssr_feedback_ctx_set(outcome="cache_hit", latency_ms=0.0)
        return cached[1]

    # Fallback: try semantic cache (find similar contexts)
    try:
        from app.ssr_semantic_cache import semantic_cache_lookup

        semantic_match = semantic_cache_lookup(ctx, _SSR_LLM_EXPLANATION_CACHE)
        if semantic_match:
            record_ssr_llm_profile(
                outcome="semantic_cache_hit",
                latency_ms=0.0,
                hint_kind=rec.hint_kind,
                primary_nav=str(rec.primary_nav),
            )
            _ssr_feedback_ctx_set(outcome="semantic_cache_hit", latency_ms=0.0)
            return semantic_match
    except Exception:  # noqa: BLE001
        pass  # Semantic cache is optional; fallthrough to LLM call

    from app.prompts import SSR_LLM_EXPLANATION_SYSTEM, SSR_LLM_EXPLANATION_USER_TEMPLATE
    from llama_index.core.llms import ChatMessage, MessageRole

    _fmt = dict(
        last_session_topic=str(ctx.get("last_session_topic") or "нет данных"),
        last_session_date=str(ctx.get("last_session_date") or "нет данных"),
        quiz_score_last_3=str(ctx.get("quiz_score_last_3") or "нет данных"),
        cards_due_count=str(ctx.get("cards_due_count") or ctx.get("flashcard_due_n") or 0),
        sm2_due_count=str(ctx.get("sm2_due_count") or 0),
        weak_concepts_list=str(ctx.get("weak_concepts_list") or "нет данных"),
        local_evidence=str(ctx.get("local_evidence") or "нет дополнительных локальных сигналов"),
        primary_label_ru=rec.primary_label_ru,
        primary_nav=rec.primary_nav,
        hint_kind=rec.hint_kind,
        why_now_template=rec.why_now_ru,
    )
    messages = [
        ChatMessage(role=MessageRole.SYSTEM, content=SSR_LLM_EXPLANATION_SYSTEM),
        ChatMessage(role=MessageRole.USER, content=SSR_LLM_EXPLANATION_USER_TEMPLATE.format(**_fmt)),
    ]

    from app.otel_tracing import trace_ssr_llm_explanation

    with trace_ssr_llm_explanation() as otel_span:
        started_pc = time.perf_counter()
        started_mono = time.monotonic()
        ssr_used_main_llm = False
        llm_eff: Any | None = None
        circuit_base: str | None = None
        try:
            if llm is None:
                llm_eff, ssr_used_main_llm = get_ssr_llm_resolved()
            else:
                llm_eff = llm
            from app.llm_resilience import chat_with_resilience

            shares_main = ssr_llm_shares_main_api_base() or ssr_used_main_llm
            if not shares_main:
                from app.llm_local_circuit import is_open as _circuit_is_open

                circuit_base = str(getattr(llm_eff, "api_base", "") or "") or None
                if circuit_base and _circuit_is_open(circuit_base):
                    _finalize_ssr_explanation_metrics(
                        otel_span,
                        outcome="template_fallback_circuit_open",
                        latency_ms=(time.perf_counter() - started_pc) * 1000.0,
                        used_main_chat_client=ssr_used_main_llm,
                        llm=llm_eff,
                        hint_kind=rec.hint_kind,
                        primary_nav=str(rec.primary_nav),
                    )
                    _ssr_feedback_ctx_set(
                        outcome="template_fallback_circuit_open",
                        latency_ms=(time.perf_counter() - started_pc) * 1000.0,
                    )
                    return fallback
            result = chat_with_resilience(
                llm_eff,
                messages,
                stage="ssr_llm_explanation",
                max_tokens=220,
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001 - UI helper must preserve deterministic SSR fallback.
            logger.info("ssr_llm_explanation_fallback", extra={"reason": type(exc).__name__})
            if circuit_base:
                from app.llm_local_circuit import record_failure as _circuit_record_failure

                _circuit_record_failure(circuit_base, error_type=type(exc).__name__)
            _finalize_ssr_explanation_metrics(
                otel_span,
                outcome="error",
                latency_ms=(time.perf_counter() - started_pc) * 1000.0,
                used_main_chat_client=ssr_used_main_llm,
                llm=llm_eff,
                error_type=type(exc).__name__,
                hint_kind=rec.hint_kind,
                primary_nav=str(rec.primary_nav),
            )
            _ssr_feedback_ctx_set(
                outcome="error",
                latency_ms=(time.perf_counter() - started_pc) * 1000.0,
            )
            return fallback

        latency_ms = (time.perf_counter() - started_pc) * 1000.0
        # chat() returns ChatResponse; text is in .message.content.
        # Use explicit None-check so empty string "" correctly propagates
        # and triggers template_fallback_empty rather than falling through.
        _msg = getattr(result, "message", None)
        _content = getattr(_msg, "content", None) if _msg is not None else None
        text = _clip_ssr_explanation(
            str(_content if _content is not None else getattr(result, "text", result)).strip()
        )
        token_cost = _extract_llm_token_cost(result)

        if token_cost is not None and token_cost > _SSR_LLM_EXPLANATION_TOKEN_FALLBACK:
            logger.info("ssr_llm_explanation_fallback", extra={"reason": "token_budget", "token_cost": token_cost})
            _finalize_ssr_explanation_metrics(
                otel_span,
                outcome="template_fallback_token_budget",
                latency_ms=latency_ms,
                used_main_chat_client=ssr_used_main_llm,
                llm=llm_eff,
                total_tokens=token_cost,
                token_hard_cap_hit=True,
                hint_kind=rec.hint_kind,
                primary_nav=str(rec.primary_nav),
            )
            _ssr_feedback_ctx_set(outcome="template_fallback_token_budget", latency_ms=latency_ms)
            return fallback
        if token_cost is not None and token_cost > _SSR_LLM_EXPLANATION_TOKEN_WARN:
            logger.info("ssr_llm_explanation_token_budget_warn", extra={"token_cost": token_cost})
        elapsed_mono = time.monotonic() - started_mono
        if elapsed_mono > _SSR_LLM_EXPLANATION_TIMEOUT_SEC:
            _finalize_ssr_explanation_metrics(
                otel_span,
                outcome="template_fallback_timeout",
                latency_ms=latency_ms,
                used_main_chat_client=ssr_used_main_llm,
                llm=llm_eff,
                total_tokens=token_cost,
                hint_kind=rec.hint_kind,
                primary_nav=str(rec.primary_nav),
                extra={"elapsed_mono_sec": round(elapsed_mono, 3)},
            )
            _ssr_feedback_ctx_set(outcome="template_fallback_timeout", latency_ms=latency_ms)
            return fallback
        if not text:
            _finalize_ssr_explanation_metrics(
                otel_span,
                outcome="template_fallback_empty",
                latency_ms=latency_ms,
                used_main_chat_client=ssr_used_main_llm,
                llm=llm_eff,
                total_tokens=token_cost,
                hint_kind=rec.hint_kind,
                primary_nav=str(rec.primary_nav),
            )
            _ssr_feedback_ctx_set(outcome="template_fallback_empty", latency_ms=latency_ms)
            return fallback
        if circuit_base:
            from app.llm_local_circuit import record_success as _circuit_record_success

            _circuit_record_success(circuit_base)
        _cache_put_exact(key, now, text)
        # Also store in semantic cache for similarity-based future lookups
        try:
            from app.ssr_semantic_cache import semantic_cache_store

            semantic_cache_store(key, ctx, text)
        except Exception:  # noqa: BLE001
            pass  # Semantic cache is optional
        extra_ok: dict[str, Any] = {"output_word_count": len(text.split())}
        if token_cost is not None and token_cost > _SSR_LLM_EXPLANATION_TOKEN_WARN:
            extra_ok["soft_token_warn"] = True
        _ssr_feedback_ctx_set(outcome="llm_success", latency_ms=latency_ms)
        _finalize_ssr_explanation_metrics(
            otel_span,
            outcome="llm_success",
            latency_ms=latency_ms,
            used_main_chat_client=ssr_used_main_llm,
            llm=llm_eff,
            total_tokens=token_cost,
            hint_kind=rec.hint_kind,
            primary_nav=str(rec.primary_nav),
            extra=extra_ok,
        )
        return text

