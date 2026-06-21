"""SQLite caching for dashboard metrics."""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any

from filelock import FileLock

from app import metrics_core as core


def _ensure_dashboard_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_bucket (
            granularity TEXT NOT NULL,
            bucket_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (granularity, bucket_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dashboard_meta (
            k TEXT PRIMARY KEY,
            v TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _dashboard_db_meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT v FROM dashboard_meta WHERE k = ?", (key,)).fetchone()
    return row[0] if row else None


def _dashboard_db_meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO dashboard_meta (k, v) VALUES (?, ?)", (key, value))


def _new_bucket_accumulator() -> dict[str, Any]:
    return {
        "count": 0,
        "total_answer_ms": [],
        "pipeline_ms": [],
        "costs": [],
        "qc_checked": 0,
        "qc_passed": 0,
    }


def _feed_request_into_buckets(
    item: dict[str, Any],
    by_day: dict[str, dict[str, Any]],
    by_week: dict[str, dict[str, Any]],
) -> None:
    day_id, week_id = core._day_week_from_timestamp(item.get("timestamp"))
    latency = item.get("latency_ms") or {}
    ta = latency.get("total_answer_ms")
    pl = latency.get("pipeline_ms")
    cost = item.get("estimated_cost_usd")
    qc = item.get("quality_checks") or {}
    checks = qc.get("checks") or {}
    has_checks = bool(checks)
    passed = qc.get("passed") is True

    for bucket_id, target in ((day_id, by_day), (week_id, by_week)):
        if not bucket_id:
            continue
        acc = target.setdefault(bucket_id, _new_bucket_accumulator())
        acc["count"] += 1
        if ta is not None:
            acc["total_answer_ms"].append(core._safe_float(ta))
        if pl is not None:
            acc["pipeline_ms"].append(core._safe_float(pl))
        if cost is not None:
            acc["costs"].append(core._safe_float(cost))
        if has_checks:
            acc["qc_checked"] += 1
            if passed:
                acc["qc_passed"] += 1


def _finalize_request_bucket(acc: dict[str, Any]) -> dict[str, Any]:
    ta = acc["total_answer_ms"]
    pl = acc["pipeline_ms"]
    costs = acc["costs"]
    checked = acc["qc_checked"]
    passed = acc["qc_passed"]
    out: dict[str, Any] = {
        "request_count": acc["count"],
        "latency_ms": {
            "p50_total_answer_ms": core._percentile(ta, 0.50),
            "p95_total_answer_ms": core._percentile(ta, 0.95),
            "p99_total_answer_ms": core._percentile(ta, 0.99),
            "p50_pipeline_ms": core._percentile(pl, 0.50),
            "p95_pipeline_ms": core._percentile(pl, 0.95),
            "p99_pipeline_ms": core._percentile(pl, 0.99),
        },
        "estimated_cost_usd": {
            "total": round(sum(costs), 8) if costs else 0.0,
            "avg_per_request": round(sum(costs) / len(costs), 8) if costs else None,
        },
        "quality": {
            "checked_requests": checked,
            "passed_requests": passed,
            "pass_rate": round(passed / checked, 3) if checked else None,
        },
    }
    return out


def _collect_judge_avgs_by_bucket(
    judge_items: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    from collections import defaultdict
    day_scores: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    week_scores: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for item in judge_items:
        if item.get("error"):
            continue
        raw = item.get("scores")
        if not isinstance(raw, dict):
            continue
        day_id, week_id = core._day_week_from_timestamp(item.get("timestamp"))
        for name, value in raw.items():
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            if day_id:
                day_scores[day_id][str(name)].append(v)
            if week_id:
                week_scores[week_id][str(name)].append(v)

    def _avg_nested(d: dict[str, dict[str, list[float]]]) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for bid, inner in d.items():
            out[bid] = {k: round(sum(vals) / len(vals), 4) for k, vals in inner.items() if vals}
        return out

    return _avg_nested(day_scores), _avg_nested(week_scores)


def _stream_metrics_events_for_dashboard(
    *,
    limit_requests: int,
    limit_judge: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if limit_requests < 1:
        limit_requests = 1
    if limit_judge < 1:
        limit_judge = 1
    req_buf: deque[dict[str, Any]] = deque(maxlen=limit_requests)
    judge_buf: deque[dict[str, Any]] = deque(maxlen=limit_judge)
    if not core.METRICS_STORE_PATH.exists():
        return [], []

    with open(core.METRICS_STORE_PATH, "r", encoding="utf-8") as file:
        for line in file:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            et = item.get("event_type")
            if et == "request":
                req_buf.append(item)
            elif et == "quality_judge":
                judge_buf.append(item)
    return list(req_buf), list(judge_buf)


def _rebuild_metrics_dashboard_db(
    *,
    limit_events: int,
    jsonl_mtime: float,
    jsonl_size: int,
) -> None:
    requests, judges = _stream_metrics_events_for_dashboard(
        limit_requests=limit_events,
        limit_judge=min(5000, max(limit_events, 500)),
    )
    by_day: dict[str, dict[str, Any]] = {}
    by_week: dict[str, dict[str, Any]] = {}
    for item in requests:
        _feed_request_into_buckets(item, by_day, by_week)

    day_judge, week_judge = _collect_judge_avgs_by_bucket(judges)

    core.METRICS_DASHBOARD_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(str(core.METRICS_DASHBOARD_DB_PATH) + ".lock")
    with FileLock(lock_path):
        conn = sqlite3.connect(str(core.METRICS_DASHBOARD_DB_PATH))
        try:
            _ensure_dashboard_db(conn)
            conn.execute("DELETE FROM dashboard_bucket")
            for bid in sorted(by_day.keys()):
                payload = _finalize_request_bucket(by_day[bid])
                ja = day_judge.get(bid)
                if ja:
                    payload["judge_avg_scores"] = ja
                conn.execute(
                    "INSERT INTO dashboard_bucket (granularity, bucket_id, payload) VALUES (?, ?, ?)",
                    ("day", bid, json.dumps(payload, ensure_ascii=False)),
                )
            for bid in sorted(by_week.keys()):
                payload = _finalize_request_bucket(by_week[bid])
                ja = week_judge.get(bid)
                if ja:
                    payload["judge_avg_scores"] = ja
                conn.execute(
                    "INSERT INTO dashboard_bucket (granularity, bucket_id, payload) VALUES (?, ?, ?)",
                    ("week", bid, json.dumps(payload, ensure_ascii=False)),
                )
            _dashboard_db_meta_set(conn, "jsonl_mtime", str(jsonl_mtime))
            _dashboard_db_meta_set(conn, "jsonl_size", str(jsonl_size))
            _dashboard_db_meta_set(conn, "limit_events", str(limit_events))
            _dashboard_db_meta_set(conn, "dashboard_db_schema_version", str(core._METRICS_DASHBOARD_DB_SCHEMA_VERSION))
            conn.commit()
        finally:
            conn.close()


def _read_metrics_dashboard_from_db() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    if not core.METRICS_DASHBOARD_DB_PATH.exists():
        return [], [], {}
    conn = sqlite3.connect(str(core.METRICS_DASHBOARD_DB_PATH))
    try:
        _ensure_dashboard_db(conn)
        daily: list[dict[str, Any]] = []
        weekly: list[dict[str, Any]] = []
        for gran, bid, raw in conn.execute(
            "SELECT granularity, bucket_id, payload FROM dashboard_bucket ORDER BY granularity, bucket_id"
        ):
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {}
            row = {"bucket_id": bid, **body}
            if gran == "day":
                daily.append(row)
            elif gran == "week":
                weekly.append(row)
        meta = {
            "jsonl_mtime": _dashboard_db_meta_get(conn, "jsonl_mtime") or "",
            "jsonl_size": _dashboard_db_meta_get(conn, "jsonl_size") or "",
            "limit_events": _dashboard_db_meta_get(conn, "limit_events") or "",
        }
        return daily, weekly, meta
    finally:
        conn.close()


def _metrics_jsonl_fingerprint() -> tuple[float, int] | None:
    if not core.METRICS_STORE_PATH.exists():
        return None
    st = core.METRICS_STORE_PATH.stat()
    return (st.st_mtime, st.st_size)


def _dashboard_cache_matches(jsonl_mtime: float, jsonl_size: int, limit_events: int) -> bool:
    if not core.METRICS_DASHBOARD_DB_PATH.exists():
        return False
    conn = sqlite3.connect(str(core.METRICS_DASHBOARD_DB_PATH))
    try:
        _ensure_dashboard_db(conn)
        m = _dashboard_db_meta_get(conn, "jsonl_mtime")
        s = _dashboard_db_meta_get(conn, "jsonl_size")
        le = _dashboard_db_meta_get(conn, "limit_events")
        ver = _dashboard_db_meta_get(conn, "dashboard_db_schema_version")
        if ver != str(core._METRICS_DASHBOARD_DB_SCHEMA_VERSION):
            return False
        return (
            m == str(jsonl_mtime)
            and s == str(jsonl_size)
            and le == str(limit_events)
        )
    finally:
        conn.close()


def get_metrics_dashboard(*, limit_events: int = 20000) -> dict[str, Any]:
    if limit_events < 1:
        limit_events = 1
    fp = _metrics_jsonl_fingerprint()
    if fp is None:
        return {
            "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
            "dashboard_db_schema_version": core._METRICS_DASHBOARD_DB_SCHEMA_VERSION,
            "daily": [],
            "weekly": [],
            "summary": {
                "events_window_requests": 0,
                "source": "empty_store",
            },
        }
    mtime, size = fp
    if not _dashboard_cache_matches(mtime, size, limit_events):
        _rebuild_metrics_dashboard_db(limit_events=limit_events, jsonl_mtime=mtime, jsonl_size=size)

    daily, weekly, meta = _read_metrics_dashboard_from_db()
    req_count = sum(int(b.get("request_count") or 0) for b in daily)
    return {
        "schema_version": core.METRICS_STORE_SCHEMA_VERSION,
        "dashboard_db_schema_version": core._METRICS_DASHBOARD_DB_SCHEMA_VERSION,
        "daily": daily,
        "weekly": weekly,
        "summary": {
            "events_window_requests": req_count,
            "jsonl_mtime": meta.get("jsonl_mtime"),
            "jsonl_size": meta.get("jsonl_size"),
            "limit_events": meta.get("limit_events"),
            "source": "sqlite",
        },
    }
