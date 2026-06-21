import json
from pathlib import Path

REGRESSION_THRESHOLD = 0.05
DEFENSE_BASELINE_SCHEMA_VERSION = 1
DEFENSE_REGRESSION_GATE_SCHEMA_VERSION = 1

_BASELINE_PROMOTABLE_SUMMARY_KEYS: tuple[str, ...] = (
    "cases",
    "cases_completed",
    "cases_skipped",
    "dataset_version",
    "avg_latency_sec",
    "p50_latency_sec",
    "p95_latency_sec",
    "avg_answer_relevancy",
    "avg_context_relevancy",
    "avg_faithfulness",
    "avg_retrieval_recall_at_k",
    "avg_retrieval_precision_at_k",
    "avg_retrieval_mrr",
    "avg_retrieval_hit_rate",
    "avg_answer_correctness",
    "route_match_rate",
    "avg_tutor_score",
    "correctness_rate",
    "evidence_quality_rate",
    "citation_correctness_rate",
    "p50_latency_ms",
    "p95_latency_ms",
    "correctness_rate_delta",
    "evidence_quality_rate_delta",
    "citation_correctness_rate_delta",
    "latency_p95_delta_ms",
)


def _load_baseline(path: str | None) -> dict | None:
    if not path:
        return None
    baseline_path = Path(path)
    if not baseline_path.exists():
        return None
    with open(baseline_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _compare_to_baseline(summary: dict, baseline: dict | None) -> dict | None:
    if not baseline:
        return None

    baseline_summary = baseline.get("summary", baseline)
    comparisons = {}
    regressions = []

    tracked_metrics = (
        "avg_answer_relevancy",
        "avg_context_relevancy",
        "avg_faithfulness",
        "avg_retrieval_recall_at_k",
        "avg_retrieval_precision_at_k",
        "avg_retrieval_mrr",
        "avg_retrieval_hit_rate",
        "avg_answer_correctness",
        "route_match_rate",
        "avg_tutor_score",
    )

    for metric in tracked_metrics:
        current_value = summary.get(metric)
        baseline_value = baseline_summary.get(metric)
        if current_value is None or baseline_value in (None, 0):
            comparisons[metric] = {
                "current": current_value,
                "baseline": baseline_value,
                "delta": None,
                "relative_change": None,
                "regression": False,
            }
            continue

        delta = round(current_value - baseline_value, 3)
        relative_change = round((current_value - baseline_value) / baseline_value, 3)
        is_regression = relative_change < -REGRESSION_THRESHOLD
        comparisons[metric] = {
            "current": current_value,
            "baseline": baseline_value,
            "delta": delta,
            "relative_change": relative_change,
            "regression": is_regression,
        }
        if is_regression:
            regressions.append(metric)

    return {
        "baseline_path": baseline.get("artifact_path"),
        "threshold": REGRESSION_THRESHOLD,
        "comparisons": comparisons,
        "regressions": regressions,
        "passed": len(regressions) == 0,
    }


def build_promotable_baseline_document(
    summary: dict,
    *,
    dataset_version: str | None = None,
    eval_kind: str | None = None,
    promoted_from: str | None = None,
    notes: str | None = None,
) -> dict:
    """Стабильный JSON-блок для сохранения как defense/tutor baseline (с полем ``summary``)."""
    dv = dataset_version if dataset_version is not None else summary.get("dataset_version")
    subset = {k: summary[k] for k in _BASELINE_PROMOTABLE_SUMMARY_KEYS if k in summary}
    if dv is not None:
        subset.setdefault("dataset_version", dv)
    return {
        "baseline_schema_version": DEFENSE_BASELINE_SCHEMA_VERSION,
        "artifact_path": promoted_from,
        "eval_kind": eval_kind or "rag_eval",
        "dataset_version": dv,
        "summary": subset,
        "promotion_notes": notes,
    }


def serialize_baseline_report(document: dict) -> str:
    """Детерминированная сериализация baseline (для round-trip и CI diff)."""
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def promote_eval_artifact_to_baseline(
    source_eval_json_path: str | Path,
    baseline_target_path: str | Path,
    *,
    notes: str | None = None,
) -> dict:
    """Promotion: полный eval JSON → компактный baseline-файл next к прогону."""
    src = Path(source_eval_json_path)
    dest = Path(baseline_target_path)
    raw = json.loads(src.read_text(encoding="utf-8"))
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    ek_raw = raw.get("eval_kind")
    ek = ek_raw.strip() if isinstance(ek_raw, str) and ek_raw.strip() else "rag_eval"
    doc = build_promotable_baseline_document(
        summary,
        dataset_version=raw.get("dataset_version") or summary.get("dataset_version"),
        eval_kind=ek,
        promoted_from=str(src.resolve()),
        notes=notes,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(serialize_baseline_report(doc), encoding="utf-8")
    return {"baseline_path": str(dest.resolve()), "document": doc}


def build_graph_uplift_regression_gate_payload(
    eval_output: dict,
    *,
    gate_kind: str = "graph_uplift",
) -> dict:
    """Regression gate payload for graph uplift eval (mirrors defense gate pattern)."""
    uplift_gate = eval_output.get("uplift_gate")
    passed = True
    failed_checks: list[dict] = []
    if isinstance(uplift_gate, dict):
        passed = bool(uplift_gate.get("passed", True))
        failed_checks = [
            item for item in (uplift_gate.get("failed_checks") or []) if isinstance(item, dict)
        ]
    exit_code = 0 if passed else 2
    deltas = eval_output.get("deltas") if isinstance(eval_output.get("deltas"), dict) else {}
    return {
        "schema_version": DEFENSE_REGRESSION_GATE_SCHEMA_VERSION,
        "gate_kind": gate_kind,
        "passed": passed,
        "exit_code": exit_code,
        "failed_checks": failed_checks,
        "metric_deltas": [
            {"metric": key, "delta": value}
            for key, value in sorted(deltas.items())
            if value is not None
        ],
        "generation_id": eval_output.get("generation_id"),
        "dataset_version": eval_output.get("dataset_version"),
        "run_id": eval_output.get("run_id"),
    }


def build_defense_regression_gate_payload(
    eval_output: dict,
    *,
    gate_kind: str = "defense_eval",
) -> dict:
    """Итог regression-gate для CI: passed / exit_code / регрессии / дельты метрик."""
    comp = eval_output.get("baseline_comparison")
    summary = eval_output.get("summary") if isinstance(eval_output.get("summary"), dict) else {}
    passed = True
    regressions: list[str] = []
    baseline_ref: str | None = None
    deltas: list[dict] = []

    if isinstance(comp, dict):
        passed = bool(comp.get("passed", True))
        regressions = [str(x) for x in (comp.get("regressions") or [])]
        baseline_ref = comp.get("baseline_path")
        for metric, row in sorted((comp.get("comparisons") or {}).items()):
            if isinstance(row, dict) and row.get("delta") is not None:
                entry = {"metric": metric, **row}
                deltas.append(entry)

    exit_code = 0 if passed else 2

    return {
        "schema_version": DEFENSE_REGRESSION_GATE_SCHEMA_VERSION,
        "gate_kind": gate_kind,
        "passed": passed,
        "exit_code": exit_code,
        "regressions": regressions,
        "metric_deltas": deltas,
        "baseline_path": baseline_ref,
        "dataset_version": summary.get("dataset_version"),
        "cases": summary.get("cases"),
    }
