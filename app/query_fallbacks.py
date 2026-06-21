"""Fallback response assembly for query answers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.guardrails import OutputGuardrailError, get_safe_fallback_message
from app.models import QueryContext
from app.usage_cost import merge_token_usage, sum_costs


def build_safe_fallback_result(
    *,
    error: OutputGuardrailError,
    cache_hit: bool,
    engine_acquire_ms: float,
    query_execute_ms: float,
    total_ms: float,
    pipeline_params: dict[str, Any],
    query_context: QueryContext | None = None,
    retrieval_stage_usage_cost_fn: Callable[..., tuple[Any, Any]],
    compute_quality_checks_fn: Callable[..., dict[str, Any]],
    build_retrieval_trace_fn: Callable[..., dict[str, Any]],
    build_trace_schema_debug_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Build the safe fallback response emitted after output guardrail failures."""
    ctx = query_context
    effective_query = ctx.effective_query if ctx else ""
    retrieval_mode = pipeline_params.get("retrieval_mode") if pipeline_params else None
    retrieval_usage, retrieval_cost = retrieval_stage_usage_cost_fn(
        retrieval_mode=retrieval_mode,
        effective_question=effective_query,
        ctx=ctx,
    )
    stage_usage = {
        "classify": ctx.trace.get("classify_usage") if ctx else None,
        "rewrite": ctx.trace.get("rewrite_usage") if ctx else None,
        "retrieval": retrieval_usage,
        "generation": None,
        "judge": None,
    }
    stage_costs = {
        "classify": ctx.trace.get("classify_estimated_cost_usd") if ctx else None,
        "rewrite": ctx.trace.get("rewrite_estimated_cost_usd") if ctx else None,
        "retrieval": retrieval_cost,
        "generation": None,
        "judge": None,
    }
    fallback_answer = get_safe_fallback_message(error.code)
    quality_checks = compute_quality_checks_fn(
        fallback_answer,
        [],
        fallback_applied=True,
    )
    retrieval_trace = build_retrieval_trace_fn(
        pipeline_params,
        [],
        cache_hit=cache_hit,
        effective_query=effective_query,
        effective_query_source=(ctx.effective_query_source if ctx else "original"),
    )
    trace_schema = build_trace_schema_debug_fn(
        ctx.trace if ctx else {},
        retrieval_trace,
    )
    return {
        "answer": fallback_answer,
        "sources": [],
        "debug": {
            "cache_hit": cache_hit,
            "engine_acquire_ms": round(engine_acquire_ms, 3),
            "query_execute_ms": round(query_execute_ms, 3),
            "total_answer_ms": round(total_ms, 3),
            "profile": pipeline_params.get("profile"),
            "query_type": ctx.query_type if ctx else pipeline_params.get("query_type"),
            "classify_method": ctx.classify_method if ctx else None,
            "classify_confidence": ctx.classify_confidence if ctx else None,
            "retrieval_mode": pipeline_params.get("retrieval_mode"),
            "similarity_top_k": pipeline_params.get("similarity_top_k"),
            "rerank_enabled": pipeline_params.get("enable_reranker"),
            "rerank_top_n": pipeline_params.get("rerank_top_n"),
            "rerank_model": pipeline_params.get("rerank_model"),
            "rewrite": ctx.trace.get("rewrite_enabled", False) if ctx else False,
            "rewritten_question": ctx.trace.get("rewritten_question") if ctx else None,
            "pipeline_trace": ctx.trace if ctx else {},
            "token_usage": {
                "stages": stage_usage,
                "total": merge_token_usage(
                    stage_usage["classify"],
                    stage_usage["rewrite"],
                    stage_usage["retrieval"],
                    stage_usage["generation"],
                    stage_usage["judge"],
                ),
            },
            "estimated_cost_usd": {
                "stages": stage_costs,
                "total": sum_costs(*stage_costs.values()),
            },
            "quality_checks": quality_checks,
            "retrieval_trace": retrieval_trace,
            **trace_schema,
            "guardrails": {
                "input_validated": True,
                "output_validated": False,
                "fallback_applied": True,
                "pii_redacted": False,
                "code": error.code,
                "message": str(error),
            },
        },
    }


__all__ = ["build_safe_fallback_result"]
