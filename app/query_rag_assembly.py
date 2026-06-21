import logging
from typing import Any

from app.knowledge_service import get_active_graph_for_review
from app.learner_state_scope import count_due_reviews_for_kg
from app.logging_config import log_event
from app.models import QueryContext, QueryOptions


def tutor_mode_debug(ctx: QueryContext | None, options: QueryOptions) -> dict[str, Any]:
    """Build tutor-only debug fields without expanding the query orchestrator."""
    if (options.query_mode or "").strip().lower() != "tutor":
        return {}
    from app.knowledge_graph import get_active_knowledge_graph, knowledge_graph
    from app.learner_state_scope import due_reviews_summary_for_kg
    from app.user_state import get_learner_state_diagnostics

    current = (options.topic or options.logical_folder or "").strip() or "Общая_тема"
    learned = list(ctx.metadata.get("learned_concepts", []) or []) if ctx else []
    ok, missing = knowledge_graph.check_prerequisites(current, learned)
    out: dict[str, Any] = {
        "query_mode": options.query_mode,
        "tutor_next_best_action": knowledge_graph.next_best_action(current, learned),
        "tutor_prerequisites_ok": ok,
        "tutor_prerequisites_missing": missing,
        "graph_summary": knowledge_graph.get_graph_summary(learned),
        "tutor_quiz_difficulty": str(ctx.metadata.get("quiz_difficulty") or "recognition") if ctx else "recognition",
        "tutor_socratic_type": str(ctx.metadata.get("socratic_type") or "probing") if ctx else "probing",
    }
    sr = due_reviews_summary_for_kg(get_active_knowledge_graph())
    out["tutor_spaced_repetition_due_count"] = sr["count"]
    if sr["count"]:
        out["tutor_spaced_repetition_hint"] = sr["hint"]
        out["tutor_spaced_repetition_preview"] = sr["preview_concepts"]
    if ctx:
        out.update(
            tutor_learning_goal=ctx.metadata.get("learning_goal"),
            tutor_answer_depth=ctx.metadata.get("answer_depth"),
            tutor_preferred_style=ctx.metadata.get("preferred_style"),
        )
    diag = get_learner_state_diagnostics(recent_limit=5)
    out["tutor_learner_state_lineage"] = {
        "current_lineage": diag.get("current_lineage"),
        "synced_lineage": diag.get("synced_lineage"),
        "archive_counts": diag.get("archive_counts"),
        "has_archived_state": bool(diag.get("has_archived_state")),
    }
    return out
from app.query_tutor_context import _build_tutor_payload, _normalize_tutor_answer_contract
from app.tutor_cycle import build_tutor_cycle_state
from app.usage_cost import merge_token_usage, sum_costs


def _build_faq_cache_debug_payload(
    *,
    options: QueryOptions,
    ctx: QueryContext,
    execution_plan: Any,
    cached: dict[str, Any],
    pipeline_ms: float,
    total_ms: float,
    followup_context_used: bool,
    trace_schema: dict[str, Any],
    faq_retrieval_trace: dict[str, Any],
    stage_usage: dict[str, Any],
    stage_costs: dict[str, Any],
    session_history: Any,
    tutor_mode_debug: dict[str, Any],
) -> dict[str, Any]:
    return {
        "session_id": options.session_id,
        **({"session_history": session_history} if session_history else {}),
        "cache_hit": True,
        "faq_cache_hit": True,
        "faq_cache_eligible": True,
        "faq_cache_skip_reason": None,
        "faq_score": cached.get("score"),
        "pipeline_ms": round(pipeline_ms, 3),
        "engine_acquire_ms": 0.0,
        "query_execute_ms": 0.0,
        "total_answer_ms": round(total_ms, 3),
        "profile": None,
        "query_type": ctx.query_type,
        "prompt_key": execution_plan.prompt_key if execution_plan else None,
        "query_engine_cache_policy": execution_plan.query_engine_cache_policy if execution_plan else None,
        "classify_method": ctx.classify_method,
        "classify_confidence": ctx.classify_confidence,
        "retrieval_mode": None,
        "similarity_top_k": None,
        "rerank_enabled": None,
        "rerank_top_n": None,
        "rerank_model": None,
        "rewrite": ctx.trace.get("rewrite_enabled", False),
        "rewritten_question": ctx.trace.get("rewritten_question"),
        "effective_query": ctx.effective_query,
        "effective_query_source": ctx.effective_query_source,
        "rewrite_model": ctx.trace.get("rewrite_model"),
        "llm_source": "cached",
        "llm_model": None,
        "llm_api_base": None,
        "fallback_used": False,
        "llm_profile": None,
        "llm_latency_ms": 0.0,
        "subquestions": ctx.subquestions,
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
        "homework_mode": options.homework_mode,
        "assistance_level": options.assistance_level,
        "study_mode": options.study_mode,
        "followup_context_used": followup_context_used,
        "pipeline_trace": ctx.trace,
        "retrieval_trace": faq_retrieval_trace,
        **trace_schema,
        "guardrails": {
            "input_validated": True,
            "output_validated": False,
            "fallback_applied": False,
            "pii_redacted": False,
            "code": None,
            "message": None,
        },
        **tutor_mode_debug,
    }


def _build_rag_debug_payload(
    *,
    options: QueryOptions,
    ctx: QueryContext,
    execution_plan: Any,
    session_history: Any,
    rag_result: dict[str, Any],
    pipeline_ms: float,
    total_ms: float,
    followup_context_used: bool,
    pii_redacted: bool,
    quality_checks: dict[str, Any],
    retrieval_trace: dict[str, Any],
    trace_schema: dict[str, Any],
    stage_usage: dict[str, Any],
    stage_costs: dict[str, Any],
    total_usage: dict[str, Any],
    tutor_mode_debug: dict[str, Any],
    grounded_debug: dict[str, Any] | None = None,
    guardrails_grounded_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cache_hit = rag_result["cache_hit"]
    engine_acquire_ms = rag_result["engine_acquire_ms"]
    query_execute_ms = rag_result["query_execute_ms"]
    pipeline_params = rag_result["pipeline_params"]
    guardrails_payload = {
        "input_validated": True,
        "output_validated": True,
        "fallback_applied": False,
        "pii_redacted": pii_redacted,
        "code": None,
        "message": None,
    }
    if guardrails_grounded_patch:
        guardrails_payload.update(guardrails_grounded_patch)
        guardrails_payload["pii_redacted"] = pii_redacted
    return {
        "session_id": options.session_id,
        **({"session_history": session_history} if session_history else {}),
        "cache_hit": cache_hit,
        "faq_cache_hit": False,
        "faq_cache_eligible": execution_plan.faq_cache_eligible if execution_plan else True,
        "faq_cache_skip_reason": execution_plan.faq_cache_skip_reason if execution_plan else None,
        "pipeline_ms": round(pipeline_ms, 3),
        "engine_acquire_ms": round(engine_acquire_ms, 3),
        "engine_build_ms": round(engine_acquire_ms, 3),
        "query_execute_ms": round(query_execute_ms, 3),
        "retrieval_ms": rag_result.get("retrieval_ms"),
        "llm_ms": rag_result.get("llm_ms"),
        "engine_cache_lookup_ms": rag_result.get("engine_cache_lookup_ms"),
        "post_processing_ms": rag_result.get("post_processing_ms"),
        "auto_quiz_ms": rag_result.get("auto_quiz_ms"),
        "inline_quiz_ms": rag_result.get("inline_quiz_ms"),
        "total_answer_ms": round(total_ms, 3),
        "profile": pipeline_params.get("profile"),
        "query_type": ctx.query_type,
        "prompt_key": execution_plan.prompt_key if execution_plan is not None else pipeline_params.get("prompt_key"),
        "query_engine_cache_policy": execution_plan.query_engine_cache_policy
        if execution_plan is not None
        else pipeline_params.get("query_engine_cache_policy"),
        "classify_method": ctx.classify_method,
        "classify_confidence": ctx.classify_confidence,
        "retrieval_mode": pipeline_params.get("retrieval_mode"),
        "similarity_top_k": pipeline_params.get("similarity_top_k"),
        "rerank_enabled": pipeline_params.get("enable_reranker"),
        "rerank_top_n": pipeline_params.get("rerank_top_n"),
        "rerank_model": pipeline_params.get("rerank_model"),
        "rewrite": ctx.trace.get("rewrite_enabled", False),
        "rewritten_question": ctx.trace.get("rewritten_question"),
        "effective_query": ctx.effective_query,
        "effective_query_source": ctx.effective_query_source,
        "rewrite_model": ctx.trace.get("rewrite_model"),
        "llm_source": pipeline_params.get("llm_source"),
        "llm_model": pipeline_params.get("llm_model"),
        "llm_api_base": pipeline_params.get("llm_api_base"),
        "fallback_used": pipeline_params.get("fallback_used"),
        "llm_profile": pipeline_params.get("llm_profile"),
        "llm_latency_ms": round(query_execute_ms, 3),
        "subquestions": ctx.subquestions,
        "token_usage": {"stages": stage_usage, "total": total_usage},
        "estimated_cost_usd": {"stages": stage_costs, "total": sum_costs(*stage_costs.values())},
        "quality_checks": quality_checks,
        "retrieval_trace": retrieval_trace,
        **trace_schema,
        "homework_mode": pipeline_params.get("homework_mode"),
        "assistance_level": pipeline_params.get("assistance_level"),
        "homework_level": options.assistance_level if options.homework_mode else None,
        "study_mode": options.study_mode,
        "followup_context_used": followup_context_used,
        "pipeline_trace": ctx.trace,
        "guardrails": guardrails_payload,
        **({"tutor_entrypoint": options.tutor_entrypoint} if options.tutor_entrypoint else {}),
        **({"grounded": grounded_debug} if grounded_debug else {}),
        **tutor_mode_debug,
    }


def _build_tutor_cycle_payload(
    *,
    options: QueryOptions,
    ctx: QueryContext,
    tutor_answer: dict[str, Any],
    auto_quiz_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    tutor_cycle_dict: dict[str, Any] | None = None
    if (options.query_mode or "").strip().lower() == "tutor" and not options.homework_mode:
        due_n = 0
        try:
            due_n = int(count_due_reviews_for_kg(get_active_graph_for_review()))
        except Exception as exc:  # noqa: BLE001 - non-critical optional enrichment
            logging.getLogger(__name__).debug("! caught exception: %s", exc)
        tutor_cycle_dict = build_tutor_cycle_state(
            session_id=options.session_id,
            due_reviews_count=due_n,
            auto_quiz_payload=auto_quiz_payload,
            tutor_answer_contract=tutor_answer,
        )
        if tutor_cycle_dict is not None and ctx is not None:
            from app.tutor_personalization_policy import personalization_hints

            md = ctx.metadata or {}
            lp = md.get("learner_profile") if isinstance(md.get("learner_profile"), dict) else {}
            tutor_cycle_dict["personalization_policy"] = personalization_hints(
                learning_goal=str(lp.get("learning_goal") or md.get("learning_goal") or "understand_topic"),
                mastery_level=str(lp.get("mastery_level") or md.get("mastery_level") or "intermediate"),
                due_reviews_count=due_n,
                weak_concepts=list(lp.get("weak_concepts") or []),
            )
    return tutor_cycle_dict


def _build_orchestration_state(
    *,
    options: QueryOptions,
    ctx: QueryContext,
    logger: logging.Logger,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    orchestration_state_dict: dict[str, Any] | None = None
    socratic_exposed: dict[str, Any] | None = None
    if (options.query_mode or "").strip().lower() == "tutor" and ctx is not None:
        from app.tutor_learner_contract import (
            build_orchestration_state_dict,
            persist_orchestration_state,
        )

        td = (ctx.metadata or {}).get("tutor_decision")
        md = ctx.metadata if isinstance(ctx.metadata, dict) else {}
        pipe_snap = md.get("tutor_orchestration_pipeline")
        orchestration_state_dict = build_orchestration_state_dict(
            tutor_decision=td if isinstance(td, dict) else None,
            session_metadata=md,
            tutor_orchestration_pipeline=pipe_snap if isinstance(pipe_snap, dict) else None,
        )
        try:
            persist_orchestration_state(orchestration_state_dict)
        except Exception as exc:  # noqa: BLE001 - persistence failure should not break answer
            log_event(
                logger,
                logging.WARNING,
                "persist_orchestration_state_failed",
                error=str(exc),
            )
        st = str((ctx.metadata or {}).get("socratic_type") or "").strip()
        if st:
            socratic_exposed = {"question_type": st}
    return orchestration_state_dict, socratic_exposed


def build_faq_cache_result(
    *,
    options: QueryOptions,
    ctx: QueryContext,
    execution_plan: Any,
    cached: dict[str, Any],
    sources: list[Any],
    confidence: dict[str, Any],
    pipeline_ms: float,
    total_ms: float,
    followup_context_used: bool,
    trace_schema: dict[str, Any],
    faq_retrieval_trace: dict[str, Any],
    tutor_answer: dict[str, Any],
    session_history: Any,
    tutor_mode_debug: dict[str, Any],
) -> dict[str, Any]:
    stage_usage = {
        "classify": ctx.trace.get("classify_usage"),
        "rewrite": ctx.trace.get("rewrite_usage"),
        "retrieval": None,
        "generation": None,
        "judge": None,
    }
    stage_costs = {
        "classify": ctx.trace.get("classify_estimated_cost_usd"),
        "rewrite": ctx.trace.get("rewrite_estimated_cost_usd"),
        "retrieval": None,
        "generation": None,
        "judge": None,
    }
    return {
        "answer": cached.get("answer", ""),
        "sources": sources,
        "confidence": confidence,
        "tutor_answer": tutor_answer,
        "debug": _build_faq_cache_debug_payload(
            options=options,
            ctx=ctx,
            execution_plan=execution_plan,
            cached=cached,
            pipeline_ms=pipeline_ms,
            total_ms=total_ms,
            followup_context_used=followup_context_used,
            trace_schema=trace_schema,
            faq_retrieval_trace=faq_retrieval_trace,
            stage_usage=stage_usage,
            stage_costs=stage_costs,
            session_history=session_history,
            tutor_mode_debug=tutor_mode_debug,
        ),
    }


def build_tutor_payloads(
    *,
    options: QueryOptions,
    ctx: QueryContext,
    proc_result: dict[str, Any],
    answer_text: str,
    logger: logging.Logger,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    tutor_teaching = proc_result["tutor_teaching"]
    inline_quiz = proc_result["inline_quiz"]
    socratic_followup = proc_result["socratic_followup"]
    auto_quiz_payload = proc_result["auto_quiz_payload"]
    tutor_decision = (getattr(ctx, "metadata", None) or {}).get("tutor_decision")
    learner_profile = (getattr(ctx, "metadata", None) or {}).get("persisted_learner_profile")
    tutor_answer = _normalize_tutor_answer_contract(
        answer_text=answer_text,
        tutor_teaching=tutor_teaching,
        tutor_decision=tutor_decision,
        auto_quiz_payload=auto_quiz_payload,
        inline_quiz=inline_quiz,
        socratic_followup=socratic_followup,
        learner_profile=learner_profile,
        query_context=ctx,
    )

    tutor_cycle_dict = _build_tutor_cycle_payload(
        options=options,
        ctx=ctx,
        tutor_answer=tutor_answer,
        auto_quiz_payload=auto_quiz_payload,
    )
    orchestration_state_dict, socratic_exposed = _build_orchestration_state(
        options=options,
        ctx=ctx,
        logger=logger,
    )

    pipe_contract = None
    pipe_steps = None
    if ctx is not None:
        md = ctx.metadata if isinstance(ctx.metadata, dict) else {}
        if isinstance(md.get("tutor_orchestration_pipeline"), dict):
            pipe_contract = md["tutor_orchestration_pipeline"]
        tr = getattr(ctx, "trace", None) or {}
        if isinstance(tr, dict) and isinstance(tr.get("tutor_pipeline"), list):
            pipe_steps = tr["tutor_pipeline"]

    tutor_payload = _build_tutor_payload(
        tutor_teaching=tutor_teaching,
        tutor_decision=tutor_decision,
        auto_quiz_payload=auto_quiz_payload,
        inline_quiz=inline_quiz,
        socratic_followup=socratic_followup,
        learner_profile=learner_profile,
        tutor_cycle=tutor_cycle_dict,
        orchestration_state=orchestration_state_dict,
        socratic=socratic_exposed,
        tutor_orchestration_pipeline=pipe_contract,
        tutor_pipeline=pipe_steps,
    )
    assistant_meta: dict[str, Any] | None = None
    if tutor_payload or tutor_answer:
        assistant_meta = {}
        if tutor_payload:
            assistant_meta["tutor"] = tutor_payload
        if tutor_answer:
            assistant_meta["tutor_answer"] = tutor_answer
    return tutor_answer, tutor_payload, assistant_meta


def build_rag_response_dict(
    *,
    options: QueryOptions,
    ctx: QueryContext,
    execution_plan: Any,
    answer_text: str,
    sources: list[Any],
    confidence: Any,
    tutor_payload: dict[str, Any],
    tutor_answer: dict[str, Any],
    session_history: Any,
    rag_result: dict[str, Any],
    pipeline_ms: float,
    total_ms: float,
    followup_context_used: bool,
    pii_redacted: bool,
    quality_checks: dict[str, Any],
    retrieval_trace: dict[str, Any],
    trace_schema: dict[str, Any],
    stage_usage: dict[str, Any],
    stage_costs: dict[str, Any],
    total_usage: dict[str, Any],
    tutor_mode_debug: dict[str, Any],
    answer_status: str | None = None,
    grounded_debug: dict[str, Any] | None = None,
    guardrails_grounded_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "answer": answer_text,
        "sources": sources,
        "confidence": confidence,
        "tutor": tutor_payload,
        "tutor_answer": tutor_answer,
        "debug": _build_rag_debug_payload(
            options=options,
            ctx=ctx,
            execution_plan=execution_plan,
            session_history=session_history,
            rag_result=rag_result,
            pipeline_ms=pipeline_ms,
            total_ms=total_ms,
            followup_context_used=followup_context_used,
            pii_redacted=pii_redacted,
            quality_checks=quality_checks,
            retrieval_trace=retrieval_trace,
            trace_schema=trace_schema,
            stage_usage=stage_usage,
            stage_costs=stage_costs,
            total_usage=total_usage,
            tutor_mode_debug=tutor_mode_debug,
            grounded_debug=grounded_debug,
            guardrails_grounded_patch=guardrails_grounded_patch,
        ),
    }
    if answer_status is not None:
        payload["answer_status"] = answer_status
    return payload
