"""Агрегация JSONL-профилей SSR LLM для сравнения с основным чатом.

Используется CLI ``scripts/summarize_ssr_llm_profiles.py`` и тестами.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def load_ssr_profile_rows(log_dir: Path, *, limit_files: int | None = None) -> list[dict[str, Any]]:
    files = sorted(log_dir.glob("ssr_llm_profile_*.jsonl"))
    if limit_files is not None and limit_files > 0:
        files = files[-limit_files:]
    rows: list[dict[str, Any]] = []
    for path in files:
        for row in read_jsonl(path):
            row["_source_file"] = path.name
            rows.append(row)
    return rows


def _percentile(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    if q <= 0:
        return float(sorted_vals[0])
    if q >= 1:
        return float(sorted_vals[-1])
    k = (len(sorted_vals) - 1) * q
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def summarize_ssr_profile_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Сводка для одной или нескольких выгрузок JSONL."""
    n = len(rows)
    if not n:
        return {
            "records": 0,
            "outcome_counts": {},
            "latency_ms_llm_success_p50": None,
            "latency_ms_llm_success_p95": None,
            "latency_ms_all_with_latency_p50": None,
            "effective_model_top": {},
            "used_main_chat_client_count": 0,
            "used_main_chat_client_rate": 0.0,
            "main_llm_model": None,
        }

    outcomes = Counter(str(r.get("outcome") or "unknown") for r in rows)
    lat_success = sorted(
        float(r["latency_ms"])
        for r in rows
        if r.get("outcome") == "llm_success"
        and r.get("latency_ms") is not None
    )
    lat_any = sorted(
        float(r["latency_ms"])
        for r in rows
        if r.get("latency_ms") is not None
    )
    used_main = sum(1 for r in rows if r.get("used_main_chat_client") is True)
    models = Counter(str(r.get("effective_model") or "unknown") for r in rows)
    main_models = {str(r.get("main_llm_model") or "") for r in rows if r.get("main_llm_model")}

    return {
        "records": n,
        "outcome_counts": dict(outcomes),
        "latency_ms_llm_success_p50": _percentile(lat_success, 0.50),
        "latency_ms_llm_success_p95": _percentile(lat_success, 0.95),
        "latency_ms_all_with_latency_p50": _percentile(lat_any, 0.50),
        "effective_model_top": dict(models.most_common(12)),
        "used_main_chat_client_count": used_main,
        "used_main_chat_client_rate": round(used_main / n, 4),
        "main_llm_model_sample": next(iter(main_models), None),
    }


def format_summary_text(payload: dict[str, Any]) -> str:
    if not payload.get("records"):
        return "No SSR LLM profile records found."

    lines = [
        "SSR LLM profile summary",
        f"Records: {payload['records']}",
        f"Outcomes: {payload['outcome_counts']}",
        f"Latency p50 (llm_success): {payload['latency_ms_llm_success_p50']}",
        f"Latency p95 (llm_success): {payload['latency_ms_llm_success_p95']}",
        f"Latency p50 (any row with latency_ms): {payload['latency_ms_all_with_latency_p50']}",
        f"Used main chat client: {payload['used_main_chat_client_count']} "
        f"({payload['used_main_chat_client_rate']*100:.2f}%)",
        f"main_llm_model (sample): {payload.get('main_llm_model_sample')}",
        "",
        "Top effective_model:",
    ]
    for m, c in (payload.get("effective_model_top") or {}).items():
        lines.append(f"  - {m}: {c}")
    return "\n".join(lines)
