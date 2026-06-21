import time
import traceback
import logging
from typing import Any
from threading import Lock

from app.config import get_settings
from app.latency_budget import (
    budget_meta_to_session_event,
    maybe_append_budget_tape_event,
    resolve_query_surface,
    with_budget,
)
from app.metrics import (
    PIPELINE_TRACE_SCHEMA_VERSION,
    RETRIEVAL_TRACE_SCHEMA_VERSION,
    check_pipeline_trace_schema,
    check_retrieval_trace_schema,
)
from app.guardrails import (
    OutputGuardrailError,
    apply_output_guardrails,
    redact_sensitive_text,
    should_apply_fallback,
)
from app.grounded_answer import apply_grounded_validation
from app.flashcard_handoff import flashcard_handoff_pipeline_overrides, is_flashcard_handoff
from app.logging_config import log_event, setup_logging
from app.models import PipelineOverrides, QueryContext, QueryOptions
from app.pipeline_runner import run_pipeline, update_pipeline_post_retrieval_trace
from app.query_fallbacks import build_safe_fallback_result
from app.query_rag_execution import (
    execute_rag_query,
)
from app.query_response_postprocessing import process_rag_response
from app.query_rag_assembly import (
    build_rag_response_dict,
    build_tutor_payloads,
    tutor_mode_debug as _tutor_mode_debug,
)
from app.query_faq_cache import try_faq_cache
from app.query_session_persistence import (
    persist_chat_session as _persist_chat_session,
)
from app.retrieval import build_query_engine, resolve_query_execution_plan
from app.usage_cost import (
    estimate_cost_usd,
    estimate_retrieval_embedding_usage,
    merge_token_usage,
    sum_costs,
)
from app.query_metrics import (
    _CONFIDENCE_THRESHOLDS,
    _retrieval_query_texts,
    _retrieval_stage_usage_cost,
    _build_retrieval_trace,
    _build_trace_schema_debug,
    _compute_deterministic_quality_checks,
    _compute_answer_confidence,
    _benchmark_lock,
    _answer_flow_stats,
    _avg,
    _record_answer_flow,
    get_answer_flow_stats,
    reset_answer_flow_stats,
)
from app.query_tutor_context import (
    _normalize_string_list,
    _build_tutor_payload,
    _enrich_tutor_payload_pipeline_scalars,
    _enrich_tutor_payload_orchestration_state_scalars,
    _resolve_mode_aware_tutor_next_step,
    _normalize_tutor_answer_contract,
    _initialize_tutor_context,
    _apply_tutor_context_fallback,
)


logger = setup_logging()


def _compose_study_mode_question(question: str, options: QueryOptions) -> tuple[str, bool]:
    followup_context = (options.followup_context or "").strip()
    if not options.study_mode or not followup_context:
        return question, False

    composed = (
        "Study mode follow-up.\n"
        "Previous context:\n"
        f"{followup_context}\n\n"
        "Current follow-up request:\n"
        f"{question}"
    )
    return composed, True


def _build_safe_fallback_result(
    *,
    error: OutputGuardrailError,
    cache_hit: bool,
    engine_acquire_ms: float,
    query_execute_ms: float,
    total_ms: float,
    pipeline_params: dict[str, Any],
    query_context: QueryContext | None = None,
):
    return build_safe_fallback_result(
        error=error,
        cache_hit=cache_hit,
        engine_acquire_ms=engine_acquire_ms,
        query_execute_ms=query_execute_ms,
        total_ms=total_ms,
        pipeline_params=pipeline_params,
        query_context=query_context,
        retrieval_stage_usage_cost_fn=_retrieval_stage_usage_cost,
        compute_quality_checks_fn=_compute_deterministic_quality_checks,
        build_retrieval_trace_fn=_build_retrieval_trace,
        build_trace_schema_debug_fn=_build_trace_schema_debug,
    )


def _prepare_query_context(
    question: str, options: QueryOptions
) -> tuple[QueryContext, str, bool, float]:
    """Подготовка QueryContext, включая выполнение пайплайна и инициализацию Tutor."""
    effective_input_question, followup_context_used = _compose_study_mode_question(
        question, options
    )

    log_event(
        logger,
        logging.INFO,
        "answer_question_started",
        question=redact_sensitive_text(question),
        folder=options.folder,
        folder_rel=options.folder_rel,
        file_name=options.file_name,
        relative_path=options.relative_path,
        study_mode=options.study_mode,
        homework_mode=options.homework_mode,
    )

    pipeline_started = time.perf_counter()
    ctx = run_pipeline(effective_input_question, options)
    pipeline_ms = (time.perf_counter() - pipeline_started) * 1000
    ctx.trace.setdefault("prompt_selector_contract", "adr021_phase3")

    if (options.query_mode or "").strip().lower() == "tutor":
        try:
            _initialize_tutor_context(ctx, options)
        except Exception as e:  # noqa: BLE001 - tutor context is optional enrichment; fallback keeps tutor /ask alive.
            log_event(
                logger,
                logging.WARNING,
                "tutor_context_initialization_failed",
                error=str(e),
            )
            _apply_tutor_context_fallback(ctx, options, str(e))

    return ctx, effective_input_question, followup_context_used, pipeline_ms


def _execute_rag_query(
    ctx: QueryContext,
    options: QueryOptions,
    execution_plan: Any,
) -> dict[str, Any]:
    """Выполнение RAG-запроса через QueryEngine с поддержкой self-correction и трейсинга."""
    return execute_rag_query(
        ctx,
        options,
        execution_plan,
        build_query_engine_fn=build_query_engine,
        logger=logger,
    )


def _process_rag_response(
    response: Any,
    ctx: QueryContext,
    options: QueryOptions,
    retrieval_sc: dict[str, Any],
    pipeline_params: dict[str, Any],
    accumulated_rag_generation_usage: Any,
    original_question: str,
) -> dict[str, Any]:
    """Пост-обработка ответа: парсинг Tutor-тегов, обогащение источников, запуск авто-квизов."""
    return process_rag_response(
        response,
        ctx,
        options,
        retrieval_sc,
        pipeline_params,
        accumulated_rag_generation_usage,
        original_question,
        logger=logger,
    )


def _build_stage_usage_and_costs(
    *,
    ctx: QueryContext,
    pipeline_params: dict[str, Any],
    generation_usage: Any,
    generation_cost: float | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    r_usage, r_cost = _retrieval_stage_usage_cost(
        retrieval_mode=pipeline_params.get("retrieval_mode"),
        effective_question=ctx.effective_query,
        ctx=ctx,
    )
    stage_usage = {
        "classify": ctx.trace.get("classify_usage"),
        "rewrite": ctx.trace.get("rewrite_usage"),
        "retrieval": r_usage,
        "generation": generation_usage,
        "judge": None,
    }
    stage_costs = {
        "classify": ctx.trace.get("classify_estimated_cost_usd"),
        "rewrite": ctx.trace.get("rewrite_estimated_cost_usd"),
        "retrieval": r_cost,
        "generation": generation_cost,
        "judge": None,
    }
    total_usage = merge_token_usage(
        stage_usage["classify"],
        stage_usage["rewrite"],
        stage_usage["retrieval"],
        stage_usage["generation"],
        stage_usage["judge"],
    )
    return stage_usage, stage_costs, total_usage


def _apply_rag_answer_grounding(
    answer_text: str,
    sources: list[Any],
    options: QueryOptions,
    cache_hit: bool,
    answer_path_mode: str | None,
) -> tuple[str, bool, str | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Grounded validation, output guardrails и PII-флаг."""
    grounded = apply_grounded_validation(
        answer_text=answer_text,
        sources=sources,
        query_mode=options.query_mode,
        homework_mode=bool(options.homework_mode),
        assistance_level=options.assistance_level,
        cache_hit=cache_hit,
        answer_path_mode=answer_path_mode,
    )
    answer_text = grounded.answer_text
    answer_text, pii_redacted = apply_output_guardrails(answer_text, sources)
    grounded_debug = grounded.debug if grounded.debug else None
    return (
        answer_text,
        pii_redacted,
        grounded.answer_status,
        grounded_debug,
        grounded.guardrails_patch,
    )


def _build_generation_model_and_metadata(
    pipeline_params: dict[str, Any],
    generation_message_roles: Any,
) -> tuple[str, dict[str, Any]]:
    generation_model = (
        pipeline_params.get("generation_model")
        or pipeline_params.get("llm_model")
        or get_settings().llm_model
    )
    generation_source_metadata = {
        key: pipeline_params.get(key)
        for key in ("llm_source", "llm_model", "llm_api_base", "fallback_used", "llm_profile")
        if pipeline_params.get(key) is not None
    }
    if generation_message_roles:
        generation_source_metadata["chat_message_roles"] = generation_message_roles
    return generation_model, generation_source_metadata


def _rag_assembly_answer_trace_and_usage(
    ctx: QueryContext,
    execution_plan: Any,
    rag_result: dict[str, Any],
    proc_result: dict[str, Any],
) -> tuple[
    QueryContext,
    str,
    bool,
    Any,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    str | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    """Guardrails, confidence, retrieval/generation usage и стоимости по стадиям."""
    answer_text = proc_result["answer_text"]
    sources = proc_result["sources"]
    generation_usage = proc_result["generation_usage"]
    cache_hit = rag_result["cache_hit"]
    pipeline_params = rag_result["pipeline_params"]
    options = getattr(ctx, "query_options", None) if ctx is not None else None
    if options is None:
        options = QueryOptions()
    answer_path = ctx.trace.get("answer_path") if ctx is not None else None
    answer_path_mode = answer_path.get("mode") if isinstance(answer_path, dict) else None

    (
        answer_text,
        pii_redacted,
        answer_status,
        grounded_debug,
        guardrails_grounded_patch,
    ) = _apply_rag_answer_grounding(
        answer_text,
        sources,
        options,
        cache_hit,
        answer_path_mode,
    )
    confidence = _compute_answer_confidence(
        sources,
        ctx.query_type,
        ctx.classify_confidence,
    )
    generation_model, generation_source_metadata = _build_generation_model_and_metadata(
        pipeline_params,
        rag_result.get("generation_message_roles"),
    )
    if ctx is not None and execution_plan is not None:
        ctx = update_pipeline_post_retrieval_trace(
            ctx,
            execution_plan,
            cache_hit=cache_hit,
            source_count=len(sources),
            generation_model=generation_model,
            llm_source_metadata=generation_source_metadata,
            latency_ms=rag_result.get("query_execute_ms"),
            answer_length=len(answer_text),
        )
    generation_cost = estimate_cost_usd(generation_model, generation_usage)
    quality_checks = _compute_deterministic_quality_checks(
        answer_text,
        sources,
        fallback_applied=False,
    )
    retrieval_trace = _build_retrieval_trace(
        pipeline_params,
        sources,
        cache_hit=cache_hit,
        effective_query=ctx.effective_query,
        effective_query_source=ctx.effective_query_source,
    )
    trace_schema = _build_trace_schema_debug(ctx.trace, retrieval_trace)
    stage_usage, stage_costs, total_usage = _build_stage_usage_and_costs(
        ctx=ctx,
        pipeline_params=pipeline_params,
        generation_usage=generation_usage,
        generation_cost=generation_cost,
    )
    return (
        ctx,
        answer_text,
        pii_redacted,
        confidence,
        quality_checks,
        retrieval_trace,
        trace_schema,
        stage_usage,
        stage_costs,
        total_usage,
        answer_status,
        grounded_debug,
        guardrails_grounded_patch,
    )


def _rag_assembly_tutor_payloads(
    options: QueryOptions,
    ctx: QueryContext,
    proc_result: dict[str, Any],
    answer_text: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    """Tutor-контракт, цикл, оркестрация и внешний tutor payload."""
    return build_tutor_payloads(
        options=options,
        ctx=ctx,
        proc_result=proc_result,
        answer_text=answer_text,
        logger=logger,
    )


def _rag_assembly_response_dict(
    *,
    options: QueryOptions,
    ctx: QueryContext,
    execution_plan: Any,
    answer_text: str,
    sources: list[Any],
    confidence: Any,
    tutor_payload: dict[str, Any],
    tutor_answer: dict[str, Any],
    assistant_meta: dict[str, Any] | None,
    _sess_hist: Any,
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
    answer_status: str | None = None,
    grounded_debug: dict[str, Any] | None = None,
    guardrails_grounded_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Итоговый JSON ответа (поле debug и контракт сверху)."""
    return build_rag_response_dict(
        options=options,
        ctx=ctx,
        execution_plan=execution_plan,
        answer_text=answer_text,
        sources=sources,
        confidence=confidence,
        tutor_payload=tutor_payload,
        tutor_answer=tutor_answer,
        session_history=_sess_hist,
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
        tutor_mode_debug=_tutor_mode_debug(ctx, options),
        answer_status=answer_status,
        grounded_debug=grounded_debug,
        guardrails_grounded_patch=guardrails_grounded_patch,
    )


def _log_rag_answer_completion(
    *,
    cache_hit: bool,
    total_ms: float,
    engine_build_ms: float,
    rag_ms: float,
    sources: list[Any],
    ctx: QueryContext,
    retrieval_ms: float | None = None,
    llm_ms: float | None = None,
    auto_quiz_ms: float | None = None,
    inline_quiz_ms: float | None = None,
    engine_cache_lookup_ms: float | None = None,
    tutor_entrypoint: str | None = None,
) -> None:
    source_count = len(sources)
    post_ms = round(max(0.0, total_ms - engine_build_ms - rag_ms), 3)
    quiz_ms = (auto_quiz_ms or 0.0) + (inline_quiz_ms or 0.0)
    fields: dict[str, Any] = {
        "cache_hit": cache_hit,
        "total_ms": round(total_ms, 3),
        "engine_build_ms": round(engine_build_ms, 3),
        "rag_ms": round(rag_ms, 3),
        "post_processing_ms": post_ms,
        "source_count": source_count,
        "query_type": ctx.query_type if ctx else None,
    }
    if retrieval_ms is not None:
        fields["retrieval_ms"] = round(retrieval_ms, 3)
    if llm_ms is not None:
        fields["llm_ms"] = round(llm_ms, 3)
    if auto_quiz_ms is not None:
        fields["auto_quiz_ms"] = round(auto_quiz_ms, 3)
    if inline_quiz_ms is not None:
        fields["inline_quiz_ms"] = round(inline_quiz_ms, 3)
    if quiz_ms > 0:
        fields["post_processing_excl_quiz_ms"] = round(max(0.0, post_ms - quiz_ms), 3)
    if engine_cache_lookup_ms is not None:
        fields["engine_cache_lookup_ms"] = round(engine_cache_lookup_ms, 3)
    if tutor_entrypoint:
        fields["tutor_entrypoint"] = tutor_entrypoint
    log_event(logger, logging.INFO, "answer_question_completed", **fields)


def _record_rag_timing(
    *,
    started_at: float,
    cache_hit: bool,
    engine_acquire_ms: float,
    query_execute_ms: float,
) -> float:
    total_ms = (time.perf_counter() - started_at) * 1000
    _record_answer_flow(
        cache_hit=cache_hit,
        engine_acquire_ms=engine_acquire_ms,
        query_execute_ms=query_execute_ms,
        total_ms=total_ms,
    )
    return total_ms


def _assemble_rag_result(
    question: str,
    options: QueryOptions,
    ctx: QueryContext,
    execution_plan: Any,
    rag_result: dict[str, Any],
    proc_result: dict[str, Any],
    started_at: float,
    pipeline_ms: float,
    followup_context_used: bool,
) -> dict[str, Any]:
    """Сборка финального JSON-ответа: guardrails, метрики, контракты Tutor и персистентность."""
    sources = proc_result["sources"]
    cache_hit = rag_result["cache_hit"]
    engine_acquire_ms = rag_result["engine_acquire_ms"]
    query_execute_ms = rag_result["query_execute_ms"]

    total_ms = _record_rag_timing(
        started_at=started_at,
        cache_hit=cache_hit,
        engine_acquire_ms=engine_acquire_ms,
        query_execute_ms=query_execute_ms,
    )
    _log_rag_answer_completion(
        cache_hit=cache_hit,
        total_ms=total_ms,
        engine_build_ms=engine_acquire_ms,
        rag_ms=query_execute_ms,
        sources=sources,
        ctx=ctx,
        retrieval_ms=rag_result.get("retrieval_ms"),
        llm_ms=rag_result.get("llm_ms"),
        auto_quiz_ms=proc_result.get("auto_quiz_ms"),
        inline_quiz_ms=proc_result.get("inline_quiz_ms"),
        engine_cache_lookup_ms=rag_result.get("engine_cache_lookup_ms"),
        tutor_entrypoint=getattr(options, "tutor_entrypoint", None),
    )

    (
        ctx,
        answer_text,
        pii_redacted,
        confidence,
        quality_checks,
        retrieval_trace,
        trace_schema,
        stage_usage,
        stage_costs,
        total_usage,
        answer_status,
        grounded_debug,
        guardrails_grounded_patch,
    ) = _rag_assembly_answer_trace_and_usage(ctx, execution_plan, rag_result, proc_result)

    tutor_answer, tutor_payload, assistant_meta = _rag_assembly_tutor_payloads(
        options, ctx, proc_result, answer_text
    )

    _sess_hist = _persist_chat_session(
        session_id=options.session_id,
        user_question=question,
        assistant_answer=answer_text,
        confidence=confidence,
        assistant_metadata=assistant_meta,
        sources=sources,
    )

    post_ms = round(max(0.0, total_ms - engine_acquire_ms - query_execute_ms), 3)
    rag_result_debug = {
        **rag_result,
        "post_processing_ms": post_ms,
        "auto_quiz_ms": proc_result.get("auto_quiz_ms"),
        "inline_quiz_ms": proc_result.get("inline_quiz_ms"),
    }

    return _rag_assembly_response_dict(
        options=options,
        ctx=ctx,
        execution_plan=execution_plan,
        answer_text=answer_text,
        sources=sources,
        confidence=confidence,
        tutor_payload=tutor_payload,
        tutor_answer=tutor_answer,
        assistant_meta=assistant_meta,
        _sess_hist=_sess_hist,
        rag_result=rag_result_debug,
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
        answer_status=answer_status,
        grounded_debug=grounded_debug,
        guardrails_grounded_patch=guardrails_grounded_patch,
    )


def _resolve_execution_plan_for_question(
    effective_question: str,
    options: QueryOptions,
    ctx: QueryContext,
):
    overrides: PipelineOverrides | None = None
    if is_flashcard_handoff(options):
        overrides = flashcard_handoff_pipeline_overrides()
    elif options.rag_profile:
        overrides = PipelineOverrides(rag_profile=options.rag_profile)
    if overrides is None:
        return resolve_query_execution_plan(
            effective_question,
            options,
            query_context=ctx,
        )
    return resolve_query_execution_plan(
        effective_question,
        options,
        query_context=ctx,
        overrides=overrides,
    )


def _answer_question_main_flow(
    *,
    question: str,
    options: QueryOptions,
    ctx: QueryContext,
    pipeline_ms: float,
    followup_context_used: bool,
    started_at: float,
) -> dict[str, Any]:
    effective_question = ctx.effective_query
    execution_plan = _resolve_execution_plan_for_question(effective_question, options, ctx)

    faq_result = try_faq_cache(
        ctx,
        options,
        execution_plan,
        started_at,
        pipeline_ms,
        question,
        followup_context_used,
        tutor_mode_debug_fn=_tutor_mode_debug,
    )
    if faq_result:
        return faq_result

    rag_result = _execute_rag_query(ctx, options, execution_plan)
    proc_result = _process_rag_response(
        response=rag_result["response"],
        ctx=ctx,
        options=options,
        retrieval_sc=rag_result["retrieval_sc"],
        pipeline_params=rag_result["pipeline_params"],
        accumulated_rag_generation_usage=rag_result["accumulated_usage"],
        original_question=question,
    )
    return _assemble_rag_result(
        question=question,
        options=options,
        ctx=ctx,
        execution_plan=execution_plan,
        rag_result=rag_result,
        proc_result=proc_result,
        started_at=started_at,
        pipeline_ms=pipeline_ms,
        followup_context_used=followup_context_used,
    )


def _merge_latency_budget_debug(result: Any, meta) -> Any:
    if not isinstance(result, dict):
        return result
    debug = dict(result.get("debug") or {})
    debug["latency_budget"] = budget_meta_to_session_event(meta)
    return {**result, "debug": debug}


def _finalize_budgeted_answer(result: Any, meta, options: QueryOptions) -> Any:
    merged = _merge_latency_budget_debug(result, meta)
    maybe_append_budget_tape_event(
        options.session_id,
        meta,
        course_id=options.folder_rel or options.folder,
    )
    return merged


def _build_timeout_answer(elapsed: float, error_type: str, *, include_timed_out: bool) -> dict[str, Any]:
    result = {
        "answer": "Модель не ответила вовремя. Попробуйте ещё раз через несколько секунд.",
        "sources": [],
        "debug": {
            "cache_hit": False,
            "total_answer_ms": round(elapsed * 1000, 3),
            "error_type": error_type,
            "fallback_applied": True,
        },
    }
    if include_timed_out:
        result["timed_out"] = True
    return result


def _handle_answer_question_exception(
    e: Exception,
    *,
    started_at: float,
    question: str,
    options: QueryOptions,
    include_timed_out: bool,
) -> dict[str, Any]:
    import httpx
    import openai

    elapsed = time.perf_counter() - started_at

    if isinstance(e, (openai.APITimeoutError, httpx.ReadTimeout, httpx.TimeoutException)):
        log_event(
            logger,
            logging.WARNING,
            "answer_question_llm_timeout",
            elapsed_sec=round(elapsed, 3),
            question=redact_sensitive_text(question),
            error_type=type(e).__name__,
        )
        return _build_timeout_answer(elapsed, type(e).__name__, include_timed_out=include_timed_out)

    log_event(
        logger,
        logging.ERROR,
        "answer_question_failed",
        elapsed_sec=round(elapsed, 3),
        question=redact_sensitive_text(question),
        folder=options.folder,
        folder_rel=options.folder_rel,
        file_name=options.file_name,
        relative_path=options.relative_path,
        error_type=type(e).__name__,
        error=str(e),
    )
    log_event(logger, logging.ERROR, "answer_question_traceback", traceback=traceback.format_exc())
    raise


def _handle_output_guardrail_fallback(
    e: OutputGuardrailError,
    *,
    started_at: float,
    question: str,
    cache_hit: bool,
    engine_acquire_ms: float,
    query_execute_ms: float,
    pipeline_params: dict[str, Any],
    ctx: Any,
) -> dict[str, Any]:
    if not should_apply_fallback(e.code):
        raise
    total_ms = (time.perf_counter() - started_at) * 1000
    log_event(
        logger,
        logging.WARNING,
        "output_guardrail_triggered",
        code=e.code,
        message=str(e),
        question=redact_sensitive_text(question),
    )
    return _build_safe_fallback_result(
        error=e,
        cache_hit=cache_hit,
        engine_acquire_ms=engine_acquire_ms,
        query_execute_ms=query_execute_ms,
        total_ms=total_ms,
        pipeline_params=pipeline_params,
        query_context=ctx,
    ) | {"answer_status": "guardrails_fallback"}


def answer_question(question: str, options: QueryOptions):
    started_at = time.perf_counter()
    cache_hit = False
    engine_acquire_ms = 0.0
    query_execute_ms = 0.0
    pipeline_params: dict[str, Any] = {}
    ctx = None

    try:
        ctx, _, followup_context_used, pipeline_ms = _prepare_query_context(question, options)
    except OutputGuardrailError as e:
        return _handle_output_guardrail_fallback(
            e,
            started_at=started_at,
            question=question,
            cache_hit=cache_hit,
            engine_acquire_ms=engine_acquire_ms,
            query_execute_ms=query_execute_ms,
            pipeline_params=pipeline_params,
            ctx=ctx,
        )
    except Exception as e:  # noqa: BLE001 - prepare failures handled before budget wrap
        return _handle_answer_question_exception(
            e,
            started_at=started_at,
            question=question,
            options=options,
            include_timed_out=True,
        )

    surface = resolve_query_surface(options)

    def _budgeted_answer():
        try:
            return _answer_question_main_flow(
                question=question,
                options=options,
                ctx=ctx,
                pipeline_ms=pipeline_ms,
                followup_context_used=followup_context_used,
                started_at=started_at,
            )
        except OutputGuardrailError as e:
            return _handle_output_guardrail_fallback(
                e,
                started_at=started_at,
                question=question,
                cache_hit=cache_hit,
                engine_acquire_ms=engine_acquire_ms,
                query_execute_ms=query_execute_ms,
                pipeline_params=pipeline_params,
                ctx=ctx,
            )
        except Exception as e:  # noqa: BLE001 - general query/LLM failures handled gracefully with fallback/timeout logs or raised
            return _handle_answer_question_exception(
                e,
                started_at=started_at,
                question=question,
                options=options,
                include_timed_out=False,
            )

    budget = with_budget(surface, _budgeted_answer)
    return _finalize_budgeted_answer(budget.result, budget.meta, options)
