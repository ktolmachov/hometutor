"""Local SSR ML monitoring and A/B counters stored in user_state.db."""

from __future__ import annotations

from typing import Any, Literal

from app.ssr_ai.telemetry import (
    ML_MONITORING_KEY,
    append_kv_events,
    read_app_kv,
    summarize_ml_inference_events,
    utc_now_iso,
    write_app_kv,
)

_AB_KEY = "ssr_ml_ab_test_v1"
_MAX_EVENTS = 5000


def record_ssr_ml_inference(
    *,
    latency_ms: float,
    confidence: float | None,
    fallback: bool,
    reason: str,
) -> None:
    from app.user_state import _with_db

    def _write(conn) -> None:
        append_kv_events(
            conn,
            key=ML_MONITORING_KEY,
            event={
                "ts": utc_now_iso(),
                "latency_ms": round(float(latency_ms), 3),
                "confidence": None if confidence is None else round(float(confidence), 4),
                "fallback": bool(fallback),
                "reason": str(reason),
            },
            max_events=_MAX_EVENTS,
        )

    _with_db(_write, write=True)


def summarize_ssr_ml_monitoring() -> dict[str, Any]:
    from app.user_state import _with_db

    def _read(conn) -> dict[str, Any]:
        payload = read_app_kv(conn, ML_MONITORING_KEY, {"events": []})
        events = list(payload.get("events") or [])
        return summarize_ml_inference_events(events)

    return _with_db(_read)


def set_ssr_ml_ab_assignment(variant: Literal["control", "treatment"]) -> None:
    from app.user_state import _with_db

    if variant not in {"control", "treatment"}:
        raise ValueError("variant must be control or treatment")

    def _write(conn) -> None:
        payload = read_app_kv(conn, _AB_KEY, {"variant": "control", "events": []})
        payload["variant"] = variant
        payload["updated_at"] = utc_now_iso()
        write_app_kv(conn, _AB_KEY, payload)

    _with_db(_write, write=True)


def get_ssr_ml_real_sample_count() -> int:
    from app.user_state import _with_db

    def _read(conn) -> int:
        try:
            row = conn.execute("SELECT COUNT(*) AS n FROM flashcards").fetchone()
            return int(row["n"]) if row else 0
        except Exception:  # noqa: BLE001
            return 0

    return _with_db(_read)


def get_ssr_ml_ab_assignment() -> Literal["control", "treatment"]:
    from app.user_state import _with_db
    import random

    def _read(conn) -> Literal["control", "treatment"]:
        payload = read_app_kv(conn, _AB_KEY, {})
        if not payload or "variant" not in payload:
            variant = "treatment" if random.random() < 0.5 else "control"
            payload = {
                "variant": variant,
                "events": [],
                "assigned_at": utc_now_iso()
            }
            write_app_kv(conn, _AB_KEY, payload)
            return variant
        return "treatment" if payload.get("variant") == "treatment" else "control"

    try:
        return _with_db(_read, write=True)
    except Exception:  # noqa: BLE001
        # Fallback to pure read-only in case of connection locking issues
        def _read_fallback(conn) -> Literal["control", "treatment"]:
            payload = read_app_kv(conn, _AB_KEY, {"variant": "control", "events": []})
            return "treatment" if payload.get("variant") == "treatment" else "control"
        return _with_db(_read_fallback)


def record_cards_due_completion(*, shown_due_count: int, completed_due_count: int, variant: str | None = None) -> None:
    from app.user_state import _with_db

    def _write(conn) -> None:
        payload = read_app_kv(conn, _AB_KEY, {"variant": "control", "events": []})
        active_variant = variant or payload.get("variant") or "control"
        events = list(payload.get("events") or [])
        events.append(
            {
                "ts": utc_now_iso(),
                "variant": "treatment" if active_variant == "treatment" else "control",
                "shown_due_count": max(0, int(shown_due_count)),
                "completed_due_count": max(0, int(completed_due_count)),
            }
        )
        payload["events"] = events[-_MAX_EVENTS:]
        write_app_kv(conn, _AB_KEY, payload)

    _with_db(_write, write=True)


def summarize_cards_due_completion_ab() -> dict[str, Any]:
    from app.user_state import _with_db

    def _read(conn) -> dict[str, Any]:
        payload = read_app_kv(conn, _AB_KEY, {"variant": "control", "events": []})
        summary: dict[str, Any] = {}
        for variant in ("control", "treatment"):
            events = [e for e in payload.get("events", []) if e.get("variant") == variant]
            shown = sum(int(e.get("shown_due_count") or 0) for e in events)
            completed = sum(int(e.get("completed_due_count") or 0) for e in events)
            summary[variant] = {
                "events": len(events),
                "shown_due_count": shown,
                "completed_due_count": completed,
                "cards_due_completion_rate": round(float(completed / shown), 4) if shown else 0.0,
            }
        summary["active_variant"] = "treatment" if payload.get("variant") == "treatment" else "control"
        return summary

    return _with_db(_read)
