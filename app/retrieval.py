"""Retrieval orchestration (execution plan, query engine).

US-3.6 (MoT#2): ветвление «ранний extractive vs полная LLM-генерация» выполняется в
``app.query_rag_execution.execute_rag_query`` (см. ``ctx.trace["answer_path"]`` и
``Settings.enable_two_stage_answer_path``).
"""

import logging
from typing import Any, Optional

from app.rag_runtime_preferences import effective_retrieval_settings, effective_settings
from app.flashcard_handoff import handoff_llm_with_output_cap, is_flashcard_handoff
from app.llm_guards import resolve_rag_context_token_budget
from app.provider import llm_source_metadata
from app.retrieval_strategies import (
    DocThenChunkRetriever,
    _merge_filters,
    build_query_engine_for_retrieval_mode,
)
from app.logging_config import log_event, setup_logging
from app.models import PipelineOverrides, QueryContext, QueryExecutionPlan, QueryOptions
from app.graph_retrieval import append_graph_expansion_postprocessor
from app.lost_in_middle_reorder import append_lost_in_middle_reorder_postprocessor
from app.multi_query_expansion import prepare_multi_query_expansion, wrap_engine_for_multi_query
from app.pipeline_factory import (
    build_filters,
    build_postprocessors,
    resolve_pipeline_params,
)
from app.pipeline_runner import resolve_retrieval_strategy
from app.prompts import KEYWORD_PROMPT, PROMPTS, QA_PROMPT, get_homework_prompt
from app.query_routing import KEYWORD_QUERY, detect_query_type
from app.retrieval_cache import (
    get_base_services,
    get_query_engine_cache_result,
    set_cached_query_engine,
)
from app.retrieval_context_budget import append_context_budget_postprocessor
from app.retrieval_router import resolve_retrieval_routing

logger = setup_logging()


def _attach_llm_source_metadata(params: dict[str, Any], llm: Any) -> dict[str, Any]:
    meta = llm_source_metadata(llm)
    params.update({k: v for k, v in meta.items() if v is not None})
    return params


def _maybe_boost_first_turn_hybrid(
    effective_retrieval_mode: str,
    query_type: str,
    query_context: QueryContext,
    overrides: Optional[PipelineOverrides],
) -> tuple[str, bool]:
    """US-3.4: первый user-turn в сессии или cold ask без session_id — не оставаться на vector_only."""
    if overrides is not None and getattr(overrides, "retrieval_mode", None):
        return effective_retrieval_mode, False
    if query_type in (KEYWORD_QUERY, "keyword"):
        return effective_retrieval_mode, False
    if effective_retrieval_mode != "vector_only":
        return effective_retrieval_mode, False
    meta = getattr(query_context, "metadata", None) or {}
    turns = meta.get("session_user_turns_before")
    opts = getattr(query_context, "query_options", None)
    sid = (opts.session_id or "").strip() if opts else ""
    first_turn = (turns == 0) or (turns is None and not sid)
    if not first_turn:
        return effective_retrieval_mode, False
    if query_type not in ("qa", "overview", "synthesis", "learning_plan"):
        return effective_retrieval_mode, False
    return "hybrid", True


def _faq_cache_policy(
    *,
    faq_cache_enabled: bool,
    query_type: str,
    options: QueryOptions,
) -> tuple[bool, str | None]:
    if not faq_cache_enabled:
        return False, "disabled"
    if query_type != "qa":
        return False, "non_qa"
    if options.study_mode:
        return False, "study_mode"
    if bool((options.session_id or "").strip()):
        return False, "session_id"
    if (options.query_mode or "").strip().lower() == "tutor":
        return False, "tutor_mode"
    return True, None


def _is_study_quiz_generation_request(question: str, options: QueryOptions) -> bool:
    if not options.study_mode:
        return False
    q = (question or "").casefold()
    return any(
        marker in q
        for marker in (
            "quiz",
            "test",
            "self-check",
            "multiple-choice",
            "multiple choice",
            "вариант",
            "тест",
            "квиз",
            "вопрос",
        )
    )


def _build_query_execution_plan(
    *,
    query_type: str,
    prompt_key: str,
    retrieval_mode: str,
    enable_reranker: bool,
    params: dict[str, object],
    options: QueryOptions,
    cache_policy: str,
    faq_cache_eligible: bool,
    faq_cache_skip_reason: str | None,
) -> QueryExecutionPlan:
    return QueryExecutionPlan(
        query_type=query_type,
        prompt_key=prompt_key,
        retrieval_mode=retrieval_mode,
        enable_reranker=enable_reranker,
        similarity_top_k=int(params["similarity_top_k"]),
        rerank_top_n=int(params["rerank_top_n"]),
        rerank_model=str(params["rerank_model"]),
        split_strategy=str(params["split_strategy"]),
        window_size=int(params["window_size"]),
        profile=str(params["profile"]),
        homework_mode=options.homework_mode,
        assistance_level=options.assistance_level,
        query_engine_cache_policy=cache_policy,
        faq_cache_eligible=faq_cache_eligible,
        faq_cache_skip_reason=faq_cache_skip_reason,
        doc_top_k=(int(params["doc_top_k"]) if "doc_top_k" in params and params["doc_top_k"] is not None else None),
    )


def _resolve_effective_prompt(
    *,
    execution_plan: QueryExecutionPlan,
    options: QueryOptions,
    query_context: Optional[QueryContext],
):
    if execution_plan.prompt_key == "keyword":
        return KEYWORD_PROMPT
    if execution_plan.prompt_key == "homework":
        return get_homework_prompt(options.assistance_level)
    if execution_plan.prompt_key == "tutor":
        if is_flashcard_handoff(options):
            from app.tutor_prompts import build_flashcard_handoff_tutor_prompt

            return build_flashcard_handoff_tutor_prompt()
        from app.tutor_prompts import build_tutor_rag_prompt_with_quiz_difficulty

        metadata = (query_context.metadata or {}) if query_context is not None else {}
        lvl = metadata.get("quiz_difficulty") or "recognition"
        soc = metadata.get("socratic_type") or "probing"
        lg = metadata.get("learning_goal") or "understand_topic"
        ad = metadata.get("answer_depth") or "examples"
        ps = metadata.get("preferred_style") or "balanced"
        s = effective_settings()
        _inline_in_main = s.enable_tutor_inline_quiz and not s.tutor_inline_quiz_separate_llm_call
        return build_tutor_rag_prompt_with_quiz_difficulty(
            str(lvl),
            socratic_type=str(soc),
            include_inline_quiz=_inline_in_main,
            learning_goal=str(lg),
            answer_depth=str(ad),
            preferred_style=str(ps),
        )
    if query_context is not None:
        return PROMPTS.get(query_context.prompt_key, QA_PROMPT)
    return QA_PROMPT


def resolve_query_execution_plan(
    question: str,
    options: QueryOptions,
    query_context: Optional[QueryContext] = None,
    overrides: Optional[PipelineOverrides] = None,
) -> QueryExecutionPlan:
    if overrides is None and options.rag_profile:
        overrides = PipelineOverrides(rag_profile=options.rag_profile)

    if query_context is not None:
        overrides = resolve_retrieval_routing(query_context, options, overrides)
        params = resolve_pipeline_params(overrides=overrides)
        query_type = query_context.query_type
        effective_retrieval_mode = resolve_retrieval_strategy(
            query_context, overrides=overrides,
        )
        mode_after_boost, boost_applied = _maybe_boost_first_turn_hybrid(
            effective_retrieval_mode,
            query_type,
            query_context,
            overrides,
        )
        effective_retrieval_mode = mode_after_boost
        if boost_applied:
            query_context.trace["smart_default_retrieval"] = {
                "applied": True,
                "from_mode": "vector_only",
                "to_mode": "hybrid",
                "reason": "first_turn_or_cold_ask_us_3_4",
            }
        effective_reranker_enabled = (
            False if query_type == KEYWORD_QUERY else params["enable_reranker"]
        )
        prompt_key = query_context.prompt_key
    else:
        params = resolve_pipeline_params(overrides=overrides)
        query_type = detect_query_type(question)
        effective_retrieval_mode = (
            "bm25_only" if query_type == KEYWORD_QUERY else params["retrieval_mode"]
        )
        effective_reranker_enabled = (
            False if query_type == KEYWORD_QUERY else params["enable_reranker"]
        )
        prompt_key = "keyword" if query_type == KEYWORD_QUERY else "qa"

    if _is_study_quiz_generation_request(question, options):
        query_type = "qa"
        prompt_key = "qa"
        if effective_retrieval_mode == "bm25_only":
            effective_retrieval_mode = str(params["retrieval_mode"])
        effective_reranker_enabled = bool(params["enable_reranker"])

    tutor_mode = (options.query_mode or "").strip().lower() == "tutor"
    if options.homework_mode and (query_type == "qa" or tutor_mode):
        prompt_key = "homework"
    elif tutor_mode and not options.homework_mode:
        prompt_key = "tutor"

    cache_policy = (
        "shared"
        if is_flashcard_handoff(options)
        else (
            "disabled_for_session"
            if bool((options.session_id or "").strip())
            else "shared"
        )
    )
    faq_cache_eligible, faq_cache_skip_reason = _faq_cache_policy(
        faq_cache_enabled=effective_settings().enable_faq_cache,
        query_type=query_type,
        options=options,
    )

    return _build_query_execution_plan(
        query_type=query_type,
        prompt_key=prompt_key,
        retrieval_mode=effective_retrieval_mode,
        enable_reranker=effective_reranker_enabled,
        params=params,
        options=options,
        cache_policy=cache_policy,
        faq_cache_eligible=faq_cache_eligible,
        faq_cache_skip_reason=faq_cache_skip_reason,
    )


def build_query_engine(
    question: str,
    options: QueryOptions,
    query_context: Optional[QueryContext] = None,
    overrides: Optional[PipelineOverrides] = None,
    execution_plan: Optional[QueryExecutionPlan] = None,
) -> dict[str, Any]:
    settings = effective_settings()
    retrieval_settings = effective_retrieval_settings()
    filters = build_filters(options)
    execution_plan = execution_plan or resolve_query_execution_plan(
        question,
        options,
        query_context=query_context,
        overrides=overrides,
    )
    effective_params = execution_plan.to_pipeline_params()
    query_type = execution_plan.query_type
    effective_prompt = _resolve_effective_prompt(
        execution_plan=execution_plan,
        options=options,
        query_context=query_context,
    )

    tutor_quiz_diff = ""
    tutor_socratic = ""
    tutor_learning_goal = ""
    tutor_answer_depth = ""
    tutor_preferred_style = ""
    if query_context is not None and (options.query_mode or "").strip().lower() == "tutor":
        tutor_quiz_diff = (query_context.metadata or {}).get("quiz_difficulty") or "recognition"
        tutor_socratic = (query_context.metadata or {}).get("socratic_type") or "probing"
        tutor_learning_goal = (query_context.metadata or {}).get("learning_goal") or "understand_topic"
        tutor_answer_depth = (query_context.metadata or {}).get("answer_depth") or "examples"
        tutor_preferred_style = (query_context.metadata or {}).get("preferred_style") or "balanced"

    cache_allowed = execution_plan.query_engine_cache_policy == "shared"

    # Cache key covers only parameters that determine engine/prompt structure.
    # Dynamic per-query fields (question text, learner hints, orchestration hints,
    # recent-topic history) are intentionally excluded — they change every request
    # and would make the cache useless. Those hints are injected at query time in
    # execute_rag_query instead. Filters already encode folder/file/topic scope, so
    # options.cache_key() (which duplicates filters + adds volatile session fields)
    # is omitted here.
    # is_flashcard_handoff is included because it selects a different prompt template
    # (_resolve_effective_prompt) even when profile/mode/retrieval dims are identical.
    cache_key = (
        "query_engine",
        execution_plan.query_type,
        execution_plan.profile,
        execution_plan.retrieval_mode,
        execution_plan.similarity_top_k,
        execution_plan.enable_reranker,
        execution_plan.rerank_top_n,
        execution_plan.rerank_model,
        execution_plan.split_strategy,
        repr(filters),
        options.homework_mode,
        options.assistance_level,
        (options.query_mode or ""),
        settings.enable_tutor_inline_quiz,
        settings.tutor_inline_quiz_separate_llm_call,
        tutor_quiz_diff,
        tutor_socratic,
        tutor_learning_goal,
        tutor_answer_depth,
        tutor_preferred_style,
        settings.enable_tutor_pedagogical_orchestrator,
        settings.enable_graph_augmented_retrieval,
        settings.graph_augment_max_extra_docs,
        resolve_rag_context_token_budget(settings.rag_context_token_budget),
        retrieval_settings.enable_multi_query,
        retrieval_settings.multi_query_count,
        retrieval_settings.enable_lost_in_middle_reorder,
        is_flashcard_handoff(options),
    )

    if cache_allowed:
        cache_result = get_query_engine_cache_result(cache_key)
        cached_engine = cache_result["engine"]
    else:
        cache_result = {
            "engine": None,
            "cache_hit": False,
            "cache_latency_ms": 0.0,
        }
        cached_engine = None

    if cached_engine is not None:
        effective_params = _attach_llm_source_metadata(effective_params, get_base_services()["llm"])
        log_event(
            logger,
            logging.INFO,
            "query_engine_cache_hit",
            cache_key=repr(cache_key),
            query_type=execution_plan.query_type,
            retrieval_mode=execution_plan.retrieval_mode,
        )
        return {
            "engine": cached_engine,
            "cache_hit": True,
            "cache_key": cache_key,
            "engine_cache_lookup_ms": cache_result["cache_latency_ms"],
            "filters": repr(filters),
            "pipeline_params": effective_params,
        }

    services = get_base_services()
    index = services["index"]
    llm = services["llm"]
    if is_flashcard_handoff(options):
        llm = handoff_llm_with_output_cap(llm)
    effective_params = _attach_llm_source_metadata(effective_params, llm)
    collection = services["collection"]
    summary_index = services.get("summary_index")
    postprocessors = build_postprocessors(effective_params)
    rr_raw: dict[str, Any] = {}
    if query_context is not None:
        tr = query_context.trace or {}
        maybe_rr = tr.get("retrieval_routing")
        if isinstance(maybe_rr, dict):
            rr_raw = maybe_rr
    use_gating_ctx = query_context is not None
    if use_gating_ctx and rr_raw:
        eff_ga = bool(rr_raw.get("effective_graph_augmented"))
    elif use_gating_ctx:
        eff_ga = bool(settings.enable_graph_augmented_retrieval)
    else:
        eff_ga = True
    classify_cf = (
        float(query_context.classify_confidence) if query_context is not None else 1.0
    )
    postprocessors = append_graph_expansion_postprocessor(
        postprocessors,
        execution_plan_query_type=execution_plan.query_type,
        base_index=index,
        filters=filters,
        similarity_top_k=execution_plan.similarity_top_k,
        classify_confidence=classify_cf,
        effective_profile=execution_plan.profile,
        effective_graph_augmented=eff_ga,
        use_composite_graph_gating=use_gating_ctx,
    )
    postprocessors = append_context_budget_postprocessor(postprocessors)
    postprocessors = append_lost_in_middle_reorder_postprocessor(postprocessors)

    retrieval_mode = execution_plan.retrieval_mode

    log_event(
        logger,
        logging.INFO,
        "query_engine_build_started",
        profile=execution_plan.profile,
        query_type=execution_plan.query_type,
        retrieval_mode=retrieval_mode,
        similarity_top_k=execution_plan.similarity_top_k,
        rerank_enabled=execution_plan.enable_reranker,
        rerank_top_n=execution_plan.rerank_top_n if execution_plan.enable_reranker else None,
        rerank_model=execution_plan.rerank_model if execution_plan.enable_reranker else None,
        split_strategy=execution_plan.split_strategy,
        filters=repr(filters),
        query_engine_cache_policy=execution_plan.query_engine_cache_policy,
    )

    multi_query_variants: list[str] | None = None
    if query_context is not None:
        multi_query_variants, mq_trace = prepare_multi_query_expansion(
            execution_plan=execution_plan,
            query_context=query_context,
            options=options,
        )
        query_context.trace["multi_query_expansion"] = mq_trace

    engine = build_query_engine_for_retrieval_mode(
        retrieval_mode=retrieval_mode,
        index=index,
        llm=llm,
        collection=collection,
        summary_index=summary_index,
        effective_params=effective_params,
        filters=filters,
        effective_prompt=effective_prompt,
        postprocessors=postprocessors,
        query_context=query_context,
    )

    if (
        query_context is not None
        and multi_query_variants
        and len(multi_query_variants) > 1
        and query_context.trace.get("multi_query_expansion", {}).get("expansion_enabled")
    ):
        engine = wrap_engine_for_multi_query(
            engine,
            variant_queries=multi_query_variants,
            trace_sink=query_context.trace["multi_query_expansion"],
            similarity_top_k=execution_plan.similarity_top_k,
        )

    if cache_allowed:
        set_cached_query_engine(cache_key, engine)

    return {
        "engine": engine,
        "cache_hit": False,
        "cache_key": cache_key,
        "engine_cache_lookup_ms": cache_result["cache_latency_ms"],
        "filters": repr(filters),
        "pipeline_params": effective_params,
    }
