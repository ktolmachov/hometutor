"""JSONL storage and retrieval for metrics events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from filelock import FileLock

from app import metrics_core as core


def _append_metrics_event(entry: dict[str, Any]) -> None:
    core.METRICS_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(core.METRICS_STORE_PATH) + ".lock")
    with FileLock(lock_path):
        with open(core.METRICS_STORE_PATH, "a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_metrics_store(*, request_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    if limit < 1:
        limit = 1
    if not core.METRICS_STORE_PATH.exists():
        return {
            "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
            "items": [],
            "total": 0,
        }

    request_id_filter = (request_id or "").strip()
    items: list[dict[str, Any]] = []

    with open(core.METRICS_STORE_PATH, "r", encoding="utf-8") as file:
        for line in file:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if request_id_filter and item.get("request_id") != request_id_filter:
                continue
            items.append(item)

    items.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return {
        "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
        "items": items[:limit],
        "total": len(items),
    }


def record_quality_judge(
    *,
    request_id: str | None = None,
    scores: dict[str, float] | None = None,
    model: str | None = None,
    query_type: str | None = None,
    latency_ms: float | None = None,
    error: str | None = None,
) -> None:
    """Persist async / sampling judge scores (optional pipeline)."""
    _append_metrics_event(
        {
            "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
            "event_type": "quality_judge",
            "timestamp": core._current_timestamp(),
            "request_id": request_id,
            "scores": scores or {},
            "model": model,
            "query_type": query_type,
            "latency_ms": round(core._safe_float(latency_ms), 3) if latency_ms is not None else None,
            "error": (error or "")[:500] if error else None,
        }
    )


def record_knowledge_workflow_event(
    *,
    action: str,
    knowledge_product_trace: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    client_event_id: str | None = None,
) -> None:
    """Product / UX events from UI (Streamlit) persisted to metrics_store."""
    normalized_action = (action or "").strip() or "unknown"
    trace = knowledge_product_trace if isinstance(knowledge_product_trace, dict) else {}
    entry: dict[str, Any] = {
        "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
        "event_type": "knowledge_workflow",
        "timestamp": core._current_timestamp(),
        "action": normalized_action,
        "knowledge_product_trace": trace,
    }
    if payload:
        entry["payload"] = payload
    if client_event_id:
        entry["client_event_id"] = str(client_event_id)[:120]
    _append_metrics_event(entry)


def record_ingestion_run(
    *,
    run_type: str,
    total_files: int,
    processed_files: int,
    unique_doc_ids: int,
    nodes_count: int,
    summary_documents: int,
    duration_sec: float | None,
    estimated_cost_usd: dict[str, Any] | None = None,
    token_usage: dict[str, Any] | None = None,
    enrichment_stats: dict[str, Any] | None = None,
) -> None:
    _append_metrics_event(
        {
            "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
            "event_type": "ingestion_run",
            "timestamp": core._current_timestamp(),
            "run_type": run_type,
            "total_files": total_files,
            "processed_files": processed_files,
            "unique_doc_ids": unique_doc_ids,
            "nodes_count": nodes_count,
            "summary_documents": summary_documents,
            "duration_sec": round(core._safe_float(duration_sec), 3) if duration_sec is not None else None,
            "estimated_cost_usd": estimated_cost_usd,
            "token_usage": token_usage,
            "enrichment_stats": enrichment_stats,
        }
    )
