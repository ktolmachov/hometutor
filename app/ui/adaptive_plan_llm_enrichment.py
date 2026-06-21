"""LLM enrichment for the Smart Study Router card."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any

from app.prompts import SSR_LLM_EXPLANATION_PROMPT, SSR_LLM_EXPLANATION_PROMPT_VERSION
from app.provider import get_ssr_llm_resolved, ssr_llm_shares_main_api_base
from app.smart_study_router import SmartStudyRecommendation
from app.ssr_explanation_cache import (
    _SSR_LLM_EXPLANATION_CACHE,
    _SSR_LLM_EXPLANATION_CACHE_TTL_SEC,
    _cache_get_exact,
    _cache_put_exact,
    _clip_ssr_explanation,
    _ssr_feedback_ctx_reset,
    _ssr_feedback_ctx_set,
    peek_ssr_explanation_feedback_meta,
    prime_ssr_explanation_feedback_meta_for_tests,
)

logger = logging.getLogger(__name__)


def _finalize_ssr_explanation_metrics(otel_span: Any, **profile_kw: Any) -> None:
    """JSONL-профиль + атрибуты OTEL-спана ``ssr_llm_explanation`` (если включён)."""
    from app.otel_tracing import set_ssr_span_attributes
    from app.ssr_llm_profiling import record_ssr_llm_profile

    eid = record_ssr_llm_profile(**profile_kw)
    if otel_span is None:
        return
    llm_obj = profile_kw.get("llm")
    eff = profile_kw.get("effective_model") or (
        str(getattr(llm_obj, "model", "") or "") if llm_obj is not None else ""
    )
    attrs: dict[str, Any] = {
        "event_id": eid or "",
        "outcome": str(profile_kw.get("outcome") or ""),
        "latency_ms": float(profile_kw.get("latency_ms") or 0.0),
        "used_main_chat_client": bool(profile_kw.get("used_main_chat_client")),
        "effective_model": eff or "unknown",
    }
    et = profile_kw.get("error_type")
    if et:
        attrs["error_type"] = str(et)
    tt = profile_kw.get("total_tokens")
    if tt is not None:
        attrs["total_tokens"] = int(tt)
    set_ssr_span_attributes(otel_span, attrs)


_SSR_LLM_EXPLANATION_TIMEOUT_SEC = 3.0


_SSR_LLM_EXPLANATION_TOKEN_WARN = 500


_SSR_LLM_EXPLANATION_TOKEN_FALLBACK = 700

def _ssr_explanation_cache_key(
    rec: SmartStudyRecommendation,
    learning_context: dict[str, Any] | None,
) -> str:
    payload = {
        "prompt_version": SSR_LLM_EXPLANATION_PROMPT_VERSION,
        "rec": {
            "hint_kind": rec.hint_kind,
            "primary_label_ru": rec.primary_label_ru,
            "why_now_ru": rec.why_now_ru,
            "primary_nav": rec.primary_nav,
            "route_pedagogy_ru": rec.route_pedagogy_ru,
            "ml_audit_ru": rec.ml_audit_ru,
        },
        "learning_context": learning_context or {},
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_llm_token_cost(result: Any) -> int | None:
    """Best-effort extraction across llama-index/OpenAI-compatible response shapes."""
    candidates = [
        result,
        getattr(result, "raw", None),
        getattr(result, "usage", None),
        getattr(result, "additional_kwargs", None),
    ]
    for item in list(candidates):
        if item is None:
            continue
        usage = item.get("usage") if isinstance(item, dict) else getattr(item, "usage", None)
        if usage is not None:
            candidates.append(usage)
    for item in candidates:
        if item is None:
            continue
        getter = item.get if isinstance(item, dict) else lambda key, default=None: getattr(item, key, default)
        total = getter("total_tokens") or getter("total_token_count") or getter("tokens")
        if total is not None:
            try:
                return int(total)
            except (TypeError, ValueError):
                continue
        prompt_tokens = getter("prompt_tokens") or getter("input_tokens")
        completion_tokens = getter("completion_tokens") or getter("output_tokens")
        if prompt_tokens is not None and completion_tokens is not None:
            try:
                return int(prompt_tokens) + int(completion_tokens)
            except (TypeError, ValueError):
                continue
    return None


# Context builder moved to ssr_context_builder (no heavy deps) so Streamlit can import
# it without pulling in llama_index. Re-exported here for backward compatibility.
from app.ssr_context_builder import (
    _LEDGER_FC_RE,
    _LEDGER_SM2_RE,
    _parse_ssr_ledger_queue_counts,
    build_ssr_llm_learning_context as _build_ssr_llm_learning_context,
)


def _ssr_why_now_for_card(
    rec: SmartStudyRecommendation,
    *,
    evidence_ledger: list[str] | None,
    tutor_topic: str | None,
    weak_concept: str | None,
    primary_topic_hint: str | None,
    llm: Any | None = None,
    now_monotonic: float | None = None,
) -> str:
    """Текст «Почему сейчас»: LLM при успехе, иначе шаблон ``rec.why_now_ru`` (см. кэш/таймаут)."""
    ctx = _build_ssr_llm_learning_context(
        rec,
        evidence_ledger=evidence_ledger,
        tutor_topic=tutor_topic,
        weak_concept=weak_concept,
        primary_topic_hint=primary_topic_hint,
    )
    # Числовые слоты промпта: из леджера или эвристика по сигналу маршрутизатора
    if not evidence_ledger:
        hk = rec.hint_kind
        fc_hint = 1 if hk == "cards_due" else 0
        sm2_hint = 1 if hk == "sm2_due" else 0
        ctx["cards_due_count"] = fc_hint
        ctx["sm2_due_count"] = sm2_hint

    # Tier gate: decide template-only vs LLM enrichment
    from app.ssr_explanation_tier_gate import decide_explanation_tier
    from app.ssr_llm_profiling import record_ssr_llm_profile

    _debt_labels = frozenset({"quiz_failed", "mastery_stale", "tutor_weak_gap", "quiz_recovery_tutor", "sm2_due"})
    tier = decide_explanation_tier(
        evidence_ledger,
        hint_kind=rec.hint_kind,
        primary_nav=rec.primary_nav,
        has_contrastive=bool(rec.secondaries),
        has_steering_conflict=False,
        has_debt_label=rec.hint_kind in _debt_labels or rec.primary_nav in _debt_labels,
    )
    if tier.tier == "template_only":
        record_ssr_llm_profile(
            outcome="template_only",
            hint_kind=rec.hint_kind,
            primary_nav=str(rec.primary_nav),
            extra={"tier_reason": tier.reason, "signal_count": tier.signal_count},
        )
        _ssr_feedback_ctx_set(outcome="template_only", latency_ms=0.0)
        return rec.why_now_ru

    return _generate_llm_explanation(rec, ctx, llm=llm, now_monotonic=now_monotonic)


def _generate_llm_explanation(
    rec: SmartStudyRecommendation,
    learning_context: dict[str, Any] | None = None,
    *,
    llm: Any | None = None,
    now_monotonic: float | None = None,
) -> str:
    from app.ui.adaptive_plan_llm_explanation import _generate_llm_explanation as _impl

    return _impl(rec, learning_context, llm=llm, now_monotonic=now_monotonic)


def stream_ssr_explanation(
    rec: SmartStudyRecommendation,
    *,
    evidence_ledger: list[str] | None,
    tutor_topic: str | None,
    weak_concept: str | None,
    primary_topic_hint: str | None,
) -> "Generator[str, None, str]":
    """Yield explanation tokens one by one; return full text on StopIteration.

    Falls back to yielding the complete template string in a single chunk when:
    - the LLM is unavailable or circuit-breaker is open
    - the result is empty or would exceed the token budget
    - streaming is not supported by the resolved LLM

    The caller is responsible for caching the accumulated text.
    """
    from typing import Generator

    ctx = _build_ssr_llm_learning_context(
        rec,
        evidence_ledger=evidence_ledger,
        tutor_topic=tutor_topic,
        weak_concept=weak_concept,
        primary_topic_hint=primary_topic_hint,
    )
    if not evidence_ledger:
        hk = rec.hint_kind
        ctx["cards_due_count"] = 1 if hk == "cards_due" else 0
        ctx["sm2_due_count"] = 1 if hk == "sm2_due" else 0

    _ssr_feedback_ctx_reset()

    fallback = rec.why_now_ru
    key = _ssr_explanation_cache_key(rec, ctx)
    now = time.monotonic()
    cached = _cache_get_exact(key)
    if cached and now - cached[0] < _SSR_LLM_EXPLANATION_CACHE_TTL_SEC:
        _ssr_feedback_ctx_set(outcome="cache_hit", latency_ms=0.0)
        yield cached[1]
        return

    # Fallback: try semantic cache (find similar contexts)
    try:
        from app.ssr_semantic_cache import semantic_cache_lookup

        semantic_match = semantic_cache_lookup(ctx, _SSR_LLM_EXPLANATION_CACHE)
        if semantic_match:
            _ssr_feedback_ctx_set(outcome="semantic_cache_hit", latency_ms=0.0)
            yield semantic_match
            return
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

    try:
        started_pc = time.perf_counter()
        llm_eff, ssr_used_main_llm = get_ssr_llm_resolved()
        shares_main = ssr_llm_shares_main_api_base() or ssr_used_main_llm
        if not shares_main:
            from app.llm_local_circuit import is_open as _circuit_is_open

            circuit_base = str(getattr(llm_eff, "api_base", "") or "") or None
            if circuit_base and _circuit_is_open(circuit_base):
                _ssr_feedback_ctx_set(
                    outcome="template_fallback_circuit_open",
                    latency_ms=(time.perf_counter() - started_pc) * 1000.0,
                )
                yield fallback
                return
        if not callable(getattr(llm_eff, "stream_chat", None)):
            # Model doesn't support streaming — delegate to blocking path.
            result = _generate_llm_explanation(rec, ctx, llm=llm_eff)
            yield result
            return
        chunks: list[str] = []
        for delta in llm_eff.stream_chat(messages, max_tokens=220, temperature=0.2):
            token = getattr(delta, "delta", None) or ""
            if token:
                chunks.append(token)
                yield token
        text = _clip_ssr_explanation("".join(chunks).strip())
        latency_ms = (time.perf_counter() - started_pc) * 1000.0
        if text:
            _cache_put_exact(key, time.monotonic(), text)
            # Also store in semantic cache for similarity-based future lookups
            try:
                from app.ssr_semantic_cache import semantic_cache_store

                semantic_cache_store(key, ctx, text)
            except Exception:  # noqa: BLE001
                pass  # Semantic cache is optional
            _ssr_feedback_ctx_set(outcome="llm_success", latency_ms=latency_ms)
        else:
            _ssr_feedback_ctx_set(outcome="template_fallback_empty", latency_ms=latency_ms)
    except Exception:  # noqa: BLE001
        _ssr_feedback_ctx_set(outcome="stream_path_error", latency_ms=0.0)
        yield fallback


__all__ = [
    "_SSR_LLM_EXPLANATION_CACHE",
    "_build_ssr_llm_learning_context",
    "_generate_llm_explanation",
    "_ssr_why_now_for_card",
    "peek_ssr_explanation_feedback_meta",
    "prime_ssr_explanation_feedback_meta_for_tests",
    "stream_ssr_explanation",
]
