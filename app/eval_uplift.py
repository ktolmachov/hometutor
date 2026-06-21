"""Rule-based graph uplift metrics and gate evaluation (ADR-021 §9)."""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import BASE_DIR, get_settings

UPLIFT_REPORT_SCHEMA_VERSION = 1
GRAPH_SHAPED_DATASET_REL = "eval_data/graph_shaped_ii_agenty.json"
GRAPH_SHAPED_CATEGORIES = frozenset({"relationship", "prerequisite", "dependency"})

LOCAL_UPLIFT_GATE_DEFAULTS: dict[str, float] = {
    "min_correctness_delta": 0.02,
    "min_evidence_quality_delta": 0.02,
    "min_citation_correctness_delta": 0.01,
    "max_latency_p95_delta_ms": 40.0,
}

STRICT_UPLIFT_GATE_DEFAULTS: dict[str, float] = {
    "min_correctness_delta": 0.03,
    "min_evidence_quality_delta": 0.03,
    "min_citation_correctness_delta": 0.02,
    "max_latency_p95_delta_ms": 30.0,
}


def graph_shaped_dataset_path() -> Path:
    return BASE_DIR / GRAPH_SHAPED_DATASET_REL


def load_graph_shaped_dataset(path: Path | None = None) -> dict[str, Any]:
    p = path or graph_shaped_dataset_path()
    return json.loads(p.read_text(encoding="utf-8"))


def iter_graph_shaped_items(dataset: dict[str, Any]) -> list[dict[str, Any]]:
    cats = dataset.get("categories")
    if not isinstance(cats, dict):
        return []
    items: list[dict[str, Any]] = []
    for name, block in cats.items():
        if not isinstance(block, list):
            continue
        for raw in block:
            if isinstance(raw, dict):
                item = dict(raw)
                item.setdefault("category", name)
                items.append(item)
    return items


def _normalize_doc_id(value: str) -> str:
    return str(value).strip().replace("\\", "/").lower()


def _source_names_from_case(case: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("retrieved_doc_ids", "top_k_doc_ids"):
        raw = case.get(key)
        if isinstance(raw, list):
            for item in raw:
                names.add(_normalize_doc_id(str(item)))
    sources = case.get("sources")
    if isinstance(sources, list):
        for src in sources:
            if isinstance(src, dict):
                for field in ("file_name", "relative_path", "doc_id", "document_id"):
                    val = src.get(field)
                    if val:
                        names.add(_normalize_doc_id(str(val)))
            elif isinstance(src, str) and src.strip():
                names.add(_normalize_doc_id(src))
    return names


def _expected_doc_ids(case: dict[str, Any]) -> list[str]:
    raw = case.get("expected_doc_ids")
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def case_correctness_pass(case: dict[str, Any], *, top_k: int = 5) -> bool:
    expected = _expected_doc_ids(case)
    if not expected:
        return False
    retrieved = _source_names_from_case(case)
    if not retrieved:
        return False
    for doc_id in expected[:top_k]:
        norm = _normalize_doc_id(doc_id)
        if any(norm in r or r.endswith(norm.split("/")[-1]) for r in retrieved):
            return True
    return False


def _chunk_graph_evidence_confidence(chunk: dict[str, Any]) -> float | None:
    meta = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    evidences = meta.get("graph_evidence")
    if not isinstance(evidences, list):
        return None
    best: float | None = None
    for raw in evidences:
        if not isinstance(raw, dict):
            continue
        try:
            conf = float(raw.get("confidence"))
        except (TypeError, ValueError):
            continue
        best = conf if best is None else max(best, conf)
    return best


def case_evidence_quality_pass(
    case: dict[str, Any],
    *,
    weak_threshold: float | None = None,
) -> bool:
    if not case.get("graph_applied"):
        return False
    thr = float(weak_threshold if weak_threshold is not None else get_settings().graph_evidence_weak_threshold)
    chunks = case.get("expanded_chunks")
    if not isinstance(chunks, list):
        trace = case.get("graph_expansion") if isinstance(case.get("graph_expansion"), dict) else {}
        evidences = trace.get("graph_evidence")
        if isinstance(evidences, list):
            for raw in evidences:
                if not isinstance(raw, dict):
                    continue
                try:
                    conf = float(raw.get("confidence"))
                except (TypeError, ValueError):
                    continue
                if conf >= thr:
                    return True
        return False
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        conf = _chunk_graph_evidence_confidence(chunk)
        if conf is not None and conf >= thr:
            return True
    return False


def case_citation_correctness_pass(case: dict[str, Any]) -> bool:
    expected = [_normalize_doc_id(x) for x in _expected_doc_ids(case)]
    if not expected:
        return False
    cited = _source_names_from_case(case)
    if not cited:
        return False
    return all(
        any(exp in c or c.endswith(exp.split("/")[-1]) for c in cited)
        for exp in expected
    )


def _rate(pass_count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(pass_count / total, 4)


def aggregate_profile_case_metrics(
    cases: list[dict[str, Any]],
    *,
    weak_threshold: float | None = None,
) -> dict[str, Any]:
    correctness_pass = 0
    evidence_pass = 0
    citation_pass = 0
    graph_applied_total = 0
    latencies: list[float] = []
    total = len(cases)
    for case in cases:
        if case_correctness_pass(case):
            correctness_pass += 1
        if case.get("graph_applied"):
            graph_applied_total += 1
            if case_evidence_quality_pass(case, weak_threshold=weak_threshold):
                evidence_pass += 1
        if case_citation_correctness_pass(case):
            citation_pass += 1
        try:
            lat = float(case.get("latency_ms"))
            if lat >= 0:
                latencies.append(lat)
        except (TypeError, ValueError):
            pass

    latencies_sorted = sorted(latencies)
    p50 = latencies_sorted[len(latencies_sorted) // 2] if latencies_sorted else None
    p95_idx = max(0, int(len(latencies_sorted) * 0.95) - 1)
    p95 = latencies_sorted[p95_idx] if latencies_sorted else None

    return {
        "cases": total,
        "correctness_rate": _rate(correctness_pass, total),
        "evidence_quality_rate": _rate(evidence_pass, graph_applied_total),
        "citation_correctness_rate": _rate(citation_pass, total),
        "graph_applied_cases": graph_applied_total,
        "p50_latency_ms": round(p50, 2) if p50 is not None else None,
        "p95_latency_ms": round(p95, 2) if p95 is not None else None,
    }


def _git_commit_short() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return out.decode("utf-8").strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def build_graph_uplift_report(
    *,
    quality_cases: list[dict[str, Any]],
    graph_aware_cases: list[dict[str, Any]],
    generation_id: str | None = None,
    dataset_version: str | None = None,
    run_id: str | None = None,
    config_snapshot: dict[str, Any] | None = None,
    includes_defense_categories: bool = True,
    weak_threshold: float | None = None,
) -> dict[str, Any]:
    """Serialize uplift comparison report with US-12.7 metadata block."""
    rid = run_id or str(uuid.uuid4())
    quality_summary = aggregate_profile_case_metrics(quality_cases, weak_threshold=weak_threshold)
    graph_summary = aggregate_profile_case_metrics(graph_aware_cases, weak_threshold=weak_threshold)
    deltas: dict[str, Any] = {}
    for metric in (
        "correctness_rate",
        "evidence_quality_rate",
        "citation_correctness_rate",
    ):
        q = quality_summary.get(metric)
        g = graph_summary.get(metric)
        if q is not None and g is not None:
            deltas[f"{metric}_delta"] = round(float(g) - float(q), 4)
    q_p95 = quality_summary.get("p95_latency_ms")
    g_p95 = graph_summary.get("p95_latency_ms")
    if q_p95 is not None and g_p95 is not None:
        deltas["latency_p95_delta_ms"] = round(float(g_p95) - float(q_p95), 2)

    settings = get_settings()
    snapshot = dict(config_snapshot or {})
    snapshot.setdefault("enable_graph_augmented_retrieval", settings.enable_graph_augmented_retrieval)
    snapshot.setdefault("graph_evidence_weak_threshold", settings.graph_evidence_weak_threshold)

    return {
        "schema_version": UPLIFT_REPORT_SCHEMA_VERSION,
        "eval_kind": "graph_uplift",
        "run_id": rid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "generation_id": generation_id,
        "dataset_version": dataset_version,
        "includes_defense_categories": includes_defense_categories,
        "config_snapshot": snapshot,
        "git_commit": _git_commit_short(),
        "profiles": {
            "quality": quality_summary,
            "graph_aware": graph_summary,
        },
        "deltas": deltas,
        "quality_cases": quality_cases,
        "graph_aware_cases": graph_aware_cases,
    }


def evaluate_uplift_gate(
    report: dict[str, Any],
    thresholds: dict[str, float] | None = None,
    *,
    expected_generation_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate uplift thresholds; returns actionable metric/delta/threshold checks."""
    thr = dict(LOCAL_UPLIFT_GATE_DEFAULTS)
    if thresholds:
        thr.update(thresholds)

    checks: list[dict[str, Any]] = []
    report_gen = str(report.get("generation_id") or "").strip()
    exp_gen = str(expected_generation_id or "").strip()

    if exp_gen and report_gen and report_gen != exp_gen:
        checks.append(
            {
                "metric": "generation_id_binding",
                "operator": "==",
                "threshold": exp_gen,
                "actual": report_gen,
                "delta": None,
                "passed": False,
                "reason_key": "stale_generation_binding",
            }
        )

    deltas = report.get("deltas") if isinstance(report.get("deltas"), dict) else {}

    def add_delta_check(
        metric_key: str,
        delta_key: str,
        threshold: float,
        operator: str,
        reason_key: str,
    ) -> None:
        if delta_key not in deltas:
            return
        actual = deltas.get(delta_key)
        if actual is None:
            checks.append(
                {
                    "metric": metric_key,
                    "operator": operator,
                    "threshold": threshold,
                    "actual": None,
                    "delta": None,
                    "passed": False,
                    "reason_key": reason_key,
                }
            )
            return
        val = float(actual)
        if operator == ">=":
            passed = val >= threshold
        elif operator == "<=":
            passed = val <= threshold
        else:
            raise ValueError(f"Unsupported operator: {operator}")
        checks.append(
            {
                "metric": metric_key,
                "operator": operator,
                "threshold": threshold,
                "actual": val,
                "delta": val,
                "passed": passed,
                "reason_key": reason_key,
            }
        )

    add_delta_check(
        "correctness_delta",
        "correctness_rate_delta",
        float(thr["min_correctness_delta"]),
        ">=",
        "correctness_delta_below_threshold",
    )
    add_delta_check(
        "evidence_quality_delta",
        "evidence_quality_rate_delta",
        float(thr["min_evidence_quality_delta"]),
        ">=",
        "evidence_quality_delta_below_threshold",
    )
    add_delta_check(
        "citation_correctness_delta",
        "citation_correctness_rate_delta",
        float(thr["min_citation_correctness_delta"]),
        ">=",
        "citation_correctness_delta_below_threshold",
    )
    add_delta_check(
        "latency_p95_delta_ms",
        "latency_p95_delta_ms",
        float(thr["max_latency_p95_delta_ms"]),
        "<=",
        "latency_p95_delta_above_threshold",
    )

    failed = [c for c in checks if not c["passed"]]
    return {
        "schema_version": UPLIFT_REPORT_SCHEMA_VERSION,
        "gate_kind": "graph_uplift",
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "thresholds": thr,
        "exit_code": 0 if not failed else 2,
    }
