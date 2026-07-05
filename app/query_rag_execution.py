"""RAG query execution helpers for query_service orchestration."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from app.flashcard_handoff import is_flashcard_handoff
from app.graph_retrieval import graph_expansion_trace_scope
from app.logging_config import log_event
from app.models import QueryContext, QueryOptions
from app.otel_tracing import get_tracer
from app.langfuse_trace_export import apply_langfuse_query_span_attributes
from app.prompts import TWO_STAGE_EXTRACTIVE_INTRO
from app.rag_runtime_preferences import effective_settings
from app.retrieval_context_budget import retrieval_context_budget_trace_scope
from app.usage_cost import (
    begin_llm_generation_token_accumulation,
    consume_llm_generation_call_ms,
    consume_llm_generation_message_roles,
    consume_llm_generation_token_accumulation,
    estimate_cost_usd,
)


def max_source_node_score(source_nodes: Any) -> float | None:
    if not source_nodes:
        return None
    scores: list[float] = []
    for node in source_nodes:
        score = getattr(node, "score", None)
        if score is None:
            continue
        try:
            scores.append(float(score))
        except (TypeError, ValueError):
            continue
    return max(scores) if scores else None


def retrieval_alternate_query(
    ctx: QueryContext,
    effective_question: str,
) -> str | None:
    rewritten_query = (ctx.rewritten_query or "").strip()
    if rewritten_query and rewritten_query != effective_question.strip():
        return rewritten_query
    subquestions = getattr(ctx, "subquestions", None) or []
    if subquestions and str(subquestions[0]).strip():
        return str(subquestions[0]).strip()
    return None


def _scored_node_text(node: Any) -> str:
    tv = getattr(node, "text", None)
    if tv is not None and str(tv).strip():
        return str(tv).strip()
    inner = getattr(node, "node", None)
    if inner is not None:
        tv2 = getattr(inner, "text", None)
        if tv2 is not None:
            return str(tv2).strip()
    return ""


def _two_stage_eligible(ctx: QueryContext, options: QueryOptions) -> bool:
    settings = effective_settings()
    if not settings.enable_two_stage_answer_path:
        return False
    if (options.query_mode or "").strip().lower() == "tutor":
        return False
    if options.homework_mode:
        return False
    if options.study_mode:
        return False
    qt = (ctx.query_type or "").strip().lower()
    if qt in ("keyword", "kw"):
        return False
    if qt in ("synthesis", "learning_plan", "overview"):
        return False
    return qt == "qa"


def _build_extractive_answer(nodes: Any, *, max_chars: int) -> str:
    intro = TWO_STAGE_EXTRACTIVE_INTRO.strip() + "\n\n"
    parts: list[str] = [intro]
    used = len(intro)
    for item in nodes[:5]:
        chunk = _scored_node_text(item)
        if not chunk:
            continue
        piece = chunk[:900].strip()
        if not piece:
            continue
        block = f"— {piece}\n\n"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "".join(parts).strip()[:max_chars]


class _ExtractiveRagResponse:
    __slots__ = ("_text", "source_nodes")

    def __init__(self, text: str, source_nodes: list[Any]) -> None:
        self._text = text
        self.source_nodes = source_nodes

    def __str__(self) -> str:
        return self._text


def execute_rag_query(
    ctx: QueryContext,
    options: QueryOptions,
    execution_plan: Any,
    *,
    build_query_engine_fn: Callable[..., dict[str, Any]],
    logger: logging.Logger,
) -> dict[str, Any]:
    """Run QueryEngine retrieval/generation with tracing and self-correction."""
    otel_tracer = get_tracer("home_rag.query")
    accumulated_rag_generation_usage = None
    generation_message_roles: list[list[str]] | None = None
    effective_question = ctx.effective_query

    with otel_tracer.start_as_current_span("rag_retrieve_generate") as otel_span:
        engine_started = time.perf_counter()
        engine_result = build_query_engine_fn(
            effective_question,
            options,
            query_context=ctx,
            execution_plan=execution_plan,
        )
        engine = engine_result["engine"]
        cache_hit = engine_result["cache_hit"]
        engine_acquire_ms = (time.perf_counter() - engine_started) * 1000

        log_event(
            logger,
            logging.INFO,
            "query_engine_ready",
            cache_hit=cache_hit,
            engine_acquire_ms=round(engine_acquire_ms, 3),
            engine_cache_lookup_ms=engine_result.get("engine_cache_lookup_ms"),
        )

        pipeline_params = engine_result.get("pipeline_params") or {}
        pipeline_params["filters"] = engine_result.get("filters")

        retriever = getattr(engine, "retriever", None)
        if retriever is not None and _two_stage_eligible(ctx, options):
            from llama_index.core.schema import QueryBundle

            query_started = time.perf_counter()
            retrieval_sc_early: dict[str, Any] = {
                "attempts": 1,
                "retried": False,
                "weak_context": False,
            }
            with graph_expansion_trace_scope() as graph_trace:
                scored_nodes = retriever.retrieve(QueryBundle(effective_question))
                if graph_trace.get("graph_expansion") is not None:
                    ctx.trace["graph_expansion"] = graph_trace["graph_expansion"]
            query_execute_ms = (time.perf_counter() - query_started) * 1000

            settings = effective_settings()
            max_score = max_source_node_score(scored_nodes)
            nonempty = [n for n in scored_nodes if _scored_node_text(n)]
            thr = float(settings.two_stage_early_exit_min_score)
            min_nodes = int(settings.two_stage_early_exit_min_nodes)
            if (
                max_score is not None
                and max_score >= thr
                and len(nonempty) >= min_nodes
            ):
                cap = int(settings.two_stage_extractive_max_chars)
                answer_body = _build_extractive_answer(nonempty, max_chars=cap)
                intro_floor = len(TWO_STAGE_EXTRACTIVE_INTRO.strip()) + 24
                if len(answer_body.strip()) >= intro_floor:
                    retrieval_sc_early["two_stage_early_exit"] = True
                    retrieval_sc_early["final_max_score"] = max_score
                    ctx.trace["answer_path"] = {
                        "mode": "two_stage_early",
                        "max_score": max_score,
                        "nodes_used": len(nonempty),
                        "min_score_threshold": thr,
                        "min_nodes": min_nodes,
                    }
                    ctx.trace["retrieval_self_correction"] = retrieval_sc_early
                    response = _ExtractiveRagResponse(answer_body, list(scored_nodes))
                    log_event(
                        logger,
                        logging.INFO,
                        "query_two_stage_early_exit",
                        max_score=max_score,
                        nodes=len(nonempty),
                    )
                    if getattr(otel_span, "set_attribute", None):
                        otel_span.set_attribute("engine_cache_hit", cache_hit)
                        otel_span.set_attribute("query_execute_ms", round(query_execute_ms, 3))
                        otel_span.set_attribute("answer_path", "two_stage_early")
                    log_event(
                        logger,
                        logging.INFO,
                        "query_execution_completed",
                        query_execute_ms=round(query_execute_ms, 3),
                    )
                    return {
                        "engine_result": engine_result,
                        "response": response,
                        "query_execute_ms": query_execute_ms,
                        "accumulated_usage": None,
                        "retrieval_sc": retrieval_sc_early,
                        "cache_hit": cache_hit,
                        "engine_acquire_ms": engine_acquire_ms,
                        "engine_cache_lookup_ms": engine_result.get("engine_cache_lookup_ms"),
                        "pipeline_params": pipeline_params,
                        "retrieval_ms": round(query_execute_ms, 3),
                        "llm_ms": 0.0,
                    }

        # Inject dynamic per-query tutor hints into the question text.
        # These were removed from the static prompt template so the engine can be
        # cached across queries; they are re-attached here before every LLM call.
        if (
            (options.query_mode or "").strip().lower() == "tutor"
            and ctx is not None
            and not is_flashcard_handoff(options)
        ):
            _meta = ctx.metadata or {}
            _gh = (_meta.get("graph_hint") or "").strip()
            _lh = (_meta.get("learner_hint") or "").strip()
            _oh = (_meta.get("orchestration_hint") or "").strip()
            if _gh or _lh or _oh:
                _hint_lines = []
                if _gh:
                    _hint_lines.append(f"Graph guidance: {_gh}")
                if _lh:
                    _hint_lines.append(f"Learner state: {_lh}")
                if _oh:
                    _hint_lines.append(f"Orchestration: {_oh}")
                effective_question = "\n".join(_hint_lines) + "\n\n" + effective_question

        begin_llm_generation_token_accumulation()
        try:
            query_started = time.perf_counter()
            retrieval_sc: dict[str, Any] = {
                "attempts": 1,
                "retried": False,
                "weak_context": False,
            }
            context_budget_traces: list[dict[str, Any]] = []
            with graph_expansion_trace_scope() as graph_trace, retrieval_context_budget_trace_scope() as budget_trace:
                try:
                    response = engine.query(effective_question)
                finally:
                    if graph_trace.get("graph_expansion") is not None:
                        ctx.trace["graph_expansion"] = graph_trace["graph_expansion"]
                    if budget_trace:
                        context_budget_traces.append(dict(budget_trace))
                if budget_trace:
                    ctx.trace["retrieval_context_budget"] = context_budget_traces[-1]
            query_execute_ms = (time.perf_counter() - query_started) * 1000

            settings = effective_settings()
            if (
                settings.enable_retrieval_self_correction
                and (options.query_mode or "").strip().lower() != "tutor"
            ):
                threshold = float(settings.retrieval_self_correction_min_score)
                max_score = max_source_node_score(
                    getattr(response, "source_nodes", None)
                )
                retrieval_sc["max_score_initial"] = max_score
                alternate_query = retrieval_alternate_query(ctx, effective_question)
                if max_score is not None and max_score < threshold and alternate_query:
                    q2_started = time.perf_counter()
                    with (
                        graph_expansion_trace_scope() as graph_trace_2,
                        retrieval_context_budget_trace_scope() as budget_trace_2,
                    ):
                        try:
                            response2 = engine.query(alternate_query)
                        finally:
                            if graph_trace_2.get("graph_expansion") is not None:
                                ctx.trace["graph_expansion"] = graph_trace_2[
                                    "graph_expansion"
                                ]
                            if budget_trace_2:
                                context_budget_traces.append(dict(budget_trace_2))
                                ctx.trace["retrieval_context_budget"] = context_budget_traces[-1]
                    query_execute_ms += (time.perf_counter() - q2_started) * 1000
                    retrieval_sc["attempts"] = 2
                    retrieval_sc["retried"] = True
                    retrieval_sc["alternate_query"] = alternate_query
                    max_score_2 = max_source_node_score(
                        getattr(response2, "source_nodes", None)
                    )
                    retrieval_sc["max_score_after_retry"] = max_score_2
                    pick_second = max_score_2 is not None and (
                        max_score_2 > (max_score or 0.0)
                        or (max_score_2 >= threshold and (max_score or 0.0) < threshold)
                    )
                    if pick_second:
                        response = response2
                        retrieval_sc["used_alternate_response"] = True
                final_score = max_source_node_score(
                    getattr(response, "source_nodes", None)
                )
                retrieval_sc["final_max_score"] = final_score
                if final_score is None or final_score < threshold:
                    retrieval_sc["weak_context"] = True
            if context_budget_traces:
                ctx.trace["retrieval_context_budget"] = context_budget_traces[-1]
                if len(context_budget_traces) > 1:
                    ctx.trace["retrieval_context_budget_attempts"] = context_budget_traces
            ctx.trace["retrieval_self_correction"] = retrieval_sc
            ctx.trace["answer_path"] = {
                "mode": "full_rag",
                "retrieval_self_correction": bool(
                    settings.enable_retrieval_self_correction
                ),
            }
        finally:
            accumulated_rag_generation_usage = consume_llm_generation_token_accumulation()
            generation_message_roles = consume_llm_generation_message_roles()
            generation_call_ms = consume_llm_generation_call_ms()

        if getattr(otel_span, "set_attribute", None):
            otel_span.set_attribute("engine_cache_hit", cache_hit)
            otel_span.set_attribute("query_execute_ms", round(query_execute_ms, 3))
            generation_model = str(
                pipeline_params.get("generation_model")
                or pipeline_params.get("llm_model")
                or ""
            ).strip() or None
            estimated_cost = estimate_cost_usd(generation_model, accumulated_rag_generation_usage)
            apply_langfuse_query_span_attributes(
                otel_span,
                session_id=options.session_id,
                query_mode=options.query_mode,
                usage=accumulated_rag_generation_usage,
                model=generation_model,
                estimated_cost_usd=estimated_cost,
            )

        # Honest split: engine.query() bundles retrieval + rerank/postprocessors +
        # LLM synthesis under query_execute_ms. The LLM wrapper timed each generation
        # call (record_llm_generation_call_ms); the remainder is retrieval + rerank —
        # exactly the cost this package needs to surface. Clamp to avoid negatives from
        # timer skew / overlapping spans.
        llm_ms = round(generation_call_ms, 3) if generation_call_ms is not None else 0.0
        retrieval_ms = round(max(0.0, query_execute_ms - llm_ms), 3)

        log_event(
            logger,
            logging.INFO,
            "query_execution_completed",
            query_execute_ms=round(query_execute_ms, 3),
            retrieval_ms=retrieval_ms,
            llm_ms=llm_ms,
        )

    return {
        "engine_result": engine_result,
        "response": response,
        "query_execute_ms": query_execute_ms,
        "accumulated_usage": accumulated_rag_generation_usage,
        "generation_message_roles": generation_message_roles,
        "retrieval_sc": retrieval_sc,
        "cache_hit": cache_hit,
        "engine_acquire_ms": engine_acquire_ms,
        "engine_cache_lookup_ms": engine_result.get("engine_cache_lookup_ms"),
        "pipeline_params": pipeline_params,
        "retrieval_ms": retrieval_ms,
        "llm_ms": llm_ms,
    }


__all__ = [
    "execute_rag_query",
    "max_source_node_score",
    "retrieval_alternate_query",
]
