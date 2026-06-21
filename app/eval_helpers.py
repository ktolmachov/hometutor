import time
from pathlib import Path
from statistics import mean

from app.config import get_settings
from app.models import QueryOptions

def _eval_max_workers() -> int:
    raw = (get_settings().eval_max_workers or "1").strip()
    try:
        n = int(raw)
    except ValueError:
        return 1
    return max(1, min(n, 32))


def _extract_contexts(sources):
    contexts = []
    for src in sources:
        text = (src.get("text") or "").strip()
        if text:
            contexts.append(text)
    return contexts


def _safe_score(result):
    try:
        return float(result.score) if result.score is not None else None
    except Exception as _exc:  # noqa: BLE001 - safe score extraction is robust against judge failures.
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return None


def _compute_retrieval_metrics(sources, expected_sources):
    """Recall@k, MRR, hit rate, precision@3 по expected_sources vs retrieved sources."""
    if not expected_sources:
        return None

    retrieved_paths = []
    for src in sources:
        path = src.get("relative_path") or src.get("file_name") or ""
        if path:
            retrieved_paths.append(path)

    expected_set = set(expected_sources)
    if not expected_set:
        return None

    hits = sum(1 for p in retrieved_paths if p in expected_set)
    recall_at_k = hits / len(expected_set) if expected_set else 0.0

    top3 = retrieved_paths[:3]
    hits_in_top_3 = sum(1 for p in top3 if p in expected_set)
    precision_at_k = hits_in_top_3 / 3

    rr = 0.0
    for rank, p in enumerate(retrieved_paths, start=1):
        if p in expected_set:
            rr = 1.0 / rank
            break

    hit = 1.0 if hits > 0 else 0.0

    return {
        "recall_at_k": round(recall_at_k, 3),
        "precision_at_k": round(precision_at_k, 3),
        "mrr": round(rr, 3),
        "hit_rate": hit,
    }


def _resolve_reference_text(item: dict) -> str | None:
    """Resolve reference text from ``reference`` or ``reference_answer`` (priority: reference)."""
    raw = item.get("reference")
    if raw is None:
        raw = item.get("reference_answer")
    if raw is None:
        return None
    text = str(raw).strip()
    return text if text else None


def _token_f1_similarity(generated: str, reference: str) -> float:
    """Deterministic token-F1 between generated and reference (truncated to 2000 chars each)."""
    gen = (generated or "")[:2000].lower().split()
    ref = (reference or "")[:2000].lower().split()
    if not gen and not ref:
        return 1.0
    if not gen or not ref:
        return 0.0

    gen_set = set(gen)
    ref_set = set(ref)
    overlap = len(gen_set & ref_set)
    if overlap == 0:
        return 0.0

    precision = overlap / len(gen_set)
    recall = overlap / len(ref_set)
    return 2.0 * precision * recall / (precision + recall)


def _compute_answer_correctness(answer: str, reference: str | None) -> float | None:
    """Token-F1 answer correctness; None when no reference (no penalty)."""
    if not reference:
        return None
    return round(_token_f1_similarity(answer, reference), 3)


def _normalize_eval_category(category: str | None) -> str:
    normalized = (category or "qa").strip().lower()
    if normalized == "cross_document":
        return "synthesis"
    return normalized


def _compute_synthesis_quality(answer: str, sources: list, category: str) -> dict | None:
    """Deterministic quality checks for overview/synthesis answers."""
    if category not in ("overview", "synthesis"):
        return None

    has_structure = any(
        marker in answer
        for marker in ("1.", "2.", "- ", "* ", "##", "###", "**")
    )
    unique_source_files = {
        (s.get("relative_path") or s.get("file_name") or "")
        for s in sources
    } - {""}
    multi_source = len(unique_source_files) >= 2
    sufficient_length = len(answer) >= 150
    has_source_refs = any(
        ref_marker in answer
        for ref_marker in ("документ", "файл", "источник", "document", "source")
    )

    score = sum([has_structure, multi_source, sufficient_length, has_source_refs]) / 4.0

    return {
        "has_structure": has_structure,
        "multi_source": multi_source,
        "sufficient_length": sufficient_length,
        "has_source_references": has_source_refs,
        "unique_source_files": len(unique_source_files),
        "answer_length": len(answer),
        "quality_score": round(score, 2),
    }


def _build_category_summary(results):
    category_groups = {}
    for item in results:
        category = item["category"]
        category_groups.setdefault(category, []).append(item)

    summary = {}
    for category, items in category_groups.items():
        answer_scores = [i["metrics"]["answer_relevancy"] for i in items if i["metrics"]["answer_relevancy"] is not None]
        context_scores = [i["metrics"]["context_relevancy"] for i in items if i["metrics"]["context_relevancy"] is not None]
        faithfulness_scores = [i["metrics"]["faithfulness"] for i in items if i["metrics"]["faithfulness"] is not None]
        route_matches = [1.0 if i["route_match"] else 0.0 for i in items]
        cat_summary: dict = {
            "cases": len(items),
            "avg_latency_sec": round(mean([i["latency_sec"] for i in items]), 3),
            "avg_answer_relevancy": round(mean(answer_scores), 3) if answer_scores else None,
            "avg_context_relevancy": round(mean(context_scores), 3) if context_scores else None,
            "avg_faithfulness": round(mean(faithfulness_scores), 3) if faithfulness_scores else None,
            "route_match_rate": round(mean(route_matches), 3) if route_matches else None,
        }
        synth_scores = [
            i["synthesis_quality"]["quality_score"]
            for i in items
            if i.get("synthesis_quality") and i["synthesis_quality"].get("quality_score") is not None
        ]
        if synth_scores:
            cat_summary["avg_synthesis_quality"] = round(mean(synth_scores), 3)
        summary[category] = cat_summary
    return summary


def _build_runtime_eval_link(summary: dict, runtime_metrics: dict | None) -> dict | None:
    if not runtime_metrics:
        return None

    warnings = []
    if (runtime_metrics.get("fallback_rate") or 0.0) > 0.2:
        warnings.append("high_fallback_rate")
    if (runtime_metrics.get("requests_without_sources_rate") or 0.0) > 0.2:
        warnings.append("high_no_sources_rate")
    if (runtime_metrics.get("empty_answers_rate") or 0.0) > 0.05:
        warnings.append("high_empty_answer_rate")
    if ((runtime_metrics.get("latency_ms") or {}).get("p95_total_answer_ms") or 0.0) > 5000:
        warnings.append("high_runtime_p95_latency")
    if (summary.get("route_match_rate") or 1.0) < 0.8:
        warnings.append("low_eval_route_match")
    if (summary.get("avg_faithfulness") or 1.0) < 0.8:
        warnings.append("low_eval_faithfulness")

    return {
        "runtime_metrics_window": runtime_metrics,
        "offline_eval_snapshot": {
            "dataset_version": summary.get("dataset_version"),
            "cases": summary.get("cases"),
            "avg_answer_relevancy": summary.get("avg_answer_relevancy"),
            "avg_context_relevancy": summary.get("avg_context_relevancy"),
            "avg_faithfulness": summary.get("avg_faithfulness"),
            "route_match_rate": summary.get("route_match_rate"),
            "p95_latency_sec": summary.get("p95_latency_sec"),
        },
        "warnings": warnings,
    }


def _build_tutor_query_options(inp: dict, case_id: str) -> QueryOptions:
    hl = inp.get("homework_level")
    homework_mode = bool(hl) or bool(inp.get("homework_mode"))
    assistance = hl or inp.get("assistance_level")
    session_id = inp.get("session_id") or f"eval_tutor_{case_id}"
    qm = (inp.get("query_mode") or "tutor").strip().lower()
    followup = inp.get("followup_context") or inp.get("history")

    return QueryOptions(
        folder=inp.get("folder"),
        folder_rel=inp.get("folder_rel"),
        file_name=inp.get("file_name"),
        relative_path=inp.get("relative_path"),
        topic=inp.get("topic"),
        logical_folder=inp.get("logical_folder"),
        file=inp.get("file"),
        homework_mode=homework_mode,
        assistance_level=assistance if homework_mode else None,
        study_mode=bool(inp.get("study_mode")),
        followup_context=followup,
        session_id=session_id,
        query_mode=qm,
    )


def _tutor_expected_rubric(answer: str, expected: dict | None) -> dict | None:
    """Лёгкие детерминированные проверки по полю expected (дополнение к LLM-метрикам)."""
    if not expected:
        return None

    checks: dict = {}
    score_parts: list[float] = []

    if expected.get("contains_solution") is False:
        no_code = "```" not in answer
        checks["no_code_block"] = no_code
        score_parts.append(1.0 if no_code else 0.0)

    if expected.get("contains_structure") is False:
        has_structure = any(
            marker in answer
            for marker in ("1.", "2.", "Шаг", "##", "###", "**")
        )
        checks["no_explicit_structure"] = not has_structure
        score_parts.append(0.0 if has_structure else 1.0)

    qc = expected.get("question_contains")
    if isinstance(qc, str) and qc.strip():
        contained = qc.lower() in answer.lower()
        checks["question_contains_in_answer"] = contained
        score_parts.append(1.0 if contained else 0.0)

    if not score_parts:
        return None

    return {
        "checks": checks,
        "score": round(mean(score_parts), 3),
    }


def _aggregate_tutor_score(metrics: dict, rubric: dict | None) -> float | None:
    m_vals = [v for v in metrics.values() if v is not None]
    if rubric and rubric.get("score") is not None:
        m_vals.append(float(rubric["score"]))
    if not m_vals:
        return None
    return round(mean(m_vals), 3)


def _compute_eval_summary(results: list[dict], dataset_version: str) -> dict:
    answer_scores = [
        r["metrics"]["answer_relevancy"]
        for r in results
        if r["metrics"]["answer_relevancy"] is not None
    ]
    context_scores = [
        r["metrics"]["context_relevancy"]
        for r in results
        if r["metrics"]["context_relevancy"] is not None
    ]
    faithfulness_scores = [
        r["metrics"]["faithfulness"]
        for r in results
        if r["metrics"]["faithfulness"] is not None
    ]

    retrieval_recall = [
        r["retrieval_metrics"]["recall_at_k"]
        for r in results
        if r.get("retrieval_metrics")
    ]
    retrieval_mrr = [
        r["retrieval_metrics"]["mrr"]
        for r in results
        if r.get("retrieval_metrics")
    ]
    retrieval_hit = [
        r["retrieval_metrics"]["hit_rate"]
        for r in results
        if r.get("retrieval_metrics")
    ]
    retrieval_precision = [
        r["retrieval_metrics"]["precision_at_k"]
        for r in results
        if r.get("retrieval_metrics")
    ]
    answer_correctness = [
        r["metrics"]["answer_correctness"]
        for r in results
        if r["metrics"].get("answer_correctness") is not None
    ]

    latencies = [r["latency_sec"] for r in results]
    latencies_sorted = sorted(latencies)
    n = len(latencies_sorted)

    def _percentile(p: float) -> float | None:
        if not latencies_sorted:
            return None
        idx = int(round(p * (n - 1)))
        return round(latencies_sorted[idx], 3)

    return {
        "cases": len(results),
        "dataset_version": dataset_version,
        "avg_latency_sec": round(mean(latencies), 3) if results else None,
        "p50_latency_sec": _percentile(0.50),
        "p95_latency_sec": _percentile(0.95),
        "avg_answer_relevancy": round(mean(answer_scores), 3) if answer_scores else None,
        "avg_context_relevancy": round(mean(context_scores), 3) if context_scores else None,
        "avg_faithfulness": round(mean(faithfulness_scores), 3) if faithfulness_scores else None,
        "avg_retrieval_recall_at_k": round(mean(retrieval_recall), 3) if retrieval_recall else None,
        "avg_retrieval_precision_at_k": round(mean(retrieval_precision), 3) if retrieval_precision else None,
        "avg_retrieval_mrr": round(mean(retrieval_mrr), 3) if retrieval_mrr else None,
        "avg_retrieval_hit_rate": round(mean(retrieval_hit), 3) if retrieval_hit else None,
        "avg_answer_correctness": round(mean(answer_correctness), 3) if answer_correctness else None,
        "route_match_rate": round(mean([1.0 if r["route_match"] else 0.0 for r in results]), 3) if results else None,
    }


def _compute_tutor_summary(results: list[dict], completed: list[dict], dataset_version: str) -> dict:
    answer_scores = [
        r["metrics"]["answer_relevancy"]
        for r in completed
        if r["metrics"]["answer_relevancy"] is not None
    ]
    context_scores = [
        r["metrics"]["context_relevancy"]
        for r in completed
        if r["metrics"]["context_relevancy"] is not None
    ]
    faithfulness_scores = [
        r["metrics"]["faithfulness"]
        for r in completed
        if r["metrics"]["faithfulness"] is not None
    ]
    aggregate_scores = [r["score"] for r in completed if r.get("score") is not None]

    latencies = [r["latency_sec"] for r in completed]
    latencies_sorted = sorted(latencies)
    n = len(latencies_sorted)

    def _percentile(p: float) -> float | None:
        if not latencies_sorted:
            return None
        idx = int(round(p * (n - 1)))
        return round(latencies_sorted[idx], 3)

    return {
        "cases": len(results),
        "cases_completed": len(completed),
        "cases_skipped": len(results) - len(completed),
        "dataset_version": dataset_version,
        "avg_latency_sec": round(mean(latencies), 3) if latencies else None,
        "p50_latency_sec": _percentile(0.50),
        "p95_latency_sec": _percentile(0.95),
        "avg_answer_relevancy": round(mean(answer_scores), 3) if answer_scores else None,
        "avg_context_relevancy": round(mean(context_scores), 3) if context_scores else None,
        "avg_faithfulness": round(mean(faithfulness_scores), 3) if faithfulness_scores else None,
        "avg_tutor_score": round(mean(aggregate_scores), 3) if aggregate_scores else None,
        "route_match_rate": round(
            mean([1.0 if r.get("route_match") else 0.0 for r in completed]),
            3,
        )
        if completed
        else None,
    }
