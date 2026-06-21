"""Functions for summarization and analysis of stored metrics."""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict, deque
from typing import Any

_log = logging.getLogger(__name__)

from app import metrics_core as core
from app.metrics_storage import get_metrics_store
from app.metrics_graph_expansion import aggregate_graph_expansion_from_request_events


def summarize_metrics_store(*, limit: int = 200) -> dict[str, Any] | None:
    store = get_metrics_store(limit=limit)
    request_items = [item for item in store["items"] if item.get("event_type") == "request"]
    if not request_items:
        return None

    total_requests = len(request_items)
    fallback_total = sum(1 for item in request_items if item.get("fallback_applied") is True)
    without_sources_total = sum(1 for item in request_items if (item.get("source_count") or 0) <= 0)
    empty_answers_total = sum(1 for item in request_items if item.get("answer_empty") is True)

    total_answer_latencies = [
        float(latency["total_answer_ms"])
        for item in request_items
        if (latency := (item.get("latency_ms") or {})).get("total_answer_ms") is not None
    ]
    pipeline_latencies = [
        float(latency["pipeline_ms"])
        for item in request_items
        if (latency := (item.get("latency_ms") or {})).get("pipeline_ms") is not None
    ]
    estimated_costs = [
        float(item["estimated_cost_usd"])
        for item in request_items
        if item.get("estimated_cost_usd") is not None
    ]
    coverage_ratios = [
        float(item["coverage_ratio"])
        for item in request_items
        if item.get("coverage_ratio") is not None
    ]

    quality_requests = 0
    quality_failures: Counter[str] = Counter()
    for item in request_items:
        quality_checks = item.get("quality_checks") or {}
        checks = quality_checks.get("checks") or {}
        if checks:
            quality_requests += 1
            for key in core._QUALITY_CHECK_KEYS:
                if checks.get(key) is False:
                    quality_failures[key] += 1

    def _avg(values: list[float]) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), 3)

    return {
        "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
        "window_size": total_requests,
        "fallback_rate": round(fallback_total / total_requests, 3),
        "requests_without_sources_rate": round(without_sources_total / total_requests, 3),
        "empty_answers_rate": round(empty_answers_total / total_requests, 3),
        "latency_ms": {
            "avg_total_answer_ms": _avg(total_answer_latencies),
            "p95_total_answer_ms": core._percentile(total_answer_latencies, 0.95),
            "avg_pipeline_ms": _avg(pipeline_latencies),
            "p95_pipeline_ms": core._percentile(pipeline_latencies, 0.95),
        },
        "estimated_cost_usd": {
            "avg_per_request": _avg(estimated_costs),
            "total": round(sum(estimated_costs), 8),
        },
        "coverage": {
            "avg_coverage_ratio": _avg(coverage_ratios),
            "samples_with_coverage": len(coverage_ratios),
        },
        "quality_checks": {
            "requests_evaluated": quality_requests,
            "failure_counts": dict(quality_failures),
            "failure_rates": {
                key: round(quality_failures[key] / quality_requests, 3)
                for key in core._QUALITY_CHECK_KEYS
                if quality_requests > 0 and quality_failures[key] > 0
            },
        },
        "graph_expansion": aggregate_graph_expansion_from_request_events(request_items),
        "route_demotion": aggregate_route_demotion_from_store(),
    }


def get_cost_dashboard(*, limit: int = 200, top_n: int = 5) -> dict[str, Any]:
    store = get_metrics_store(limit=limit)
    request_items = [
        item
        for item in store["items"]
        if item.get("event_type") == "request" and item.get("estimated_cost_usd") is not None
    ]
    ingestion_items = [
        item
        for item in store["items"]
        if item.get("event_type") == "ingestion_run" and isinstance(item.get("estimated_cost_usd"), dict)
    ]

    if top_n < 1:
        top_n = 1

    costs = [float(item["estimated_cost_usd"]) for item in request_items]

    def _avg(values: list[float]) -> float | None:
        if not values:
            return None
        return round(sum(values) / len(values), 8)

    by_query_type: dict[str, dict[str, Any]] = {}
    for item in request_items:
        query_type = (item.get("query_type") or "unknown").strip() or "unknown"
        entry = by_query_type.setdefault(
            query_type,
            {
                "count": 0,
                "total_usd": 0.0,
                "avg_usd": None,
            },
        )
        entry["count"] += 1
        entry["total_usd"] += float(item["estimated_cost_usd"])

    for entry in by_query_type.values():
        entry["total_usd"] = round(entry["total_usd"], 8)
        entry["avg_usd"] = round(entry["total_usd"] / entry["count"], 8) if entry["count"] else None

    top_expensive = sorted(
        request_items,
        key=lambda item: float(item.get("estimated_cost_usd") or 0.0),
        reverse=True,
    )[:top_n]

    avg_per_request = _avg(costs)
    ingestion_costs = [
        float((item.get("estimated_cost_usd") or {}).get("total") or 0.0)
        for item in ingestion_items
    ]
    reindex_items = [item for item in ingestion_items if item.get("run_type") == "full_reindex"]

    return {
        "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
        "window_size": {
            "requests": len(request_items),
            "ingestion_runs": len(ingestion_items),
            "reindex_runs": len(reindex_items),
        },
        "query_estimated_cost_usd": {
            "total": round(sum(costs), 8),
            "avg_per_request": avg_per_request,
            "p95_per_request": core._percentile(costs, 0.95),
            "max_per_request": round(max(costs), 8) if costs else None,
        },
        "by_query_type": by_query_type,
        "top_expensive_requests": [
            {
                "request_id": item.get("request_id"),
                "query_type": item.get("query_type"),
                "question_preview": item.get("question_preview"),
                "estimated_cost_usd": round(float(item.get("estimated_cost_usd") or 0.0), 8),
                "timestamp": item.get("timestamp"),
            }
            for item in top_expensive
        ],
        "ingestion_estimated_cost_usd": {
            "total": round(sum(ingestion_costs), 8),
            "avg_per_run": _avg(ingestion_costs),
            "full_reindex_total": round(
                sum(float((item.get("estimated_cost_usd") or {}).get("total") or 0.0) for item in reindex_items),
                8,
            ),
            "last_run": ingestion_items[0] if ingestion_items else None,
        },
        "projections": {
            "per_100_requests_usd": round((avg_per_request or 0.0) * 100, 6) if avg_per_request is not None else None,
            "per_1000_requests_usd": round((avg_per_request or 0.0) * 1000, 6) if avg_per_request is not None else None,
            "daily_100_requests_usd": round((avg_per_request or 0.0) * 100, 6) if avg_per_request is not None else None,
        },
        "estimated_cost_by_stage_usd": _rollup_stage_costs_usd(request_items),
    }


def _rollup_stage_costs_usd(request_items: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[float]] = {key: [] for key in core._STAGE_COST_KEYS}
    for item in request_items:
        stages = item.get("estimated_cost_stages_usd")
        if not isinstance(stages, dict):
            continue
        for key in core._STAGE_COST_KEYS:
            raw = stages.get(key)
            if raw is None:
                continue
            try:
                buckets[key].append(float(raw))
            except (TypeError, ValueError):
                continue
    out: dict[str, Any] = {}
    for key, vals in buckets.items():
        if not vals:
            continue
        total = sum(vals)
        out[key] = {
            "total_usd": round(total, 8),
            "avg_per_request": round(total / len(vals), 8),
            "samples": len(vals),
        }
    return out


def get_knowledge_workflow_metrics(*, limit_events: int = 20000) -> dict[str, Any]:
    if limit_events < 1:
        limit_events = 1
    items: list[dict[str, Any]] = []
    if not core.METRICS_STORE_PATH.exists():
        return {
            "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
            "window_size": 0,
            "counts_by_action": {},
            "conversion": {},
            "topics_synthesis": {},
            "working_set_documents": {},
        }

    with open(core.METRICS_STORE_PATH, "r", encoding="utf-8") as file:
        for line in file:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if item.get("event_type") != "knowledge_workflow":
                continue
            items.append(item)

    items.sort(key=lambda x: x.get("timestamp", ""))
    window = items[-limit_events:] if len(items) > limit_events else items

    counts: Counter[str] = Counter()
    doc_sizes: list[float] = []
    for it in window:
        act = (it.get("action") or "unknown").strip() or "unknown"
        counts[act] += 1
        trace = it.get("knowledge_product_trace") if isinstance(it.get("knowledge_product_trace"), dict) else {}
        if act in (
            "answer_synthesis_from_answer_complete",
            "topics_synthesis_complete",
        ):
            n = trace.get("documents_used_count")
            if n is None and isinstance(trace.get("working_set_paths"), list):
                n = len(trace["working_set_paths"])
            if n is not None:
                try:
                    doc_sizes.append(float(n))
                except (TypeError, ValueError):
                    pass

    def _rate(num: int, den: int) -> float | None:
        if den <= 0:
            return None
        return round(num / den, 4)

    denom_sources = counts.get("qa_answer_with_sources", 0)
    conversion = {
        "answer_to_topic_open_rate": _rate(counts.get("answer_to_topic_open", 0), denom_sources),
        "answer_to_synthesis_from_answer_rate": _rate(
            counts.get("answer_synthesis_from_answer_complete", 0),
            denom_sources,
        ),
        "denominator_qa_with_sources": denom_sources,
    }

    ts_start = counts.get("topics_synthesis_start", 0)
    ts_done = counts.get("topics_synthesis_complete", 0)
    ts_fail = counts.get("topics_synthesis_failed", 0)
    orphan = max(0, ts_start - ts_done - ts_fail)
    topics_synthesis = {
        "starts": ts_start,
        "completes": ts_done,
        "failures": ts_fail,
        "completion_rate": _rate(ts_done, ts_start),
        "failure_rate": _rate(ts_fail, ts_start),
        "abandonment_or_inflight_rate": _rate(orphan, ts_start),
    }

    avg_docs = round(sum(doc_sizes) / len(doc_sizes), 3) if doc_sizes else None

    return {
        "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
        "window_size": len(window),
        "counts_by_action": dict(counts),
        "conversion": conversion,
        "topics_synthesis": topics_synthesis,
        "working_set_documents": {
            "avg_documents_on_completed_synthesis": avg_docs,
            "samples_with_size": len(doc_sizes),
        },
    }


def get_quality_metrics(*, limit: int = 200) -> dict[str, Any]:
    if limit < 1:
        limit = 1
    store = get_metrics_store(limit=limit)
    items = store["items"]
    request_items = [item for item in items if item.get("event_type") == "request"]
    judge_items = [item for item in items if item.get("event_type") == "quality_judge"]

    quality_requests = 0
    quality_failures: Counter[str] = Counter()
    passed_total = 0
    for item in request_items:
        quality_checks = item.get("quality_checks") or {}
        checks = quality_checks.get("checks") or {}
        if not checks:
            continue
        quality_requests += 1
        if quality_checks.get("passed") is True:
            passed_total += 1
        for key in core._QUALITY_CHECK_KEYS:
            if checks.get(key) is False:
                quality_failures[key] += 1

    failure_rates: dict[str, float] = {}
    if quality_requests > 0:
        for key in core._QUALITY_CHECK_KEYS:
            if quality_failures[key] > 0:
                failure_rates[key] = round(quality_failures[key] / quality_requests, 3)

    score_buckets: dict[str, list[float]] = {}
    for item in judge_items:
        raw_scores = item.get("scores")
        if not isinstance(raw_scores, dict):
            continue
        for name, value in raw_scores.items():
            try:
                score_buckets.setdefault(str(name), []).append(float(value))
            except (TypeError, ValueError):
                continue

    avg_scores = {
        name: round(sum(vals) / len(vals), 4) for name, vals in score_buckets.items() if vals
    }

    return {
        "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
        "window_size": {
            "requests": len(request_items),
            "judge_samples": len(judge_items),
        },
        "deterministic": {
            "requests_with_checks": quality_requests,
            "passed_count": passed_total,
            "pass_rate": round(passed_total / quality_requests, 3) if quality_requests else None,
            "failure_counts": dict(quality_failures),
            "failure_rates": failure_rates,
        },
        "judge": {
            "samples_total": len(judge_items),
            "errors_total": sum(1 for item in judge_items if item.get("error")),
            "avg_scores": avg_scores,
        },
    }


from app.metrics_slo import (  # noqa: E402
    aggregate_route_demotion_from_store,
    collect_latency_by_query_mode,
    evaluate_slo_alerts,
    evaluate_slo_alerts_and_notify,
)
