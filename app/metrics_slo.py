"""SLO evaluation and per-mode latency collection for metrics_store."""

from __future__ import annotations

import json
import logging
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

from app import metrics_core as core


def collect_latency_by_query_mode(
    *,
    limit_events: int = 20000,
    thresholds_ms: dict[str, float] | None = None,
) -> dict[str, Any]:
    if limit_events < 1:
        limit_events = 1
    thresholds = {
        str(k).strip().lower(): float(v)
        for k, v in (thresholds_ms or {}).items()
        if str(k).strip()
    }
    if not core.METRICS_STORE_PATH.exists():
        return {"status": "skipped", "sample_size": 0, "by_mode": {}}

    buf: deque[dict[str, Any]] = deque(maxlen=limit_events)
    with open(core.METRICS_STORE_PATH, "r", encoding="utf-8") as file:
        for line in file:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if item.get("event_type") == "request":
                buf.append(item)

    buckets: dict[str, list[float]] = defaultdict(list)
    for item in buf:
        mode = str(item.get("query_type") or "unknown").strip().lower() or "unknown"
        raw_latency = (item.get("latency_ms") or {}).get("total_answer_ms")
        if raw_latency is None:
            continue
        try:
            buckets[mode].append(float(raw_latency))
        except (TypeError, ValueError):
            continue

    by_mode: dict[str, dict[str, Any]] = {}
    breached = False
    for mode, values in sorted(buckets.items()):
        p95 = core._percentile(values, 0.95)
        threshold = thresholds.get(mode)
        slo_status = "not_configured"
        if threshold is not None and p95 is not None:
            slo_status = "pass" if p95 <= threshold else "fail"
            breached = breached or slo_status == "fail"
        by_mode[mode] = {
            "sample_size": len(values),
            "p50": core._percentile(values, 0.50),
            "p95": p95,
            "slo_threshold_ms": threshold,
            "slo_status": slo_status,
        }

    samples = sum(len(v) for v in buckets.values())
    if not samples:
        return {"status": "skipped", "sample_size": 0, "by_mode": {}}
    return {
        "status": "fail" if breached else "pass",
        "sample_size": samples,
        "by_mode": by_mode,
    }


def _read_request_events_chronological(*, limit: int) -> list[dict[str, Any]]:
    if limit < 1:
        limit = 1
    if not core.METRICS_STORE_PATH.exists():
        return []
    buf: deque[dict[str, Any]] = deque(maxlen=limit)
    with open(core.METRICS_STORE_PATH, "r", encoding="utf-8") as file:
        for line in file:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if item.get("event_type") == "request":
                buf.append(item)
    items = sorted(buf, key=lambda x: x.get("timestamp", ""))
    return items


def _collect_judge_score_averages(*, limit_lines: int) -> dict[str, float]:
    if limit_lines < 1:
        limit_lines = 1
    if not core.METRICS_STORE_PATH.exists():
        return {}
    buf: deque[dict[str, Any]] = deque(maxlen=limit_lines)
    with open(core.METRICS_STORE_PATH, "r", encoding="utf-8") as file:
        for line in file:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if item.get("event_type") == "quality_judge" and not item.get("error"):
                buf.append(item)
    buckets: dict[str, list[float]] = {}
    for item in buf:
        raw_scores = item.get("scores")
        if not isinstance(raw_scores, dict):
            continue
        for name, value in raw_scores.items():
            try:
                buckets.setdefault(str(name), []).append(float(value))
            except (TypeError, ValueError):
                continue
    return {k: round(sum(v) / len(v), 4) for k, v in buckets.items() if v}


def evaluate_slo_alerts(*, limit_events: int = 20000) -> dict[str, Any]:
    """
    Check key performance and quality metrics against SLO thresholds.
    Returns a dict with 'status' (pass/fail) and 'alerts' list.
    """
    import app.config
    settings = app.config.get_settings()
    items = _read_request_events_chronological(limit=limit_events)
    if not items:
        return {"status": "skipped", "alerts": [], "sample_size": 0}

    alerts = []
    observed = {
        "fallback_rate": round(sum(1 for it in items if it.get("fallback_applied") is True) / len(items), 4),
        "source_coverage": round(sum(1 for it in items if (it.get("source_count") or 0) > 0) / len(items), 4),
        "learner_migration": {"rehydrated_rate": None}
    }

    # 1. Fallback Rate
    fallback_rate = observed["fallback_rate"]
    if settings.slo_max_fallback_rate is not None:
        if fallback_rate > settings.slo_max_fallback_rate:
            alerts.append({
                "metric": "fallback_rate",
                "current": fallback_rate,
                "threshold": settings.slo_max_fallback_rate,
                "msg": f"Fallback rate {fallback_rate:.2%} exceeds SLO {settings.slo_max_fallback_rate:.2%}"
            })

    # 2. Source Coverage
    source_coverage = observed["source_coverage"]
    if settings.slo_min_source_coverage is not None:
        if source_coverage < settings.slo_min_source_coverage:
            alerts.append({
                "metric": "source_coverage",
                "current": source_coverage,
                "threshold": settings.slo_min_source_coverage,
                "msg": f"Source coverage {source_coverage:.2%} below SLO {settings.slo_min_source_coverage:.2%}"
            })

    # 3. P95 Latency
    if settings.slo_max_p95_latency_ms is not None:
        latencies = [
            float(lat) for it in items 
            if (lat := (it.get("latency_ms") or {}).get("total_answer_ms")) is not None
        ]
        if latencies:
            p95 = core._percentile(latencies, 0.95)
            observed["p95_latency_ms"] = round(p95, 2)
            if p95 > settings.slo_max_p95_latency_ms:
                alerts.append({
                    "metric": "p95_latency",
                    "current": round(p95, 2),
                    "threshold": settings.slo_max_p95_latency_ms,
                    "msg": f"P95 Latency {p95:.1f}ms exceeds SLO {settings.slo_max_p95_latency_ms}ms"
                })

    # 4. Avg Cost
    costs = [float(c) for it in items if (c := it.get("estimated_cost_usd")) is not None]
    if costs:
        avg_cost = sum(costs) / len(costs)
        observed["avg_cost_usd"] = round(avg_cost, 6)
        if settings.slo_max_avg_cost_usd is not None:
            if avg_cost > settings.slo_max_avg_cost_usd:
                alerts.append({
                    "metric": "avg_cost",
                    "current": round(avg_cost, 6),
                    "threshold": settings.slo_max_avg_cost_usd,
                    "msg": f"Avg cost ${avg_cost:.6f} exceeds SLO ${settings.slo_max_avg_cost_usd:.6f}"
                })

    # 5. Judge Scores (Faithfulness)
    averages = _collect_judge_score_averages(limit_lines=limit_events * 2)
    observed["judge_scores"] = averages
    if settings.slo_min_judge_score is not None:
        score = averages.get("faithfulness")
        if score is not None and score < settings.slo_min_judge_score:
            alerts.append({
                "metric": "low_faithfulness",
                "current": round(score, 4),
                "threshold": settings.slo_min_judge_score,
                "msg": f"Avg faithfulness {score:.3f} below SLO {settings.slo_min_judge_score:.3f}"
            })

    # 6. Learner Rehydrated Rate (Migration anomalies)
    if settings.slo_max_learner_rehydrated_rate is not None:
        try:
            from app.learner_model_service import get_learner_profile_migration_metrics
            migration = get_learner_profile_migration_metrics(limit=limit_events)
            rate = migration.get("rehydrated_rate")
            observed["learner_migration"]["rehydrated_rate"] = rate
            if rate is not None and rate > settings.slo_max_learner_rehydrated_rate:
                alerts.append({
                    "metric": "learner_rehydrated_rate",
                    "current": round(rate, 4),
                    "threshold": settings.slo_max_learner_rehydrated_rate,
                    "msg": f"Learner rehydrated rate {rate:.2%} exceeds SLO {settings.slo_max_learner_rehydrated_rate:.2%}"
                })
        except ImportError:
            pass

    # 7. Per-query-type P95 latency (when slo_latency_by_mode is configured)
    slo_by_mode = getattr(settings, "slo_latency_by_mode", None)
    if slo_by_mode is not None:
        latency_by_mode_res = collect_latency_by_query_mode(
            limit_events=limit_events,
            thresholds_ms=slo_by_mode,
        )
        observed["latency_by_mode"] = latency_by_mode_res
        for mode, stats in (latency_by_mode_res.get("by_mode") or {}).items():
            if stats.get("slo_status") == "fail":
                alerts.append(
                    {
                        "kind": "slo",
                        "metric": "p95_total_answer_ms_by_query_type",
                        "query_type": mode,
                        "severity": "warning",
                        "observed": stats.get("p95"),
                        "threshold": stats.get("slo_threshold_ms"),
                        "message": f"p95 latency above per-mode SLO for query_type={mode}",
                    }
                )

    return {
        "status": "fail" if alerts else "pass",
        "alerts": alerts,
        "sample_size": len(items),
        "observed": observed
    }


def load_graph_route_demotion_state(settings: Any | None = None) -> dict[str, Any]:
    """Read-only persisted demotion latch (fail-safe on corrupt file)."""
    from pathlib import Path

    from app.config import DATA_DIR

    s = settings if settings is not None else core.get_settings()
    rel_name = getattr(s, "graph_route_demotion_state_relative", "graph_route_demotion_state.json")
    state_path = (DATA_DIR / Path(str(rel_name))).resolve()
    default: dict[str, Any] = {
        "consecutive_failures": 0,
        "demoted": False,
        "path": str(state_path),
    }
    if not state_path.is_file():
        return dict(default)
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {**default, "corrupt": True}
    if not isinstance(raw, dict):
        return {**default, "corrupt": True}
    out = dict(default)
    out.update(raw)
    return out


def record_route_demotion_skipped_event(
    *,
    demoted_from: str = "graph_aware",
    demoted_to: str = "quality",
    reason: str = "manual_override",
    details: dict[str, Any] | None = None,
) -> None:
    """ADR-021 §9.2: manual override while demotion latch active."""
    from app.metrics_storage import _append_metrics_event

    _append_metrics_event(
        {
            "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
            "event_type": "route_demotion_skipped",
            "timestamp": core._current_timestamp(),
            "demoted_from": str(demoted_from)[:120],
            "demoted_to": str(demoted_to)[:120],
            "reason": str(reason)[:240],
            "route_demotion_count": 1,
            "details": details or {},
        }
    )


def record_route_demotion_event(
    *,
    demoted_from: str,
    demoted_to: str,
    reason: str,
    route_demotion_count: int = 1,
    details: dict[str, Any] | None = None,
) -> None:
    """ADR-021: инкрементируем наблюдаемость demotion через JSONL metrics store."""
    from app.metrics_storage import _append_metrics_event

    _append_metrics_event(
        {
            "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
            "event_type": "route_demotion",
            "timestamp": core._current_timestamp(),
            "demoted_from": str(demoted_from)[:120],
            "demoted_to": str(demoted_to)[:120],
            "reason": str(reason)[:240],
            "route_demotion_count": max(1, int(route_demotion_count)),
            "details": details or {},
        }
    )


def aggregate_route_demotion_from_store(*, limit_lines: int = 50000) -> dict[str, Any]:
    """Сводка по ``event_type == route_demotion`` (weighted по ``route_demotion_count``)."""
    from collections import Counter

    if limit_lines < 1:
        limit_lines = 1
    if not core.METRICS_STORE_PATH.exists():
        return {"status": "skipped", "events_total": 0, "weighted_total": 0, "by_tuple": {}}
    buf: deque[dict[str, Any]] = deque(maxlen=limit_lines)
    with open(core.METRICS_STORE_PATH, "r", encoding="utf-8") as file:
        for line in file:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if item.get("event_type") == "route_demotion":
                buf.append(item)

    tuples: Counter[str] = Counter()
    weighted_total = 0
    for item in buf:
        weight = max(1, int(item.get("route_demotion_count") or 1))
        weighted_total += weight
        key = "|".join(
            [
                str(item.get("demoted_from") or ""),
                str(item.get("demoted_to") or ""),
                str(item.get("reason") or ""),
            ]
        )
        tuples[key] += weight

    return {
        "status": "ok",
        "events_total": len(buf),
        "weighted_total": weighted_total,
        "by_tuple": dict(sorted(tuples.items())),
    }


def graph_uplift_eval_report(*, baseline_metric: float, graph_metric: float) -> dict[str, float]:
    """Отчётное смещение graph vs baseline uplift (offline eval scaffolding)."""
    b = float(baseline_metric)
    g = float(graph_metric)
    return {"baseline_metric": b, "graph_metric": g, "delta": g - b}


def apply_graph_uplift_demotion_tick(
    *,
    observed_delta: float | None,
    settings: Any | None = None,
) -> dict[str, Any]:
    """
    Persisted latch для offline no-uplift rule.

    Если ``observed_delta`` задан ниже порога несколько запусков подряд —
    включается ``demoted`` и эмитируется ``route_demotion`` event.
    """
    from app.config import DATA_DIR

    s = settings if settings is not None else core.get_settings()
    rel_name = getattr(s, "graph_route_demotion_state_relative", "graph_route_demotion_state.json")
    state_path = (DATA_DIR / Path(str(rel_name))).resolve()
    state_path.parent.mkdir(parents=True, exist_ok=True)

    state: dict[str, Any] = {"consecutive_failures": 0, "demoted": False}
    if state_path.is_file():
        try:
            state.update(json.loads(state_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass

    payload = dict(state)
    payload["path"] = str(state_path)
    payload["demotion_event_emitted"] = False

    if observed_delta is None:
        return payload

    thr = float(getattr(s, "graph_uplift_min_delta", 0.05))
    need = int(getattr(s, "graph_uplift_consecutive_runs", 3))
    consecutive = int(state.get("consecutive_failures") or 0)
    demoted = bool(state.get("demoted"))

    triggered = False
    if observed_delta < thr:
        consecutive += 1
    else:
        consecutive = 0
        demoted = False

    if consecutive >= need and not demoted:
        demoted = True
        triggered = True
        record_route_demotion_event(
            demoted_from="graph_aware",
            demoted_to="quality",
            reason="graph_no_uplift_below_delta",
            details={
                "observed_delta": observed_delta,
                "threshold": thr,
                "runs": need,
            },
        )

    state.update({"consecutive_failures": consecutive, "demoted": demoted})
    try:
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        return {**payload, "error": str(exc)[:240]}

    return {
        **state,
        "path": str(state_path),
        "demotion_event_emitted": triggered,
    }


def evaluate_slo_alerts_and_notify(*, limit_events: int = 20000, send_webhook: bool = False) -> dict[str, Any]:
    """Check SLOs and optionally trigger an external webhook if status is 'fail'."""
    res = evaluate_slo_alerts(limit_events=limit_events)
    if send_webhook and res["status"] == "fail":
        settings = core.get_settings()
        if settings.alert_webhook_url:
            try:
                import requests
                # Non-blocking-ish fire and forget or simple post
                requests.post(
                    settings.alert_webhook_url,
                    json={
                        "event": "slo_breach",
                        "alerts": res["alerts"],
                        "sample_size": res["sample_size"]
                    },
                    timeout=5
                )
            except Exception:
                _log.warning("Alert webhook delivery failed url=%s", settings.alert_webhook_url, exc_info=True)
    return res
