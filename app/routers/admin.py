from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException

import app.api_services as services
from app.api_helpers import record_api_error
from app.guardrails import InputGuardrailError
from app.models import PipelineOverrides, QueryOptions
from app.user_state import (
    get_learner_state_diagnostics,
    list_archived_learner_state,
    purge_archived_learner_state,
    restore_archived_learner_state,
)

router = APIRouter(tags=["admin"])


def _prepare_admin_question(
    *,
    question: str,
    folder: Optional[str] = None,
    folder_rel: Optional[str] = None,
    file_name: Optional[str] = None,
    relative_path: Optional[str] = None,
) -> tuple[str, QueryOptions]:
    try:
        validated = services.prepare_ask_request(
            SimpleNamespace(
                question=question,
                folder=folder,
                folder_rel=folder_rel,
                file_name=file_name,
                relative_path=relative_path,
                topic=None,
                homework_mode=False,
                assistance_level=None,
                homework_level=None,
                study_mode=False,
                followup_context=None,
                session_id=None,
                query_mode=None,
                quiz_learning_mode=None,
                tutor_goal_subtopic=None,
                tutor_goal_target_level=None,
                tutor_goal_desired_outcome=None,
                tutor_goal_time_budget_min=None,
            )
        )
    except InputGuardrailError as e:
        raise HTTPException(
            status_code=400,
            detail=services.build_error_detail(e.code, str(e)),
        ) from e
    return validated.question, validated.options


def _reindex_in_background(reset: bool):
    try:
        services.build_index(reset=reset)
    finally:
        services.reindex_end()


@router.get("/cache/stats", response_model=dict[str, Any])
def cache_stats():
    return services.get_cache_stats()


@router.get("/cache/benchmark")
def cache_benchmark(
    folder: Optional[str] = None,
    folder_rel: Optional[str] = None,
    file_name: Optional[str] = None,
    relative_path: Optional[str] = None,
):
    options = QueryOptions(
        folder=folder,
        folder_rel=folder_rel,
        file_name=file_name,
        relative_path=relative_path,
    )

    t1 = time.perf_counter()
    services.build_query_engine("cache benchmark", options)
    first_ms = round((time.perf_counter() - t1) * 1000, 3)

    t2 = time.perf_counter()
    services.build_query_engine("cache benchmark", options)
    second_ms = round((time.perf_counter() - t2) * 1000, 3)

    stats = services.get_cache_stats()

    return {
        "benchmark_for": {
            "folder": folder,
            "folder_rel": folder_rel,
            "file_name": file_name,
            "relative_path": relative_path,
        },
        "first_call_ms": first_ms,
        "second_call_ms": second_ms,
        "stats": stats,
    }


@router.post("/reindex")
def reindex(background_tasks: BackgroundTasks, reset: bool = False):
    if not services.try_reindex_begin():
        raise HTTPException(status_code=409, detail="Reindex is already in progress")
    background_tasks.add_task(_reindex_in_background, reset)
    return {"status": "started", "reset": reset}


@router.get("/reindex/status")
def reindex_status():
    return services.get_ingestion_status()


@router.get("/faq/similar")
def faq_similar(
    question: str,
    top_k: int = 3,
    min_score: float = 0.7,
):
    validated_question, _ = _prepare_admin_question(question=question)
    try:
        return services.faq_memory.find_similar_questions(
            question=validated_question,
            top_k=top_k,
            min_score=min_score,
        )
    except Exception as e:  # noqa: BLE001 - admin API boundary records backend failures and returns controlled HTTP 500.
        record_api_error(endpoint="/faq/similar", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"FAQ similar query failed: {type(e).__name__}: {e}",
        )


@router.get("/index/stats", response_model=dict[str, Any])
def index_stats():
    try:
        return services.get_index_stats()
    except Exception as e:  # noqa: BLE001 - admin API boundary records backend failures and returns controlled HTTP 500.
        record_api_error(endpoint="/index/stats", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Index stats failed: {type(e).__name__}: {e}",
        )


@router.get("/index/version", response_model=dict[str, Any])
def index_version():
    try:
        return services.get_index_version()
    except Exception as e:  # noqa: BLE001 - admin API boundary records backend failures and returns controlled HTTP 500.
        record_api_error(endpoint="/index/version", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Index version failed: {type(e).__name__}: {e}",
        )


@router.get("/index/diff")
def index_diff():
    try:
        return services.get_index_diff()
    except Exception as e:  # noqa: BLE001 - admin API boundary records backend failures and returns controlled HTTP 500.
        record_api_error(endpoint="/index/diff", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Index diff failed: {type(e).__name__}: {e}",
        )


@router.get("/learner-state/diagnostics")
def learner_state_diagnostics():
    try:
        return get_learner_state_diagnostics()
    except Exception as e:  # noqa: BLE001 - admin API boundary records backend failures and returns controlled HTTP 500.
        record_api_error(endpoint="/learner-state/diagnostics", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Learner state diagnostics failed: {type(e).__name__}: {e}",
        )


@router.get("/learner-state/archive")
def learner_state_archive(
    source_generation_id: Optional[str] = None,
    target_generation_id: Optional[str] = None,
    archived_reason: Optional[str] = None,
    state_table: Optional[str] = None,
    limit: int = 100,
):
    try:
        return list_archived_learner_state(
            source_generation_id=source_generation_id,
            target_generation_id=target_generation_id,
            archived_reason=archived_reason,
            state_table=state_table,
            limit=limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 - admin API boundary records backend failures and returns controlled HTTP 500.
        record_api_error(endpoint="/learner-state/archive", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Learner state archive listing failed: {type(e).__name__}: {e}",
        )


@router.post("/learner-state/archive/restore")
def learner_state_archive_restore(
    source_generation_id: str,
    state_table: Optional[str] = None,
    limit: int = 100,
    overwrite: bool = False,
):
    try:
        return restore_archived_learner_state(
            source_generation_id=source_generation_id,
            state_table=state_table,
            limit=limit,
            overwrite=overwrite,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 - admin API boundary records backend failures and returns controlled HTTP 500.
        record_api_error(endpoint="/learner-state/archive/restore", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Learner state archive restore failed: {type(e).__name__}: {e}",
        )


@router.post("/learner-state/archive/purge")
def learner_state_archive_purge(
    source_generation_id: Optional[str] = None,
    target_generation_id: Optional[str] = None,
    archived_reason: Optional[str] = None,
    state_table: Optional[str] = None,
    allow_all: bool = False,
):
    try:
        return purge_archived_learner_state(
            source_generation_id=source_generation_id,
            target_generation_id=target_generation_id,
            archived_reason=archived_reason,
            state_table=state_table,
            allow_all=allow_all,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 - admin API boundary records backend failures and returns controlled HTTP 500.
        record_api_error(endpoint="/learner-state/archive/purge", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Learner state archive purge failed: {type(e).__name__}: {e}",
        )


@router.get("/cache/answer-flow-stats")
def answer_flow_stats():
    return services.get_answer_flow_stats()


@router.post("/cache/answer-flow-reset")
def answer_flow_reset():
    services.reset_answer_flow_stats()
    return {"status": "reset"}


@router.get("/cache/answer-benchmark")
def answer_benchmark(
    question: str,
    folder: Optional[str] = None,
    folder_rel: Optional[str] = None,
    file_name: Optional[str] = None,
    relative_path: Optional[str] = None,
):
    validated_question, options = _prepare_admin_question(
        question=question,
        folder=folder,
        folder_rel=folder_rel,
        file_name=file_name,
        relative_path=relative_path,
    )

    first = services.answer_question(validated_question, options)
    second = services.answer_question(validated_question, options)

    return {
        "benchmark_for": {
            "question": validated_question,
            "folder": folder,
            "folder_rel": folder_rel,
            "file_name": file_name,
            "relative_path": relative_path,
        },
        "first_call": first.get("debug"),
        "second_call": second.get("debug"),
        "aggregated_stats": services.get_answer_flow_stats(),
    }


@router.get("/profile/query")
def profile_query(
    question: str,
    folder: Optional[str] = None,
    folder_rel: Optional[str] = None,
    file_name: Optional[str] = None,
    relative_path: Optional[str] = None,
):
    validated_question, options = _prepare_admin_question(
        question=question,
        folder=folder,
        folder_rel=folder_rel,
        file_name=file_name,
        relative_path=relative_path,
    )

    return services.run_profiled_query(validated_question, options)


@router.get("/profile/compare")
def profile_compare(
    question: str,
    folder: Optional[str] = None,
    folder_rel: Optional[str] = None,
    file_name: Optional[str] = None,
    relative_path: Optional[str] = None,
    a_similarity_top_k: Optional[int] = None,
    a_enable_reranker: Optional[bool] = None,
    a_rerank_top_n: Optional[int] = None,
    a_rerank_model: Optional[str] = None,
    a_split_strategy: Optional[str] = None,
    a_window_size: Optional[int] = None,
    b_similarity_top_k: Optional[int] = None,
    b_enable_reranker: Optional[bool] = None,
    b_rerank_top_n: Optional[int] = None,
    b_rerank_model: Optional[str] = None,
    b_split_strategy: Optional[str] = None,
    b_window_size: Optional[int] = None,
):
    validated_question, options = _prepare_admin_question(
        question=question,
        folder=folder,
        folder_rel=folder_rel,
        file_name=file_name,
        relative_path=relative_path,
    )

    config_a = PipelineOverrides(
        similarity_top_k=a_similarity_top_k,
        enable_reranker=a_enable_reranker,
        rerank_top_n=a_rerank_top_n,
        rerank_model=a_rerank_model,
        split_strategy=a_split_strategy,
        window_size=a_window_size,
    )

    config_b = PipelineOverrides(
        similarity_top_k=b_similarity_top_k,
        enable_reranker=b_enable_reranker,
        rerank_top_n=b_rerank_top_n,
        rerank_model=b_rerank_model,
        split_strategy=b_split_strategy,
        window_size=b_window_size,
    )

    result_a = services.run_profiled_query(validated_question, options, config_a)
    result_b = services.run_profiled_query(validated_question, options, config_b)

    profile_a = result_a["profile"]
    profile_b = result_b["profile"]

    return {
        "question": validated_question,
        "filters": {
            "folder": folder,
            "folder_rel": folder_rel,
            "file_name": file_name,
            "relative_path": relative_path,
        },
        "config_a": {
            "profile": profile_a,
            "answer": result_a["answer"],
            "sources": result_a["sources"],
        },
        "config_b": {
            "profile": profile_b,
            "answer": result_b["answer"],
            "sources": result_b["sources"],
        },
        "diff": {
            "retrieval_ms_diff": round(profile_a["retrieval_ms"] - profile_b["retrieval_ms"], 3),
            "rerank_ms_diff": round(profile_a["rerank_ms"] - profile_b["rerank_ms"], 3),
            "synthesis_ms_diff": round(profile_a["synthesis_ms"] - profile_b["synthesis_ms"], 3),
            "total_ms_diff": round(profile_a["total_ms"] - profile_b["total_ms"], 3),
            "retrieved_nodes_count_diff": profile_a["retrieved_nodes_count"] - profile_b["retrieved_nodes_count"],
            "postprocessed_nodes_count_diff": profile_a["postprocessed_nodes_count"] - profile_b["postprocessed_nodes_count"],
        },
    }


@router.get("/profile/compare-eval")
def profile_compare_eval(
    question: str,
    folder: Optional[str] = None,
    folder_rel: Optional[str] = None,
    file_name: Optional[str] = None,
    relative_path: Optional[str] = None,
    a_similarity_top_k: Optional[int] = None,
    a_enable_reranker: Optional[bool] = None,
    a_rerank_top_n: Optional[int] = None,
    a_rerank_model: Optional[str] = None,
    a_split_strategy: Optional[str] = None,
    a_window_size: Optional[int] = None,
    b_similarity_top_k: Optional[int] = None,
    b_enable_reranker: Optional[bool] = None,
    b_rerank_top_n: Optional[int] = None,
    b_rerank_model: Optional[str] = None,
    b_split_strategy: Optional[str] = None,
    b_window_size: Optional[int] = None,
):
    validated_question, options = _prepare_admin_question(
        question=question,
        folder=folder,
        folder_rel=folder_rel,
        file_name=file_name,
        relative_path=relative_path,
    )

    config_a = PipelineOverrides(
        similarity_top_k=a_similarity_top_k,
        enable_reranker=a_enable_reranker,
        rerank_top_n=a_rerank_top_n,
        rerank_model=a_rerank_model,
        split_strategy=a_split_strategy,
        window_size=a_window_size,
    )

    config_b = PipelineOverrides(
        similarity_top_k=b_similarity_top_k,
        enable_reranker=b_enable_reranker,
        rerank_top_n=b_rerank_top_n,
        rerank_model=b_rerank_model,
        split_strategy=b_split_strategy,
        window_size=b_window_size,
    )

    return services.compare_two_configs_with_eval(
        question=validated_question,
        options=options,
        config_a=config_a,
        config_b=config_b,
    )
