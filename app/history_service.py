from __future__ import annotations

import json
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from app.config import get_settings
from app.guardrails import redact_sensitive_text
from app.index_diff import get_index_stats
from app.index_registry import get_index_version_public
from app.logging_config import setup_logging


logger = setup_logging()

HISTORY_PATH = Path(get_settings().history_path)


def _current_timestamp() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _index_version() -> str | None:
    try:
        ver = get_index_version_public()
        iv = ver.get("index_version")
        gid = ver.get("generation_id")
        if iv is not None and gid:
            return f"v{int(iv)}:{gid}"
    except Exception as exc:  # noqa: BLE001 - index lineage is best-effort metadata for history.
        logger.warning("History index version lookup failed: %s", exc)
    try:
        stats = get_index_stats()
    except Exception as exc:  # noqa: BLE001 - history can be saved without index stats.
        logger.warning("History index stats lookup failed: %s", exc)
        return None

    last_indexed_at = stats.get("last_indexed_at")
    collection_name = stats.get("collection_name")
    if not last_indexed_at and not collection_name:
        return None
    return f"{collection_name}:{last_indexed_at}"


def _parse_history_boundary(value: str, *, end_of_day: bool) -> datetime | None:
    """Parse YYYY-MM-DD or ISO datetime; date-only since → start of day, until → end of day UTC."""
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        if "T" not in normalized and len(normalized) <= 10:
            dt = datetime.fromisoformat(normalized).replace(tzinfo=timezone.utc)
            if end_of_day:
                return datetime.combine(dt.date(), time(23, 59, 59, 999999), tzinfo=timezone.utc)
            return datetime.combine(dt.date(), time.min, tzinfo=timezone.utc)
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _entry_timestamp(item: dict[str, Any]) -> datetime | None:
    ts = item.get("timestamp")
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _matches_topic_filter(item: dict[str, Any], topic_substr: str) -> bool:
    t = topic_substr.strip().lower()
    if not t:
        return True
    parts: list[str] = [
        str(item.get("question", "")),
        str(item.get("answer", "")),
        str(item.get("index_version", "")),
    ]
    for src in item.get("sources") or []:
        if not isinstance(src, dict):
            continue
        parts.extend(
            [
                str(src.get("relative_path", "")),
                str(src.get("file_name", "")),
                str(src.get("folder_rel", "")),
                str(src.get("folder_name", "")),
            ]
        )
    hay = " ".join(parts).lower()
    return t in hay


def _redact_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Копирует список источников, редактируя поле text через redact_sensitive_text."""
    out = []
    for s in sources:
        item = dict(s)
        if "text" in item and isinstance(item["text"], str):
            item["text"] = redact_sensitive_text(item["text"])
        out.append(item)
    return out


def append_history_entry(
    *,
    request_id: str,
    question: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    answer = result.get("answer", "")
    sources = result.get("sources") or []
    entry = {
        "request_id": request_id,
        "timestamp": _current_timestamp(),
        "index_version": _index_version(),
        "question": redact_sensitive_text(question),
        "answer": redact_sensitive_text(answer) if isinstance(answer, str) else answer,
        "sources": _redact_sources(sources),
        "confidence": result.get("confidence"),
        "debug": result.get("debug") or {},
    }

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(HISTORY_PATH) + ".lock")
    with FileLock(lock_path):
        with open(HISTORY_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def get_history(
    *,
    q: str | None = None,
    limit: int = 20,
    since: str | None = None,
    until: str | None = None,
    topic: str | None = None,
) -> dict[str, Any]:
    if limit < 1:
        limit = 1
    if not HISTORY_PATH.exists():
        return {"items": [], "total": 0}

    normalized_query = (q or "").strip().lower()
    since_dt = _parse_history_boundary(since or "", end_of_day=False)
    until_dt = _parse_history_boundary(until or "", end_of_day=True)
    items: list[dict[str, Any]] = []

    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Failed to parse history line")
                continue

            if normalized_query:
                haystack = " ".join(
                    [
                        str(item.get("question", "")),
                        str(item.get("answer", "")),
                    ]
                ).lower()
                if normalized_query not in haystack:
                    continue

            if since_dt is not None or until_dt is not None:
                entry_dt = _entry_timestamp(item)
                if entry_dt is None:
                    continue
                if since_dt is not None and entry_dt < since_dt:
                    continue
                if until_dt is not None and entry_dt > until_dt:
                    continue

            if not _matches_topic_filter(item, topic or ""):
                continue

            items.append(item)

    items.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return {
        "items": items[:limit],
        "total": len(items),
    }


def get_pipeline_trace(*, request_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    if limit < 1:
        limit = 1

    history = get_history(limit=max(limit, 2000))
    request_id_filter = (request_id or "").strip()
    items: list[dict[str, Any]] = []

    for item in history.get("items", []):
        if request_id_filter and item.get("request_id") != request_id_filter:
            continue

        debug = item.get("debug") or {}
        pipeline_trace = debug.get("pipeline_trace")
        if not pipeline_trace:
            continue

        items.append(
            {
                "request_id": item.get("request_id"),
                "timestamp": item.get("timestamp"),
                "index_version": item.get("index_version"),
                "query_type": debug.get("query_type"),
                "classify_confidence": debug.get("classify_confidence"),
                "pipeline_trace": pipeline_trace,
            }
        )

    return {
        "items": items[:limit],
        "total": len(items),
    }
