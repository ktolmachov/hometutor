"""Thread-safe in-memory aggregate counters for metrics."""

from __future__ import annotations

import logging
from collections import Counter
from threading import Lock
from typing import Any

from app import metrics_core as core
from app.metrics_storage import _append_metrics_event
from app.metrics_graph_expansion import (
    compact_graph_expansion_for_metrics,
    _update_graph_expansion_aggregates,
    _graph_expansion_public_view,
    _new_graph_expansion_accumulator,
)

logger = logging.getLogger(__name__)
# print("DEBUG: RELOADING metrics_aggregator")

_lock = Lock()
_metrics: dict[str, Any] = {
    "requests_total": 0,
    "fallback_total": 0,
    "errors_total": 0,
    "sources_total": 0,
    "requests_without_sources_total": 0,
    "empty_answers_total": 0,
    "coverage_ratio_sum": 0.0,
    "coverage_samples": 0,
    "query_types": Counter(),
    "last_request": None,
    "latency_ms": {
        "pipeline_total": 0.0,
        "engine_acquire_total": 0.0,
        "query_execute_total": 0.0,
        "answer_total": 0.0,
    },
    "latency_samples_ms": {
        "pipeline": [],
        "engine_acquire": [],
        "query_execute": [],
        "answer_total": [],
    },
    "estimated_cost_total_usd": 0.0,
    "quality_checks_total": 0,
    "quality_check_failures": Counter(),
    "error_kinds": Counter(),
    "error_types": Counter(),
    "error_endpoints": Counter(),
    "last_error": None,
    "graph_expansion": _new_graph_expansion_accumulator(),
}


def record_request(
    *,
    request_id: str,
    question: str,
    query_type: str | None,
    total_answer_ms: float | None,
    pipeline_ms: float | None,
    engine_acquire_ms: float | None,
    query_execute_ms: float | None,
    source_count: int,
    fallback_applied: bool,
    coverage_ratio: float | None = None,
    estimated_cost_usd: float | None = None,
    estimated_cost_stages_usd: dict[str, Any] | None = None,
    answer_empty: bool = False,
    quality_checks: dict[str, Any] | None = None,
    pipeline_trace: dict[str, Any] | None = None,
    token_usage: dict[str, Any] | None = None,
    retrieval_trace: dict[str, Any] | None = None,
) -> None:
    normalized_type = (query_type or "unknown").strip() or "unknown"
    with _lock:
        _metrics["requests_total"] += 1
        _metrics["sources_total"] += max(source_count, 0)
        if source_count <= 0:
            _metrics["requests_without_sources_total"] += 1
        if answer_empty:
            _metrics["empty_answers_total"] += 1
        if fallback_applied:
            _metrics["fallback_total"] += 1

        _metrics["query_types"][normalized_type] += 1

        _metrics["latency_ms"]["pipeline_total"] += core._safe_float(pipeline_ms)
        _metrics["latency_ms"]["engine_acquire_total"] += core._safe_float(engine_acquire_ms)
        _metrics["latency_ms"]["query_execute_total"] += core._safe_float(query_execute_ms)
        _metrics["latency_ms"]["answer_total"] += core._safe_float(total_answer_ms)
        if pipeline_ms is not None:
            _metrics["latency_samples_ms"]["pipeline"].append(core._safe_float(pipeline_ms))
        if engine_acquire_ms is not None:
            _metrics["latency_samples_ms"]["engine_acquire"].append(core._safe_float(engine_acquire_ms))
        if query_execute_ms is not None:
            _metrics["latency_samples_ms"]["query_execute"].append(core._safe_float(query_execute_ms))
        if total_answer_ms is not None:
            _metrics["latency_samples_ms"]["answer_total"].append(core._safe_float(total_answer_ms))
        _metrics["estimated_cost_total_usd"] += core._safe_float(estimated_cost_usd)
        if quality_checks:
            _metrics["quality_checks_total"] += 1
            checks = quality_checks.get("checks") or {}
            for key in core._QUALITY_CHECK_KEYS:
                if checks.get(key) is False:
                    _metrics["quality_check_failures"][key] += 1

        if coverage_ratio is not None:
            _metrics["coverage_ratio_sum"] += max(0.0, coverage_ratio)
            _metrics["coverage_samples"] += 1

        ge_summary = None
        if pipeline_trace and isinstance(pipeline_trace, dict):
            ge_summary = compact_graph_expansion_for_metrics(pipeline_trace.get("graph_expansion"))
        if ge_summary is not None:
            _update_graph_expansion_aggregates(
                ge_summary,
                _metrics["graph_expansion"],
                query_type=normalized_type,
            )

        _metrics["last_request"] = {
            "request_id": request_id,
            "question_preview": question[:120],
            "query_type": normalized_type,
            "source_count": source_count,
            "fallback_applied": fallback_applied,
            "total_answer_ms": round(core._safe_float(total_answer_ms), 3),
            "estimated_cost_usd": round(core._safe_float(estimated_cost_usd), 8) if estimated_cost_usd is not None else None,
        }

    ge_for_event = None
    if pipeline_trace and isinstance(pipeline_trace, dict):
        ge_for_event = compact_graph_expansion_for_metrics(pipeline_trace.get("graph_expansion"))

    event_payload: dict[str, Any] = {
        "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
        "event_type": "request",
        "timestamp": core._current_timestamp(),
        "request_id": request_id,
        "query_type": normalized_type,
        "question_preview": question[:120],
        "source_count": source_count,
        "fallback_applied": fallback_applied,
        "answer_empty": answer_empty,
        "latency_ms": {
            "pipeline_ms": round(core._safe_float(pipeline_ms), 3) if pipeline_ms is not None else None,
            "engine_acquire_ms": round(core._safe_float(engine_acquire_ms), 3) if engine_acquire_ms is not None else None,
            "query_execute_ms": round(core._safe_float(query_execute_ms), 3) if query_execute_ms is not None else None,
            "total_answer_ms": round(core._safe_float(total_answer_ms), 3) if total_answer_ms is not None else None,
        },
        "coverage_ratio": round(max(0.0, coverage_ratio), 3) if coverage_ratio is not None else None,
        "estimated_cost_usd": round(core._safe_float(estimated_cost_usd), 8) if estimated_cost_usd is not None else None,
        "estimated_cost_stages_usd": estimated_cost_stages_usd,
        "token_usage": token_usage,
        "quality_checks": quality_checks,
        "pipeline_trace": pipeline_trace,
        "retrieval_trace": retrieval_trace,
    }
    if ge_for_event is not None:
        event_payload["graph_expansion"] = ge_for_event
    _append_metrics_event(event_payload)


def record_error(
    *,
    request_id: str | None = None,
    endpoint: str | None = None,
    error_kind: str | None = None,
    error_type: str | None = None,
    status_code: int | None = None,
    message: str | None = None,
) -> None:
    normalized_kind = (error_kind or "runtime").strip() or "runtime"
    normalized_type = (error_type or "unknown").strip() or "unknown"
    normalized_endpoint = (endpoint or "unknown").strip() or "unknown"

    with _lock:
        _metrics["errors_total"] += 1
        _metrics["error_kinds"][normalized_kind] += 1
        _metrics["error_types"][normalized_type] += 1
        _metrics["error_endpoints"][normalized_endpoint] += 1
        _metrics["last_error"] = {
            "request_id": request_id,
            "endpoint": normalized_endpoint,
            "error_kind": normalized_kind,
            "error_type": normalized_type,
            "status_code": status_code,
            "message": (message or "")[:240] if message else None,
        }

    _append_metrics_event(
        {
            "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
            "event_type": "error",
            "timestamp": core._current_timestamp(),
            "request_id": request_id,
            "endpoint": normalized_endpoint,
            "error_kind": normalized_kind,
            "error_type": normalized_type,
            "status_code": status_code,
            "message": (message or "")[:240] if message else None,
        }
    )


def get_metrics() -> dict[str, Any]:
    with _lock:
        requests_total = _metrics["requests_total"]
        coverage_samples = _metrics["coverage_samples"]
        avg_coverage = (
            round(_metrics["coverage_ratio_sum"] / coverage_samples, 3)
            if coverage_samples
            else None
        )

        def _avg(total: float) -> float | None:
            if requests_total == 0:
                return None
            return round(total / requests_total, 3)

        def _rate(total: int) -> float | None:
            if requests_total == 0:
                return None
            return round(total / requests_total, 3)

        return {
            "requests_total": requests_total,
            "fallback_total": _metrics["fallback_total"],
            "errors_total": _metrics["errors_total"],
            "fallback_rate": _rate(_metrics["fallback_total"]),
            "requests_without_sources_total": _metrics["requests_without_sources_total"],
            "requests_without_sources_rate": _rate(_metrics["requests_without_sources_total"]),
            "empty_answers_total": _metrics["empty_answers_total"],
            "empty_answers_rate": _rate(_metrics["empty_answers_total"]),
            "avg_sources_per_request": _avg(_metrics["sources_total"]),
            "avg_coverage_ratio": avg_coverage,
            "query_types": dict(_metrics["query_types"]),
            "latency_ms": {
                "avg_pipeline_ms": _avg(_metrics["latency_ms"]["pipeline_total"]),
                "avg_engine_acquire_ms": _avg(_metrics["latency_ms"]["engine_acquire_total"]),
                "avg_query_execute_ms": _avg(_metrics["latency_ms"]["query_execute_total"]),
                "avg_total_answer_ms": _avg(_metrics["latency_ms"]["answer_total"]),
                "p50_pipeline_ms": core._percentile(_metrics["latency_samples_ms"]["pipeline"], 0.50),
                "p95_pipeline_ms": core._percentile(_metrics["latency_samples_ms"]["pipeline"], 0.95),
                "p99_pipeline_ms": core._percentile(_metrics["latency_samples_ms"]["pipeline"], 0.99),
                "p50_total_answer_ms": core._percentile(_metrics["latency_samples_ms"]["answer_total"], 0.50),
                "p95_total_answer_ms": core._percentile(_metrics["latency_samples_ms"]["answer_total"], 0.95),
                "p99_total_answer_ms": core._percentile(_metrics["latency_samples_ms"]["answer_total"], 0.99),
            },
            "estimated_cost_usd": {
                "avg_per_request": _avg(_metrics["estimated_cost_total_usd"]),
                "total": round(_metrics["estimated_cost_total_usd"], 8),
            },
            "quality_checks": {
                "requests_evaluated": _metrics["quality_checks_total"],
                "failure_counts": dict(_metrics["quality_check_failures"]),
                "failure_rates": {
                    key: round(_metrics["quality_check_failures"][key] / _metrics["quality_checks_total"], 3)
                    for key in core._QUALITY_CHECK_KEYS
                    if _metrics["quality_checks_total"] > 0 and _metrics["quality_check_failures"][key] > 0
                },
            },
            "error_breakdown": {
                "by_kind": dict(_metrics["error_kinds"]),
                "by_type": dict(_metrics["error_types"]),
                "by_endpoint": dict(_metrics["error_endpoints"]),
            },
            "last_request": _metrics["last_request"],
            "last_error": _metrics["last_error"],
            "graph_expansion": _graph_expansion_public_view(_metrics["graph_expansion"]),
        }
