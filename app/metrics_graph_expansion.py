"""Graph expansion specific metrics aggregation logic."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from app import metrics_core as core


def compact_graph_expansion_for_metrics(raw: Any) -> dict[str, Any] | None:
    """
    Сжатый снимок ctx.trace["graph_expansion"] для JSONL и агрегатов.
    """
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[str, Any] = {}
    ms = raw.get("graph_expansion_ms")
    if ms is not None:
        try:
            out["graph_expansion_ms"] = round(float(ms), 3)
        except (TypeError, ValueError):
            out["graph_expansion_ms"] = None
    else:
        out["graph_expansion_ms"] = None
    if raw.get("skipped") is not None:
        out["skipped"] = bool(raw.get("skipped"))
    if raw.get("ok") is not None:
        out["ok"] = bool(raw.get("ok"))
    reason = raw.get("reason")
    if reason is not None:
        out["reason"] = str(reason)[:120]
    err = raw.get("error")
    if err is not None:
        out["error"] = str(err)[:240]
    err_type = raw.get("error_type")
    if err_type is not None:
        out["error_type"] = str(err_type)[:120]
    for key in ("hops_applied", "concepts_touched", "extra_chunk_count", "merged_total", "max_hops"):
        if key not in raw:
            continue
        n = core._safe_int(raw.get(key))
        if n is not None:
            out[key] = n
    wk = core._safe_int(raw.get("weak_graph_evidence_count"))
    if wk is not None:
        out["weak_graph_evidence_count"] = wk
    ge_sample = raw.get("graph_evidence")
    if isinstance(ge_sample, list) and ge_sample:
        out["graph_evidence_items"] = len(ge_sample)
    return out


def _normalize_graph_expansion_label(value: Any, *, fallback: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    return text or fallback


def _counter_public_view(raw: Any) -> dict[str, int]:
    if not isinstance(raw, Counter):
        if not isinstance(raw, dict):
            return {}
        items = raw.items()
    else:
        items = raw.items()
    pairs: list[tuple[str, int]] = []
    for key, value in items:
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        pairs.append((str(key), count))
    pairs.sort(key=lambda item: (-item[1], item[0]))
    return {key: value for key, value in pairs}


def _new_graph_expansion_accumulator() -> dict[str, Any]:
    return {
        "events_total": 0,
        "applied_total": 0,
        "skipped_total": 0,
        "error_total": 0,
        "unknown_outcome_total": 0,
        "latency_ms_total": 0.0,
        "extra_chunks_total": 0,
        "latency_samples_ms": [],
        "skip_reasons": Counter(),
        "error_types": Counter(),
        "by_query_type": {},
    }


def _update_graph_expansion_aggregates(
    ge_summary: dict[str, Any],
    gx: dict[str, Any],
    *,
    query_type: str | None = None,
) -> None:
    gx["events_total"] += 1
    if query_type is not None:
        by_query_type = gx.setdefault("by_query_type", {})
        qkey = _normalize_graph_expansion_label(query_type)
        bucket = by_query_type.get(qkey)
        if not isinstance(bucket, dict):
            bucket = _new_graph_expansion_accumulator()
            by_query_type[qkey] = bucket
        _update_graph_expansion_aggregates(ge_summary, bucket, query_type=None)
    ms = ge_summary.get("graph_expansion_ms")
    if ms is not None:
        try:
            msv = float(ms)
            gx["latency_ms_total"] += msv
            gx["latency_samples_ms"].append(msv)
        except (TypeError, ValueError):
            pass
    if ge_summary.get("skipped"):
        gx["skipped_total"] += 1
        gx.setdefault("skip_reasons", Counter())[
            _normalize_graph_expansion_label(ge_summary.get("reason"))
        ] += 1
    elif ge_summary.get("ok") is False:
        gx["error_total"] += 1
        gx.setdefault("error_types", Counter())[
            _normalize_graph_expansion_label(ge_summary.get("error_type"))
        ] += 1
    elif ge_summary.get("ok") is True:
        gx["applied_total"] += 1
        ec = core._safe_int(ge_summary.get("extra_chunk_count"))
        if ec is not None:
            gx["extra_chunks_total"] += ec
    else:
        gx["unknown_outcome_total"] += 1


def _graph_expansion_public_view(
    gx: dict[str, Any],
    *,
    include_query_breakdown: bool = True,
) -> dict[str, Any]:
    gev = int(gx.get("events_total") or 0)
    gsamples = gx.get("latency_samples_ms") or []
    if not isinstance(gsamples, list):
        gsamples = []
    applied = int(gx.get("applied_total") or 0)
    skipped = int(gx.get("skipped_total") or 0)
    errors = int(gx.get("error_total") or 0)
    unknown = int(gx.get("unknown_outcome_total") or 0)
    lat_total = float(gx.get("latency_ms_total") or 0.0)
    extra_total = int(gx.get("extra_chunks_total") or 0)
    out = {
        "events_total": gev,
        "applied_total": applied,
        "skipped_total": skipped,
        "error_total": errors,
        "unknown_outcome_total": unknown,
        "applied_rate": round(applied / gev, 4) if gev else None,
        "skipped_rate": round(skipped / gev, 4) if gev else None,
        "error_rate": round(errors / gev, 4) if gev else None,
        "unknown_outcome_rate": round(unknown / gev, 4) if gev else None,
        "avg_graph_expansion_ms": round(lat_total / len(gsamples), 3) if gsamples else None,
        "p50_graph_expansion_ms": core._percentile(gsamples, 0.50),
        "p95_graph_expansion_ms": core._percentile(gsamples, 0.95),
        "p99_graph_expansion_ms": core._percentile(gsamples, 0.99),
        "avg_extra_chunks_when_applied": round(extra_total / applied, 3) if applied else None,
        "extra_chunks_total": extra_total,
        "skip_reasons": _counter_public_view(gx.get("skip_reasons")),
        "error_types": _counter_public_view(gx.get("error_types")),
    }
    if include_query_breakdown:
        query_buckets = gx.get("by_query_type") or {}
        if isinstance(query_buckets, dict) and query_buckets:
            out["by_query_type"] = {
                str(query_type): _graph_expansion_public_view(bucket, include_query_breakdown=False)
                for query_type, bucket in sorted(query_buckets.items())
                if isinstance(bucket, dict)
            }
    return out


def aggregate_graph_expansion_from_request_events(
    events: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    gx = _new_graph_expansion_accumulator()
    for item in events:
        et = item.get("event_type")
        if et is not None and et != "request":
            continue
        ge = item.get("graph_expansion")
        if isinstance(ge, dict) and ge:
            _update_graph_expansion_aggregates(ge, gx, query_type=item.get("query_type"))
    return _graph_expansion_public_view(gx)
