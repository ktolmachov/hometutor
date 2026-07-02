"""Home RAG Product Baseline v1.

This baseline measures Home RAG as a learning product with a fixed baseline
model. It intentionally produces a scorecard instead of treating every miss as
a model-selection failure.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (ROOT, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import home_rag_integration_gate_v1 as integration_gate  # noqa: E402


DEFAULT_CASES_PATH = ROOT / "eval_data" / "home_rag_product_baseline" / "home_rag_product_baseline_v1.json"
DEFAULT_HOME = Path(r"D:\AI\home_rag_product_baseline_v1")
DEFAULT_REPORT_DIR = Path(r"D:\AI\logs")
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:8080/v1"
DEFAULT_LLM_MODEL = "qwopus3.6-35b-a3b-v1-mtp"
DEFAULT_EMBED_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_EMBED_MODEL = "text-embedding-qwen3-embedding-0.6b"


@dataclass
class BaselineConfig:
    cases_path: Path
    home: Path
    report_dir: Path
    llm_base_url: str
    llm_model: str
    embed_base_url: str
    embed_model: str
    preflight_only: bool
    skip_ingest: bool
    reset_home: bool
    timeout_sec: int


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _contains_all(text: object, needles: list[Any]) -> bool:
    return integration_gate._contains_all(text, needles)


def _validate_cases(doc: dict[str, Any]) -> list[str]:
    errors = integration_gate._validate_cases(doc)
    baseline = doc.get("baseline") or {}
    if baseline.get("baseline_model") != DEFAULT_LLM_MODEL:
        errors.append(f"baseline_model must remain {DEFAULT_LLM_MODEL}")
    for case in doc.get("cases") or []:
        metrics = case.get("metrics") or []
        if not metrics:
            errors.append(f"case {case.get('id')} missing metrics")
    return errors


def _safe_reset_home(path: Path) -> None:
    resolved = path.resolve()
    if "home_rag_product_baseline_v1" not in str(resolved).casefold():
        raise RuntimeError(f"Refusing to reset non-baseline HOME_RAG_HOME: {resolved}")
    if resolved.exists():
        import shutil

        shutil.rmtree(resolved)


def _to_gate_config(config: BaselineConfig) -> integration_gate.GateConfig:
    return integration_gate.GateConfig(
        cases_path=config.cases_path,
        home=config.home,
        report_dir=config.report_dir,
        llm_base_url=config.llm_base_url,
        llm_model=config.llm_model,
        embed_base_url=config.embed_base_url,
        embed_model=config.embed_model,
        preflight_only=config.preflight_only,
        skip_ingest=config.skip_ingest,
        reset_home=config.reset_home,
        timeout_sec=config.timeout_sec,
    )


def _prepare_env(config: BaselineConfig) -> None:
    integration_gate._prepare_env(_to_gate_config(config))
    import os

    os.environ["COLLECTION_NAME"] = "home_rag_product_baseline_v1_chunks"
    os.environ["SUMMARY_COLLECTION_NAME"] = "home_rag_product_baseline_v1_summaries"
    os.environ["SIMILARITY_TOP_K"] = "10"
    os.environ["RETRIEVAL_MODE"] = "hybrid"
    os.environ["RAG_PROFILE"] = "quality"


def _bind_config_module(config: BaselineConfig) -> None:
    integration_gate._bind_config_module(_to_gate_config(config))
    import os

    os.environ["COLLECTION_NAME"] = "home_rag_product_baseline_v1_chunks"
    os.environ["SUMMARY_COLLECTION_NAME"] = "home_rag_product_baseline_v1_summaries"
    os.environ["SIMILARITY_TOP_K"] = "10"


def _score_metric(metric: str, case: dict[str, Any], row: dict[str, Any]) -> bool:
    answer = str(row.get("answer") or "")
    user_value_min = int(case.get("user_value_min_chars") or 50)
    refused = bool(row.get("refusal_like"))
    checks = {
        "retrieval_quality": bool(row.get("source_ok") and row.get("sources_ok")),
        "answer_grounding": bool(row.get("include_ok") and row.get("include_any_ok") and row.get("exclude_ok")),
        "citation_accuracy": bool(row.get("citation_present_ok") and row.get("citation_source_id_ok")),
        "quiz_validity": bool(
            row.get("include_any_ok")
            and row.get("exclude_ok")
            and row.get("citation_source_id_ok")
            and not refused
        ),
        "long_doc_stability": bool(row.get("source_ok") and row.get("include_any_ok") and row.get("exclude_ok")),
        "refusal_precision": bool(row.get("include_any_ok") and row.get("exclude_ok") and row.get("no_evidence_no_citation_ok")),
        "user_value": bool(len(answer.strip()) >= user_value_min and row.get("include_any_ok") and row.get("exclude_ok")),
    }
    return checks.get(metric, False)


def _looks_like_refusal(answer: object) -> bool:
    text = str(answer or "").casefold()
    markers = (
        "insufficient",
        "not enough information",
        "not contain",
        "does not contain",
        "not available",
        "недостаточно информации",
        "недостаточно данных",
        "не содержит",
        "не приведены",
        "не найден",
    )
    return any(marker in text for marker in markers)


def _evaluate_product_case(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    row = integration_gate._evaluate_case(case, result)
    metrics = list(case.get("metrics") or [])
    row["refusal_like"] = _looks_like_refusal(row.get("answer"))
    metric_results = {metric: _score_metric(metric, case, row) for metric in metrics}
    score = (sum(1 for ok in metric_results.values() if ok) / len(metric_results)) if metric_results else 0.0
    row["category"] = case.get("category") or case.get("type")
    row["metrics"] = metric_results
    row["score"] = round(score, 4)
    row["status"] = "PASS" if score >= 0.85 else "WATCH" if score >= 0.7 else "NEEDS_WORK"
    return row


def _query_options(payload: dict[str, Any]):
    return integration_gate._query_options(payload)


def _run_cases(doc: dict[str, Any]) -> list[dict[str, Any]]:
    from app.query_service import answer_question

    rows: list[dict[str, Any]] = []
    for case in doc.get("cases") or []:
        cid = case.get("id")
        print(f"Running Product Baseline case: {cid}", flush=True)
        started = time.perf_counter()
        try:
            result = answer_question(str(case["question"]), _query_options(case.get("options") or {}))
            row = _evaluate_product_case(case, result)
            row["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        except Exception as exc:  # noqa: BLE001 - reports must capture baseline gaps.
            row = {
                "id": cid,
                "type": case.get("type"),
                "category": case.get("category"),
                "status": "ERROR",
                "score": 0.0,
                "error": type(exc).__name__,
                "message": str(exc),
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        rows.append(row)
        print(f"{cid}: {row['status']} score={row.get('score')}", flush=True)
    return rows


def _aggregate_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, list[float]] = {}
    by_metric: dict[str, list[float]] = {}
    for row in rows:
        by_category.setdefault(str(row.get("category") or "uncategorized"), []).append(float(row.get("score") or 0.0))
        for metric, ok in (row.get("metrics") or {}).items():
            by_metric.setdefault(str(metric), []).append(1.0 if ok else 0.0)

    def avg(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    overall = avg([float(row.get("score") or 0.0) for row in rows])
    status = "ACCEPTED_BASELINE" if overall >= 0.85 else "WATCH_BASELINE" if overall >= 0.7 else "NEEDS_WORK"
    return {
        "overall_score": overall,
        "baseline_status": status,
        "category_scores": {key: avg(values) for key, values in sorted(by_category.items())},
        "metric_scores": {key: avg(values) for key, values in sorted(by_metric.items())},
        "cases_pass": sum(1 for row in rows if row.get("status") == "PASS"),
        "cases_watch": sum(1 for row in rows if row.get("status") == "WATCH"),
        "cases_needs_work": sum(1 for row in rows if row.get("status") == "NEEDS_WORK"),
        "cases_error": sum(1 for row in rows if row.get("status") == "ERROR"),
    }


def _write_reports(config: BaselineConfig, summary: dict[str, Any]) -> dict[str, str]:
    config.report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base = config.report_dir / f"home_rag_product_baseline_v1_{stamp}"
    json_path = base.with_suffix(".json")
    csv_path = base.with_suffix(".csv")
    md_path = base.with_suffix(".md")
    report_paths = {"json": str(json_path), "csv": str(csv_path), "md": str(md_path)}
    summary["reports"] = report_paths
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = summary.get("rows") or []
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = ["id", "type", "category", "status", "score", "source_count", "latency_ms", "answer_preview"]
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    scorecard = summary.get("scorecard") or {}
    lines = [
        "# Home RAG Product Baseline v1",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Baseline model: `{summary.get('llm_model')}`",
        f"Overall score: `{scorecard.get('overall_score', 0)}`",
        f"Baseline status: `{scorecard.get('baseline_status', 'UNKNOWN')}`",
        "",
        "## Metric Scores",
        "",
        "| Metric | Score |",
        "|---|---:|",
    ]
    for key, value in (scorecard.get("metric_scores") or {}).items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "## Cases",
        "",
        "| Case | Category | Status | Score | Sources | Latency ms |",
        "|---|---|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('id')} | {row.get('category')} | {row.get('status')} | {row.get('score')} | {row.get('source_count', 0)} | {row.get('latency_ms', '')} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_paths


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Home RAG Product Baseline v1.")
    parser.add_argument("--cases-path", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--llm-base-url", default=DEFAULT_LLM_BASE_URL)
    parser.add_argument("--llm-model", default=DEFAULT_LLM_MODEL)
    parser.add_argument("--embed-base-url", default=DEFAULT_EMBED_BASE_URL)
    parser.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    parser.add_argument("--timeout-sec", type=int, default=10)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--reset-home", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config = BaselineConfig(
        cases_path=args.cases_path,
        home=args.home,
        report_dir=args.report_dir,
        llm_base_url=args.llm_base_url,
        llm_model=args.llm_model,
        embed_base_url=args.embed_base_url,
        embed_model=args.embed_model,
        preflight_only=args.preflight_only,
        skip_ingest=args.skip_ingest,
        reset_home=args.reset_home,
        timeout_sec=args.timeout_sec,
    )

    doc = _read_json(config.cases_path)
    errors = _validate_cases(doc)
    if errors:
        for error in errors:
            print(f"HOME_RAG_PRODUCT_BASELINE_PREFLIGHT_ERROR: {error}", file=sys.stderr)
        return 2

    if config.reset_home:
        _safe_reset_home(config.home)
    _prepare_env(config)
    written = integration_gate._write_corpus(_to_gate_config(config), doc)

    summary: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "mode": "preflight" if config.preflight_only else "model",
        "home": str(config.home.resolve()),
        "cases_path": str(config.cases_path.resolve()),
        "documents_written": written,
        "cases_total": len(doc.get("cases") or []),
        "baseline": doc.get("baseline") or {},
        "llm_model": config.llm_model,
        "embed_model": config.embed_model,
        "checks": {"case_json": "PASS", "corpus_written": "PASS"},
    }

    if config.preflight_only:
        summary["rows"] = []
        summary["scorecard"] = {}
        summary["reports"] = _write_reports(config, summary)
        print(f"Home RAG product baseline corpus written: {config.home / 'data'}")
        print("HOME_RAG_PRODUCT_BASELINE_V1_PREFLIGHT=PASS")
        return 0

    summary["tiktoken_fallback_installed"] = integration_gate._install_tiktoken_fallback_if_needed()
    try:
        summary["llm_probe"] = integration_gate._probe_models(config.llm_base_url, config.llm_model, config.timeout_sec)
        summary["embed_probe"] = integration_gate._probe_models(config.embed_base_url, config.embed_model, config.timeout_sec)
    except (TimeoutError, URLError, OSError) as exc:
        summary["runtime_probe_error"] = f"{type(exc).__name__}: {exc}"
        summary["rows"] = []
        summary["scorecard"] = {"overall_score": 0.0, "baseline_status": "BLOCKED_RUNTIME_ENDPOINT"}
        summary["reports"] = _write_reports(config, summary)
        print("HOME_RAG_PRODUCT_BASELINE_V1=BLOCKED_RUNTIME_ENDPOINT")
        return 3

    _bind_config_module(config)
    if not config.skip_ingest:
        integration_gate._run_ingest()

    try:
        rows = _run_cases(doc)
    except ImportError as exc:
        summary["runtime_import_error"] = f"{type(exc).__name__}: {exc}"
        summary["rows"] = []
        summary["scorecard"] = {"overall_score": 0.0, "baseline_status": "BLOCKED_RUNTIME_IMPORT"}
        summary["reports"] = _write_reports(config, summary)
        print("HOME_RAG_PRODUCT_BASELINE_V1=BLOCKED_RUNTIME_IMPORT")
        return 4

    summary["rows"] = rows
    summary["scorecard"] = _aggregate_scores(rows)
    summary["reports"] = _write_reports(config, summary)
    print(f"Report JSON: {summary['reports']['json']}")
    print(f"HOME_RAG_PRODUCT_BASELINE_V1={summary['scorecard']['baseline_status']}")
    return 1 if summary["scorecard"].get("cases_error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
