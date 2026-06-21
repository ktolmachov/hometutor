"""
Answer flow metrics, quality checks, and retrieval tracing.
Extracted from query_service.py to reduce god-module size (arch-cleanup-e30).
"""
from threading import Lock
from typing import Any

from app.config import get_settings
from app.metrics import (
    PIPELINE_TRACE_SCHEMA_VERSION,
    RETRIEVAL_TRACE_SCHEMA_VERSION,
    check_pipeline_trace_schema,
    check_retrieval_trace_schema,
)
from app.models import QueryContext
from app.usage_cost import estimate_retrieval_embedding_usage

_CONFIDENCE_THRESHOLDS = {
    "high": {"min_sources": 3, "min_avg_score": 0.65},
    "medium": {"min_sources": 1, "min_avg_score": 0.40},
}

_benchmark_lock = Lock()
_answer_flow_stats = {
    "cached_count": 0,
    "uncached_count": 0,
    "cached_total_ms": 0.0,
    "uncached_total_ms": 0.0,
    "cached_engine_acquire_total_ms": 0.0,
    "uncached_engine_acquire_total_ms": 0.0,
    "cached_query_execute_total_ms": 0.0,
    "uncached_query_execute_total_ms": 0.0,
    "last_cached_total_ms": None,
    "last_uncached_total_ms": None,
}


def _retrieval_query_texts(effective_question: str, ctx: QueryContext | None) -> list[str]:
    texts = [effective_question]
    if ctx is None:
        return texts
    for sq in getattr(ctx, "subquestions", None) or []:
        s = (sq or "").strip()
        if s and s not in texts:
            texts.append(s)
    return texts


def _retrieval_stage_usage_cost(
    *,
    retrieval_mode: str | None,
    effective_question: str,
    ctx: QueryContext | None,
) -> tuple[dict[str, int] | None, float | None]:
    mode = (retrieval_mode or "").strip().lower()
    if mode == "bm25_only":
        return None, None
    settings = get_settings()
    texts = _retrieval_query_texts(effective_question or "", ctx)
    return estimate_retrieval_embedding_usage(texts, embed_model=settings.embed_model)


def _build_retrieval_trace(
    pipeline_params: dict[str, Any],
    sources: list[dict[str, Any]],
    *,
    cache_hit: bool,
    effective_query: str | None = None,
    effective_query_source: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": RETRIEVAL_TRACE_SCHEMA_VERSION,
        "retrieval_mode": pipeline_params.get("retrieval_mode"),
        "query_type": pipeline_params.get("query_type"),
        "effective_query": effective_query,
        "effective_query_source": effective_query_source,
        "filters": pipeline_params.get("filters"),
        "feature_flags": {
            "rerank_enabled": pipeline_params.get("enable_reranker"),
        },
        "top_k": {
            "similarity_top_k": pipeline_params.get("similarity_top_k"),
            "rerank_top_n": pipeline_params.get("rerank_top_n") if pipeline_params.get("enable_reranker") else None,
        },
        "cache_hit": cache_hit,
        "returned_source_count": len(sources),
        "sources": [
            {
                "relative_path": source.get("relative_path"),
                "page": source.get("page"),
                "score": source.get("score"),
                "route": source.get("route") or pipeline_params.get("retrieval_mode"),
                "rank_reason": source.get("rank_reason"),
            }
            for source in sources
            if isinstance(source, dict)
        ],
    }


def _build_trace_schema_debug(
    pipeline_trace: dict[str, Any] | None,
    retrieval_trace: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "trace_schema": {
            "pipeline_trace_schema_version": PIPELINE_TRACE_SCHEMA_VERSION,
            "retrieval_trace_schema_version": RETRIEVAL_TRACE_SCHEMA_VERSION,
            "pipeline_trace_check": check_pipeline_trace_schema(pipeline_trace),
            "retrieval_trace_check": check_retrieval_trace_schema(retrieval_trace),
        }
    }


def _compute_deterministic_quality_checks(
    answer: str,
    sources: list[dict[str, Any]],
    *,
    fallback_applied: bool,
) -> dict[str, Any]:
    answer_text = str(answer or "")
    normalized_answer = answer_text.strip()
    scores = [float(s.get("score")) for s in sources if s.get("score") is not None]

    checks = {
        "answer_not_empty": bool(normalized_answer),
        "has_sources": bool(sources),
        "answer_length_in_range": 50 <= len(normalized_answer) <= 10000,
        "no_fallback_with_sources": not (fallback_applied and bool(sources)),
        "min_source_score_ok": (min(scores) >= 0.3) if scores else False,
    }
    failed_checks = [key for key, passed in checks.items() if not passed]

    return {
        "checks": checks,
        "failed_checks": failed_checks,
        "passed": not failed_checks,
        "answer_length": len(normalized_answer),
        "source_count": len(sources),
        "min_source_score": round(min(scores), 3) if scores else None,
    }


def _compute_answer_confidence(
    sources: list[dict],
    query_type: str,
    classify_confidence: float,
) -> dict[str, Any]:
    """Human-readable answer confidence based on source scores and count."""
    scores = [s.get("score") for s in sources if s.get("score") is not None]
    source_count = len(sources)
    avg_score = sum(scores) / len(scores) if scores else 0.0
    unique_source_files = {
        (s.get("relative_path") or s.get("file_name") or "")
        for s in sources
    } - {""}
    reasons: list[str] = []

    high = _CONFIDENCE_THRESHOLDS["high"]
    medium = _CONFIDENCE_THRESHOLDS["medium"]

    if source_count >= high["min_sources"] and avg_score >= high["min_avg_score"]:
        level = "high"
        label = "Высокая уверенность"
    elif source_count >= medium["min_sources"] and avg_score >= medium["min_avg_score"]:
        level = "medium"
        label = "Средняя уверенность"
    else:
        level = "low"
        label = "Низкая уверенность"

    if classify_confidence < 0.6:
        reasons.append("low_classify_confidence")
        if level == "high":
            level = "medium"
            label = "Средняя уверенность"
        elif level == "medium":
            level = "low"
            label = "Низкая уверенность"

    if source_count == 0:
        reasons.append("no_sources")
    elif source_count < medium["min_sources"]:
        reasons.append("too_few_sources")

    if scores and avg_score < medium["min_avg_score"]:
        reasons.append("low_source_scores")

    if query_type in ("overview", "synthesis"):
        if len(unique_source_files) < 2:
            reasons.append("low_document_coverage")
            if level == "high":
                level = "medium"
                label = "Средняя уверенность"
            elif level == "medium":
                level = "low"
                label = "Низкая уверенность"

    return {
        "level": level,
        "label": label,
        "source_count": source_count,
        "avg_source_score": round(avg_score, 3) if scores else None,
        "unique_source_files": len(unique_source_files),
        "reasons": reasons,
    }


def _avg(total: float, count: int):
    if count == 0:
        return None
    return round(total / count, 3)


def _record_answer_flow(cache_hit: bool, engine_acquire_ms: float, query_execute_ms: float, total_ms: float):
    with _benchmark_lock:
        if cache_hit:
            _answer_flow_stats["cached_count"] += 1
            _answer_flow_stats["cached_total_ms"] += total_ms
            _answer_flow_stats["cached_engine_acquire_total_ms"] += engine_acquire_ms
            _answer_flow_stats["cached_query_execute_total_ms"] += query_execute_ms
            _answer_flow_stats["last_cached_total_ms"] = round(total_ms, 3)
        else:
            _answer_flow_stats["uncached_count"] += 1
            _answer_flow_stats["uncached_total_ms"] += total_ms
            _answer_flow_stats["uncached_engine_acquire_total_ms"] += engine_acquire_ms
            _answer_flow_stats["uncached_query_execute_total_ms"] += query_execute_ms
            _answer_flow_stats["last_uncached_total_ms"] = round(total_ms, 3)


def get_answer_flow_stats():
    with _benchmark_lock:
        return {
            "cached": {
                "count": _answer_flow_stats["cached_count"],
                "avg_total_ms": _avg(_answer_flow_stats["cached_total_ms"], _answer_flow_stats["cached_count"]),
                "avg_engine_acquire_ms": _avg(
                    _answer_flow_stats["cached_engine_acquire_total_ms"],
                    _answer_flow_stats["cached_count"],
                ),
                "avg_query_execute_ms": _avg(
                    _answer_flow_stats["cached_query_execute_total_ms"],
                    _answer_flow_stats["cached_count"],
                ),
                "last_total_ms": _answer_flow_stats["last_cached_total_ms"],
            },
            "uncached": {
                "count": _answer_flow_stats["uncached_count"],
                "avg_total_ms": _avg(_answer_flow_stats["uncached_total_ms"], _answer_flow_stats["uncached_count"]),
                "avg_engine_acquire_ms": _avg(
                    _answer_flow_stats["uncached_engine_acquire_total_ms"],
                    _answer_flow_stats["uncached_count"],
                ),
                "avg_query_execute_ms": _avg(
                    _answer_flow_stats["uncached_query_execute_total_ms"],
                    _answer_flow_stats["uncached_count"],
                ),
                "last_total_ms": _answer_flow_stats["last_uncached_total_ms"],
            },
        }


def reset_answer_flow_stats():
    with _benchmark_lock:
        for key in list(_answer_flow_stats.keys()):
            if key.endswith("_count"):
                _answer_flow_stats[key] = 0
            elif key.endswith("_ms"):
                _answer_flow_stats[key] = 0.0
        _answer_flow_stats["last_cached_total_ms"] = None
        _answer_flow_stats["last_uncached_total_ms"] = None
