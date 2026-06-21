"""Core schemas, versions and common helpers for metrics."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

# Схемы артефактов observability
METRICS_STORE_SCHEMA_VERSION = 1
PIPELINE_TRACE_SCHEMA_VERSION = 1
RETRIEVAL_TRACE_SCHEMA_VERSION = 1
_METRICS_DASHBOARD_DB_SCHEMA_VERSION = 1

_settings = get_settings()
METRICS_STORE_PATH = Path(_settings.metrics_store_path)
METRICS_DASHBOARD_DB_PATH = Path(_settings.metrics_dashboard_db_path)

_QUALITY_CHECK_KEYS = (
    "answer_not_empty",
    "has_sources",
    "answer_length_in_range",
    "no_fallback_with_sources",
    "min_source_score_ok",
)
_STAGE_COST_KEYS = ("classify", "rewrite", "retrieval", "generation", "judge")


def _safe_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _current_timestamp() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    idx = int(round(percentile * (len(sorted_values) - 1)))
    return round(sorted_values[idx], 3)


def _day_week_from_timestamp(ts: str | None) -> tuple[str | None, str | None]:
    if not ts or not isinstance(ts, str):
        return None, None
    raw = ts.strip()
    if len(raw) < 10 or raw[4] != "-" or raw[7] != "-":
        return None, None
    day = raw[:10]
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        y, w, _ = dt.isocalendar()
        return day, f"{y}-W{w:02d}"
    except ValueError:
        return day, None


def check_pipeline_trace_schema(trace: dict[str, Any] | None) -> dict[str, Any]:
    """Проверка совместимости вложенного pipeline_trace."""
    if not trace:
        return {
            "ok": True,
            "expected_version": PIPELINE_TRACE_SCHEMA_VERSION,
            "actual_version": None,
            "note": "empty_trace",
        }
    actual = trace.get("schema_version")
    if actual is None:
        return {
            "ok": False,
            "expected_version": PIPELINE_TRACE_SCHEMA_VERSION,
            "actual_version": None,
            "note": "missing_schema_version",
        }
    try:
        av = int(actual)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "expected_version": PIPELINE_TRACE_SCHEMA_VERSION,
            "actual_version": actual,
            "note": "invalid_schema_version",
        }
    if av != PIPELINE_TRACE_SCHEMA_VERSION:
        return {
            "ok": False,
            "expected_version": PIPELINE_TRACE_SCHEMA_VERSION,
            "actual_version": av,
            "note": "version_mismatch",
        }
    required_keys = ("effective_query", "effective_query_source")
    missing_keys = [key for key in required_keys if key not in trace]
    if missing_keys:
        return {
            "ok": False,
            "expected_version": PIPELINE_TRACE_SCHEMA_VERSION,
            "actual_version": av,
            "note": "missing_required_keys",
            "missing_keys": missing_keys,
        }
    return {
        "ok": True,
        "expected_version": PIPELINE_TRACE_SCHEMA_VERSION,
        "actual_version": av,
        "note": None,
    }


def check_metrics_store_line_schema(line: dict[str, Any] | None) -> dict[str, Any]:
    """Проверка одной строки JSONL metrics_store."""
    if not line:
        return {
            "ok": False,
            "expected_version": METRICS_STORE_SCHEMA_VERSION,
            "actual_version": None,
            "note": "empty_line",
        }
    actual = line.get("schema_version")
    if actual is None:
        return {
            "ok": False,
            "expected_version": METRICS_STORE_SCHEMA_VERSION,
            "actual_version": None,
            "note": "missing_schema_version",
        }
    try:
        av = int(actual)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "expected_version": METRICS_STORE_SCHEMA_VERSION,
            "actual_version": actual,
            "note": "invalid_schema_version",
        }
    if av != METRICS_STORE_SCHEMA_VERSION:
        return {
            "ok": False,
            "expected_version": METRICS_STORE_SCHEMA_VERSION,
            "actual_version": av,
            "note": "version_mismatch",
        }
    return {
        "ok": True,
        "expected_version": METRICS_STORE_SCHEMA_VERSION,
        "actual_version": av,
        "note": None,
    }


def check_retrieval_trace_schema(trace: dict[str, Any] | None) -> dict[str, Any]:
    if not trace:
        return {
            "ok": True,
            "expected_version": RETRIEVAL_TRACE_SCHEMA_VERSION,
            "actual_version": None,
            "note": "empty_trace",
        }
    actual = trace.get("schema_version")
    if actual is None:
        return {
            "ok": False,
            "expected_version": RETRIEVAL_TRACE_SCHEMA_VERSION,
            "actual_version": None,
            "note": "missing_schema_version",
        }
    try:
        av = int(actual)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "expected_version": RETRIEVAL_TRACE_SCHEMA_VERSION,
            "actual_version": actual,
            "note": "invalid_schema_version",
        }
    if av != RETRIEVAL_TRACE_SCHEMA_VERSION:
        return {
            "ok": False,
            "expected_version": RETRIEVAL_TRACE_SCHEMA_VERSION,
            "actual_version": av,
            "note": "version_mismatch",
        }
    required_keys = (
        "retrieval_mode",
        "query_type",
        "effective_query",
        "effective_query_source",
        "cache_hit",
        "returned_source_count",
    )
    missing_keys = [key for key in required_keys if key not in trace]
    if missing_keys:
        return {
            "ok": False,
            "expected_version": RETRIEVAL_TRACE_SCHEMA_VERSION,
            "actual_version": av,
            "note": "missing_required_keys",
            "missing_keys": missing_keys,
        }
    return {
        "ok": True,
        "expected_version": RETRIEVAL_TRACE_SCHEMA_VERSION,
        "actual_version": av,
        "note": None,
    }
