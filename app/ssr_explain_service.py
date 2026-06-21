"""Server-side SSR explanation: cache lookup + LLM token stream.

Single owner of the SSR explanation generation so FastAPI is the only process
that loads llama_index / sentence-transformers. The Streamlit process calls
POST /ssr/explain (SSE) instead of running this inline.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Generator

from app.prompts import (
    SSR_LLM_EXPLANATION_PROMPT_VERSION,
    SSR_LLM_EXPLANATION_SYSTEM,
    SSR_LLM_EXPLANATION_USER_TEMPLATE,
)
from app.provider import get_ssr_llm_resolved, ssr_llm_shares_main_api_base
from app.ssr_explanation_cache import (
    _SSR_LLM_EXPLANATION_CACHE,
    _SSR_LLM_EXPLANATION_CACHE_TTL_SEC,
    _cache_get_exact,
    _cache_put_exact,
    _clip_ssr_explanation,
)

logger = logging.getLogger(__name__)

SSR_EXPLANATION_MAX_TOKENS = 120


def cache_key(
    ctx: dict[str, Any],
    *,
    hint_kind: str,
    primary_label_ru: str,
    why_now_ru: str,
    primary_nav: str,
    route_pedagogy_ru: str = "",
    ml_audit_ru: str = "",
) -> str:
    """Reproduce _ssr_explanation_cache_key for dict-shaped inputs (no SmartStudyRecommendation)."""
    payload = {
        "prompt_version": SSR_LLM_EXPLANATION_PROMPT_VERSION,
        "rec": {
            "hint_kind": hint_kind,
            "primary_label_ru": primary_label_ru,
            "why_now_ru": why_now_ru,
            "primary_nav": primary_nav,
            "route_pedagogy_ru": route_pedagogy_ru,
            "ml_audit_ru": ml_audit_ru,
        },
        "learning_context": ctx or {},
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stream_explanation_tokens(
    ctx: dict[str, Any],
    *,
    hint_kind: str,
    primary_label_ru: str,
    why_now_ru: str,
    primary_nav: str,
    route_pedagogy_ru: str = "",
    ml_audit_ru: str = "",
    has_secondaries: bool = False,
    evidence_ledger: list[str] | None = None,
) -> Generator[str, None, None]:
    """Yield explanation tokens: exact cache → semantic cache → tier gate → LLM stream."""
    ctx = dict(ctx)
    if not evidence_ledger:
        ctx["cards_due_count"] = 1 if hint_kind == "cards_due" else 0
        ctx["sm2_due_count"] = 1 if hint_kind == "sm2_due" else 0

    key = cache_key(
        ctx,
        hint_kind=hint_kind,
        primary_label_ru=primary_label_ru,
        why_now_ru=why_now_ru,
        primary_nav=primary_nav,
        route_pedagogy_ru=route_pedagogy_ru,
        ml_audit_ru=ml_audit_ru,
    )

    # 1. Exact in-process cache
    now = time.monotonic()
    cached = _cache_get_exact(key)
    if cached and now - cached[0] < _SSR_LLM_EXPLANATION_CACHE_TTL_SEC:
        yield cached[1]
        return

    # 2. Semantic cache (embedding similarity) — only if model is already loaded.
    # If the warmup thread is still initialising the model (holding _MODEL_LOCK),
    # skip the semantic cache entirely rather than blocking this request thread.
    try:
        from app.ssr_semantic_cache import _EMBEDDINGS_MODEL, semantic_cache_lookup

        if _EMBEDDINGS_MODEL is not None:
            semantic_match = semantic_cache_lookup(ctx, _SSR_LLM_EXPLANATION_CACHE)
            if semantic_match:
                yield semantic_match
                return
    except Exception:  # noqa: BLE001
        pass

    # 3. Tier gate — return template text if signal is too weak for LLM enrichment
    try:
        from app.ssr_explanation_tier_gate import decide_explanation_tier

        _debt = frozenset(
            {"quiz_failed", "mastery_stale", "tutor_weak_gap", "quiz_recovery_tutor", "sm2_due"}
        )
        tier = decide_explanation_tier(
            evidence_ledger,
            hint_kind=hint_kind,
            primary_nav=primary_nav,
            has_contrastive=has_secondaries,
            has_steering_conflict=False,
            has_debt_label=hint_kind in _debt or primary_nav in _debt,
        )
        if tier.tier == "template_only":
            yield why_now_ru
            return
    except Exception:  # noqa: BLE001
        pass

    # 4. LLM streaming
    _fmt = dict(
        last_session_topic=str(ctx.get("last_session_topic") or "нет данных"),
        last_session_date=str(ctx.get("last_session_date") or "нет данных"),
        quiz_score_last_3=str(ctx.get("quiz_score_last_3") or "нет данных"),
        cards_due_count=str(ctx.get("cards_due_count") or ctx.get("flashcard_due_n") or 0),
        sm2_due_count=str(ctx.get("sm2_due_count") or 0),
        weak_concepts_list=str(ctx.get("weak_concepts_list") or "нет данных"),
        local_evidence=str(
            ctx.get("local_evidence") or "нет дополнительных локальных сигналов"
        ),
        primary_label_ru=primary_label_ru,
        primary_nav=primary_nav,
        hint_kind=hint_kind,
        why_now_template=why_now_ru,
    )
    try:
        from llama_index.core.llms import ChatMessage, MessageRole

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=SSR_LLM_EXPLANATION_SYSTEM),
            ChatMessage(
                role=MessageRole.USER,
                content=SSR_LLM_EXPLANATION_USER_TEMPLATE.format(**_fmt),
            ),
        ]
        started = time.perf_counter()
        llm_eff, ssr_used_main_llm = get_ssr_llm_resolved()
        shares_main = ssr_llm_shares_main_api_base() or ssr_used_main_llm
        if not shares_main:
            from app.llm_local_circuit import is_open as _cb_open

            circuit_base = str(getattr(llm_eff, "api_base", "") or "") or None
            if circuit_base and _cb_open(circuit_base):
                yield why_now_ru
                return

        if not callable(getattr(llm_eff, "stream_chat", None)):
            # Non-streaming LLM: blocking call, yield full text at once
            result_obj = llm_eff.chat(
                messages,
                max_tokens=SSR_EXPLANATION_MAX_TOKENS,
                temperature=0.2,
            )
            text = _clip_ssr_explanation(
                str(getattr(result_obj, "message", None) and result_obj.message.content or "").strip()
            )
            if text:
                _cache_put_exact(key, time.monotonic(), text)
            yield text or why_now_ru
            return

        chunks: list[str] = []
        for delta in llm_eff.stream_chat(
            messages,
            max_tokens=SSR_EXPLANATION_MAX_TOKENS,
            temperature=0.2,
        ):
            token = getattr(delta, "delta", None) or ""
            if token:
                chunks.append(token)
                yield token

        text = _clip_ssr_explanation("".join(chunks).strip())
        if text:
            _cache_put_exact(key, time.monotonic(), text)
            try:
                from app.ssr_semantic_cache import semantic_cache_store

                semantic_cache_store(key, ctx, text)
            except Exception:  # noqa: BLE001
                pass
        elif not chunks:
            yield why_now_ru

        elapsed = (time.perf_counter() - started) * 1000
        logger.debug("ssr_explain_service_stream_done", extra={"latency_ms": round(elapsed, 1)})

    except Exception:  # noqa: BLE001
        yield why_now_ru
