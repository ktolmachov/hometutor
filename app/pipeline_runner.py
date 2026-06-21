"""
Pipeline runner: orchestrates composable steps (ADR-010, Iteration 12).

Runs classify → condense → rewrite before retrieval/generation.
При ``QueryOptions.session_id`` подгружает историю из ``session_store`` для condense.

Полный цикл «вопрос → ответ» (retrieval + generation) — ``answer_question`` в
``query_service``; обёртки ``run_full_pipeline`` / ``run_full_pipeline_sync``
делегируют туда без повторного classify/condense/rewrite.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from app.config import get_retrieval_settings, RetrievalSettings
from app.logging_config import log_event, setup_logging
from app.metrics import PIPELINE_TRACE_SCHEMA_VERSION
from app.models import PipelineOverrides, QueryContext, QueryExecutionPlan, QueryOptions
from app.retrieval_router import get_rag_profile
from app.condense_step import condense_step
from app.pipeline_steps import (
    _classify_fallback,
    classify_step,
    rewrite_step,
    run_step_safe,
)
from app.session_store import session_store

logger = setup_logging()


def _run_classify(ctx: QueryContext) -> QueryContext:
    return run_step_safe(classify_step, ctx, fallback_fn=_classify_fallback)


def _run_rewrite(ctx: QueryContext) -> QueryContext:
    return run_step_safe(rewrite_step, ctx)


# Декларативный порядок pre-retrieval (condense сам пропускает без session_id).
_PRE_RETRIEVAL: tuple[tuple[str, Callable[[QueryContext], QueryContext]], ...] = (
    ("classify", _run_classify),
    ("condense", condense_step),
    ("rewrite", _run_rewrite),
)

PRE_RETRIEVAL_PIPELINE = _PRE_RETRIEVAL


def _pre_retrieval_steps(ctx: QueryContext) -> list[str]:
    steps: list[str] = ["classify"]
    condense_state = ctx.trace.get("condense")
    if condense_state not in ("skipped_no_session", "skipped_too_short"):
        steps.append("condense")
    if ctx.trace.get("rewrite_enabled"):
        steps.append("rewrite")
    return list(dict.fromkeys(steps))


def update_pipeline_post_retrieval_trace(
    ctx: QueryContext,
    execution_plan: QueryExecutionPlan,
    *,
    cache_hit: bool,
    source_count: int,
    generation_model: str | None,
    answer_length: int,
    llm_source_metadata: dict[str, Any] | None = None,
    latency_ms: float | None = None,
) -> QueryContext:
    """Attach retrieve/rerank/generate stages to the staged pipeline trace."""
    ctx.trace.setdefault("schema_version", PIPELINE_TRACE_SCHEMA_VERSION)
    ctx.trace["effective_query"] = ctx.effective_query
    ctx.trace["effective_query_source"] = ctx.effective_query_source
    rerank_stage = (
        "rerank"
        if execution_plan.enable_reranker
        else "rerank_skipped"
    )
    ctx.trace["retrieve_stage"] = {
        "retrieval_mode": execution_plan.retrieval_mode,
        "cache_hit": cache_hit,
        "source_count": source_count,
    }
    ctx.trace["rerank_stage"] = {
        "enabled": execution_plan.enable_reranker,
        "rerank_top_n": execution_plan.rerank_top_n if execution_plan.enable_reranker else None,
        "rerank_model": execution_plan.rerank_model if execution_plan.enable_reranker else None,
    }
    ctx.trace["generate_stage"] = {
        "prompt_key": execution_plan.prompt_key,
        "model": generation_model,
        "latency_ms": round(latency_ms, 3) if latency_ms is not None else None,
        "answer_length": answer_length,
    }
    if llm_source_metadata:
        ctx.trace["generate_stage"].update(llm_source_metadata)
    ctx.trace["execution_plan"] = execution_plan.to_pipeline_params()
    ctx.trace["pipeline_stages"] = _pre_retrieval_steps(ctx) + ["retrieve", rerank_stage, "generate"]
    ctx.pipeline_steps = list(ctx.trace["pipeline_stages"])
    return ctx


def run_pipeline(
    question: str,
    options: QueryOptions | None = None,
) -> QueryContext:
    """Run classify → condense → rewrite; return enriched QueryContext.

    Downstream code (retrieval, generation) uses ctx.effective_query
    and ctx.query_type / ctx.retrieval_strategy for decisions.
    """
    from app.otel_tracing import get_tracer

    opts = options or QueryOptions()
    sid = opts.session_id
    history = list(session_store.get(sid)) if sid else []

    tracer = get_tracer("home_rag.pipeline")
    with tracer.start_as_current_span("pipeline_classify_rewrite") as span:
        ctx = QueryContext(
            original_question=question,
            query_options=opts,
            session_id=sid,
            conversation_history=history,
        )
        if sid:
            ctx.metadata["session_user_turns_before"] = sum(
                1 for m in history if getattr(m, "role", None) == "user"
            )
        else:
            ctx.metadata["session_user_turns_before"] = None
        ctx.trace["schema_version"] = PIPELINE_TRACE_SCHEMA_VERSION
        ctx.trace["pre_retrieval_pipeline"] = [name for name, _ in _PRE_RETRIEVAL]

        for step_name, run in _PRE_RETRIEVAL:
            ctx = run(ctx)
            ctx.trace.setdefault("pre_retrieval_completed", []).append(step_name)

        ctx.trace["effective_query"] = ctx.effective_query
        ctx.trace["effective_query_source"] = ctx.effective_query_source

        ctx.pipeline_steps = _pre_retrieval_steps(ctx)

        if getattr(span, "set_attribute", None):
            span.set_attribute("query_type", ctx.query_type)
            span.set_attribute("retrieval_strategy", ctx.retrieval_strategy)

        log_event(
            logger,
            logging.INFO,
            "pipeline_runner_completed",
            query_type=ctx.query_type,
            classify_method=ctx.classify_method,
            classify_confidence=round(ctx.classify_confidence, 3),
            condensed=ctx.condensed_question is not None,
            rewritten=ctx.rewritten_query is not None,
            pipeline_steps=ctx.pipeline_steps,
            retrieval_strategy=ctx.retrieval_strategy,
        )

        return ctx


def resolve_retrieval_strategy(
    ctx: QueryContext,
    overrides: PipelineOverrides | None = None,
    settings: RetrievalSettings | None = None,
) -> str:
    """Config priority: API overrides > QueryContext (router) > rag_profile default > env defaults.

    API override is highest because the user explicitly requested a mode.
    QueryContext is second because the router chose based on query type.
    Если задан только rag_profile (после resolve_retrieval_routing), retrieval_mode берётся
    из RAG_PROFILE_DEFAULTS, а не копируется в PipelineOverrides отдельным полем.
    Env defaults are last as the baseline configuration.
    """
    if overrides and overrides.retrieval_mode:
        return overrides.retrieval_mode
    if ctx.retrieval_strategy != "default":
        return ctx.retrieval_strategy
    profile_name = overrides.rag_profile if overrides else None
    if profile_name:
        return get_rag_profile(str(profile_name).strip().lower()).retrieval_mode
    r = settings or get_retrieval_settings()
    return r.retrieval_mode


async def run_full_pipeline(
    question: str,
    options: QueryOptions | None = None,
    *,
    stream: bool = False,
) -> dict[str, Any]:
    """Полный RAG-ответ: один вызов ``answer_question`` (pipeline внутри не дублируется).

    ``stream`` зарезервирован под будущий streaming; сейчас не поддержан.
    """
    if stream:
        raise NotImplementedError("stream=True is not implemented")

    from app.query_service import answer_question

    opts = options or QueryOptions()
    return await asyncio.to_thread(answer_question, question, opts)


def run_full_pipeline_sync(
    question: str,
    options: QueryOptions | None = None,
) -> dict[str, Any]:
    """Синхронный полный ответ (обёртка над ``answer_question``)."""
    from app.query_service import answer_question

    return answer_question(question, options or QueryOptions())


def run_pipeline_sync(question: str, options: QueryOptions | None = None) -> QueryContext:
    """Синхронно только pre-retrieval (classify → condense → rewrite).

    Для полного ответа см. ``run_full_pipeline_sync``.
    """
    return run_pipeline(question, options)


__all__ = [
    "PRE_RETRIEVAL_PIPELINE",
    "resolve_retrieval_strategy",
    "run_full_pipeline",
    "run_full_pipeline_sync",
    "run_pipeline",
    "run_pipeline_sync",
]
