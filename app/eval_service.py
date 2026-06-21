import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from llama_index.core.evaluation import (
    AnswerRelevancyEvaluator,
    ContextRelevancyEvaluator,
    FaithfulnessEvaluator,
)

from app.config import BASE_DIR, get_settings
from app.logging_config import setup_logging
from app.metrics import summarize_metrics_store
from app.models import QueryOptions
from app.provider import get_judge_llm
from app.query_service import answer_question

# Re-expose all symbols for backwards-compatibility
from app.eval_helpers import (
    _eval_max_workers,
    _extract_contexts,
    _safe_score,
    _compute_retrieval_metrics,
    _resolve_reference_text,
    _token_f1_similarity,
    _compute_answer_correctness,
    _normalize_eval_category,
    _compute_synthesis_quality,
    _build_category_summary,
    _build_runtime_eval_link,
    _build_tutor_query_options,
    _tutor_expected_rubric,
    _aggregate_tutor_score,
    _compute_eval_summary,
    _compute_tutor_summary,
)

from app.eval_baseline import (
    _load_baseline,
    _compare_to_baseline,
    build_promotable_baseline_document,
    serialize_baseline_report,
    promote_eval_artifact_to_baseline,
    build_defense_regression_gate_payload,
    REGRESSION_THRESHOLD,
    DEFENSE_BASELINE_SCHEMA_VERSION,
    DEFENSE_REGRESSION_GATE_SCHEMA_VERSION,
    _BASELINE_PROMOTABLE_SUMMARY_KEYS,
)

logger = setup_logging()

EVAL_DATA_DIR = BASE_DIR / "eval_data"
EVAL_RESULTS_DIR = BASE_DIR / "eval_results"
DEFAULT_DATASET_VERSION = "v1"


def load_eval_questions(filename: str = "eval_questions.json"):
    path = EVAL_DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Eval file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _dataset_version(dataset: list[dict], filename: str) -> str:
    if dataset and dataset[0].get("dataset_version"):
        return str(dataset[0]["dataset_version"])
    return f"{Path(filename).stem}:{DEFAULT_DATASET_VERSION}"


def build_evaluators():
    judge_llm = get_judge_llm()

    return {
        "answer_relevancy": AnswerRelevancyEvaluator(llm=judge_llm),
        "context_relevancy": ContextRelevancyEvaluator(llm=judge_llm),
        "faithfulness": FaithfulnessEvaluator(llm=judge_llm),
    }


def _run_single_eval_case(item: dict, evaluators: dict | None = None) -> dict:
    """Один кейс eval: RAG + три judge-метрики. При ``evaluators is None`` создаёт свой набор."""
    ev = evaluators if evaluators is not None else build_evaluators()

    case_id = item["id"]
    question = item["question"]
    expected_category = _normalize_eval_category(item.get("category"))

    options = QueryOptions(
        folder=item.get("folder"),
        folder_rel=item.get("folder_rel"),
        file_name=item.get("file_name"),
        relative_path=item.get("relative_path"),
    )

    logger.info(
        "Eval case started | id=%s | question=%r | folder_rel=%r | relative_path=%r",
        case_id,
        question,
        options.folder_rel,
        options.relative_path,
    )

    started = time.perf_counter()

    rag_result = answer_question(question, options)
    answer = rag_result["answer"]
    sources = rag_result["sources"]
    contexts = _extract_contexts(sources)

    latency_sec = time.perf_counter() - started

    answer_rel = ev["answer_relevancy"].evaluate(
        query=question,
        response=answer,
        contexts=contexts,
    )

    context_rel = ev["context_relevancy"].evaluate(
        query=question,
        response=answer,
        contexts=contexts,
    )

    faithfulness = ev["faithfulness"].evaluate(
        query=question,
        response=answer,
        contexts=contexts,
    )

    expected_sources = item.get("source_documents") or item.get("expected_sources") or []
    retrieval_metrics = _compute_retrieval_metrics(sources, expected_sources)

    synthesis_quality = _compute_synthesis_quality(answer, sources, expected_category)

    reference_text = _resolve_reference_text(item)
    answer_correctness = _compute_answer_correctness(answer, reference_text)

    case_result = {
        "id": case_id,
        "question": question,
        "category": expected_category,
        "reference_answer": reference_text,
        "expected_sources": expected_sources,
        "eval_criteria": item.get("eval_criteria"),
        "filters": {
            "folder": options.folder,
            "folder_rel": options.folder_rel,
            "file_name": options.file_name,
            "relative_path": options.relative_path,
        },
        "latency_sec": round(latency_sec, 3),
        "answer": answer,
        "sources_count": len(sources),
        "sources": sources,
        "metrics": {
            "answer_relevancy": _safe_score(answer_rel),
            "context_relevancy": _safe_score(context_rel),
            "faithfulness": _safe_score(faithfulness),
            "answer_correctness": answer_correctness,
        },
        "predicted_query_type": rag_result.get("debug", {}).get("query_type"),
        "route_match": _normalize_eval_category(rag_result.get("debug", {}).get("query_type")) == expected_category,
        "retrieval_metrics": retrieval_metrics,
        "synthesis_quality": synthesis_quality,
        "feedback": {
            "answer_relevancy": getattr(answer_rel, "feedback", None),
            "context_relevancy": getattr(context_rel, "feedback", None),
            "faithfulness": getattr(faithfulness, "feedback", None),
        },
    }

    logger.info(
        "Eval case completed | id=%s | latency=%.3fs | sources=%s | answer_rel=%s | context_rel=%s | faithfulness=%s",
        case_id,
        latency_sec,
        len(sources),
        case_result["metrics"]["answer_relevancy"],
        case_result["metrics"]["context_relevancy"],
        case_result["metrics"]["faithfulness"],
    )

    return case_result


def run_eval(filename: str = "eval_questions.json"):
    dataset = load_eval_questions(filename)
    dataset_version = _dataset_version(dataset, filename)
    settings = get_settings()
    baseline_path = settings.eval_baseline_json
    baseline = _load_baseline(baseline_path)
    runtime_metrics = summarize_metrics_store()

    EVAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    max_workers = _eval_max_workers()
    logger.info("Eval started | cases=%s | file=%s | workers=%s", len(dataset), filename, max_workers)
    if max_workers <= 1:
        shared_evaluators = build_evaluators()
        results = [_run_single_eval_case(item, evaluators=shared_evaluators) for item in dataset]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            results = list(pool.map(_run_single_eval_case, dataset))

    summary = _compute_eval_summary(results, dataset_version)

    ts = int(time.time())
    output_path = EVAL_RESULTS_DIR / f"eval_results_{ts}.json"
    eval_output_json = settings.eval_output_json
    if eval_output_json:
        output_path = Path(eval_output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        EVAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    output = {
        "artifact_version": 2,
        "created_at": ts,
        "artifact_path": str(output_path),
        "dataset_version": dataset_version,
        "eval_max_workers": max_workers,
        "baseline_path": baseline_path,
        "summary": summary,
        "baseline_comparison": _compare_to_baseline(summary, baseline),
        "runtime_eval_link": _build_runtime_eval_link(summary, runtime_metrics),
        "category_summary": _build_category_summary(results),
        "results": results,
    }

    output["regression_gate"] = build_defense_regression_gate_payload(output, gate_kind="defense_eval")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info("Eval completed | output=%s | summary=%s", output_path, summary)

    return output_path, output


def _resolve_eval_data_path(filename: str) -> Path:
    p = Path(filename)
    if p.is_absolute():
        return p
    return EVAL_DATA_DIR / filename


def load_tutor_regression(filename: str = "tutor_regression.json") -> dict:
    path = _resolve_eval_data_path(filename)
    if not path.exists():
        raise FileNotFoundError(f"Tutor regression file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _run_single_tutor_case(case: dict, evaluators: dict | None = None) -> dict:
    """Один кейс tutor regression: RAG + judge-метрики + опциональный rubric по expected."""
    case_id = case.get("id", "unknown")
    inp = case.get("input") or {}
    question = (inp.get("question") or "").strip()
    expected = case.get("expected")
    category = _normalize_eval_category(case.get("category") or "tutor")

    if not question:
        return {
            "id": case_id,
            "status": "skipped",
            "reason": "no_question_in_input",
            "category": category,
            "score": None,
            "metrics": {
                "answer_relevancy": None,
                "context_relevancy": None,
                "faithfulness": None,
            },
        }

    ev = evaluators if evaluators is not None else build_evaluators()

    options = _build_tutor_query_options(inp, str(case_id))

    logger.info(
        "Tutor eval case started | id=%s | question=%r | session_id=%r | homework_mode=%s",
        case_id,
        question,
        options.session_id,
        options.homework_mode,
    )

    started = time.perf_counter()
    rag_result = answer_question(question, options)
    answer = rag_result["answer"]
    sources = rag_result["sources"]
    contexts = _extract_contexts(sources)
    latency_sec = time.perf_counter() - started

    answer_rel = ev["answer_relevancy"].evaluate(
        query=question,
        response=answer,
        contexts=contexts,
    )
    context_rel = ev["context_relevancy"].evaluate(
        query=question,
        response=answer,
        contexts=contexts,
    )
    faithfulness = ev["faithfulness"].evaluate(
        query=question,
        response=answer,
        contexts=contexts,
    )

    metrics = {
        "answer_relevancy": _safe_score(answer_rel),
        "context_relevancy": _safe_score(context_rel),
        "faithfulness": _safe_score(faithfulness),
    }
    rubric = _tutor_expected_rubric(answer, expected if isinstance(expected, dict) else None)
    score = _aggregate_tutor_score(metrics, rubric)

    case_result = {
        "id": case_id,
        "status": "completed",
        "category": category,
        "question": question,
        "latency_sec": round(latency_sec, 3),
        "score": score,
        "metrics": metrics,
        "expected_rubric": rubric,
        "expected": expected,
        "answer": answer,
        "sources_count": len(sources),
        "sources": sources,
        "predicted_query_type": rag_result.get("debug", {}).get("query_type"),
        "route_match": _normalize_eval_category(rag_result.get("debug", {}).get("query_type")) == category,
        "feedback": {
            "answer_relevancy": getattr(answer_rel, "feedback", None),
            "context_relevancy": getattr(context_rel, "feedback", None),
            "faithfulness": getattr(faithfulness, "feedback", None),
        },
    }

    logger.info(
        "Tutor eval case completed | id=%s | score=%s | answer_rel=%s",
        case_id,
        score,
        metrics["answer_relevancy"],
    )

    return case_result


def compare_tutor_eval_to_baseline(eval_output: dict, baseline_path: str) -> dict | None:
    """Сравнение summary tutor-прогона с baseline."""
    baseline = _load_baseline(baseline_path)
    summary = eval_output.get("summary") or {}
    return _compare_to_baseline(summary, baseline)


def run_tutor_regression(
    dataset_path: str = "tutor_regression.json",
    baseline_path: str | None = None,
):
    """Прогон tutor regression: только кейсы с ``input.question``; остальные — skipped."""
    data = load_tutor_regression(dataset_path)
    test_cases = data.get("test_cases") or []
    dataset_version = str(data.get("version") or Path(dataset_path).stem)

    settings = get_settings()
    resolved_baseline = baseline_path or settings.eval_tutor_baseline_json
    baseline = _load_baseline(resolved_baseline)
    runtime_metrics = summarize_metrics_store()

    EVAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    max_workers = _eval_max_workers()
    logger.info(
        "Tutor regression started | cases=%s | file=%s | workers=%s",
        len(test_cases),
        dataset_path,
        max_workers,
    )

    if max_workers <= 1:
        shared_evaluators = build_evaluators()
        results = [_run_single_tutor_case(c, evaluators=shared_evaluators) for c in test_cases]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            results = list(pool.map(_run_single_tutor_case, test_cases))

    completed = [r for r in results if r.get("status") == "completed"]

    summary = _compute_tutor_summary(results, completed, dataset_version)

    ts = int(time.time())
    output_path = EVAL_RESULTS_DIR / f"tutor_regression_{ts}.json"
    eval_output_json = settings.eval_tutor_output_json
    if eval_output_json:
        output_path = Path(eval_output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "artifact_version": 1,
        "eval_kind": "tutor_regression",
        "created_at": ts,
        "artifact_path": str(output_path),
        "dataset_version": dataset_version,
        "dataset_file": str(_resolve_eval_data_path(dataset_path)),
        "eval_max_workers": max_workers,
        "baseline_path": resolved_baseline,
        "summary": summary,
        "baseline_comparison": _compare_to_baseline(summary, baseline),
        "runtime_eval_link": _build_runtime_eval_link(summary, runtime_metrics),
        "category_summary": _build_category_summary(
            [
                {
                    **r,
                    "metrics": r.get("metrics")
                    or {
                        "answer_relevancy": None,
                        "context_relevancy": None,
                        "faithfulness": None,
                    },
                }
                for r in results
                if r.get("status") == "completed"
            ]
        ),
        "results": results,
    }

    output["regression_gate"] = build_defense_regression_gate_payload(output, gate_kind="tutor_regression")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info("Tutor regression completed | output=%s | summary=%s", output_path, summary)

    return output_path, output
