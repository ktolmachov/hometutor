"""Cross-level SSR AI telemetry stored in ``app_kv`` (local, privacy-safe)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from statistics import quantiles
from typing import Any, Literal

ML_MONITORING_KEY = "ssr_ml_monitoring_v1"
AUX_TELEMETRY_KEY = "ssr_ai_auxiliary_telemetry_v1"
_MAX_EVENTS = 5000

SSRAILevel = Literal["L1", "L2", "L3", "L4", "L5"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_app_kv(conn: Any, key: str, default: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT value FROM app_kv WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        value = json.loads(str(row["value"]))
    except json.JSONDecodeError:
        return default
    return value if isinstance(value, dict) else default


def write_app_kv(conn: Any, key: str, value: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO app_kv(key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, json.dumps(value, ensure_ascii=False, sort_keys=True), utc_now_iso()),
    )


def append_kv_events(
    conn: Any,
    *,
    key: str,
    event: dict[str, Any],
    max_events: int = _MAX_EVENTS,
    list_field: str = "events",
) -> None:
    payload = read_app_kv(conn, key, {list_field: []})
    items = list(payload.get(list_field) or [])
    items.append(event)
    payload[list_field] = items[-max_events:]
    write_app_kv(conn, key, payload)


def summarize_ml_inference_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up L1-style inference events (``latency_ms``, ``confidence``, ``fallback``)."""
    latencies = [float(e["latency_ms"]) for e in events if e.get("latency_ms") is not None]
    confidences = [float(e["confidence"]) for e in events if e.get("confidence") is not None]
    fallback_n = sum(1 for e in events if e.get("fallback"))
    p95 = quantiles(latencies, n=20)[18] if len(latencies) >= 2 else (latencies[0] if latencies else 0.0)
    confidence_over_06 = sum(1 for c in confidences if c > 0.6) / max(1, len(confidences))
    return {
        "events": len(events),
        "inference_latency_p95_ms": round(float(p95), 3),
        "confidence_over_0_6_rate": round(float(confidence_over_06), 4),
        "fallback_rate": round(float(fallback_n / max(1, len(events))), 4),
    }


def record_ssr_ai_auxiliary_event(
    *,
    level: SSRAILevel,
    category: str,
    detail: dict[str, Any] | None = None,
) -> None:
    from app.user_state import _with_db

    def _write(conn: Any) -> None:
        append_kv_events(
            conn,
            key=AUX_TELEMETRY_KEY,
            event={
                "ts": utc_now_iso(),
                "level": level,
                "category": category,
                "detail": detail or {},
            },
        )

    _with_db(_write, write=True)


def summarize_ssr_ai_auxiliary(*, max_events: int = 500) -> dict[str, Any]:
    """Lightweight read-only summary for ops / higher levels."""

    from app.user_state import _with_db

    def _read(conn: Any) -> dict[str, Any]:
        payload = read_app_kv(conn, AUX_TELEMETRY_KEY, {"events": []})
        events = list(payload.get("events") or [])[-max_events:]
        by_cat: dict[str, int] = {}
        for e in events:
            cat = str(e.get("category") or "unknown")
            by_cat[cat] = by_cat.get(cat, 0) + 1
        return {"events": len(events), "by_category": dict(sorted(by_cat.items()))}

    return _with_db(_read)


__all__ = [
    "AUX_TELEMETRY_KEY",
    "ML_MONITORING_KEY",
    "SSRAILevel",
    "append_kv_events",
    "read_app_kv",
    "record_ssr_ai_auxiliary_event",
    "summarize_ml_inference_events",
    "summarize_ssr_ai_auxiliary",
    "utc_now_iso",
    "write_app_kv",
]
