from typing import Optional

from llama_index.core.evaluation import (
    AnswerRelevancyEvaluator,
    ContextRelevancyEvaluator,
    FaithfulnessEvaluator,
)

from app.logging_config import setup_logging
from app.eval_helpers import _compute_answer_correctness
from app.provider import get_judge_llm
from app.models import QueryOptions, PipelineOverrides
from app.pipeline_profiler import run_profiled_query

logger = setup_logging()


def _safe_score(result):
    try:
        return float(result.score) if result.score is not None else None
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return None


def _extract_contexts(sources):
    contexts = []
    for src in sources:
        text = (src.get("text") or "").strip()
        if text:
            contexts.append(text)
    return contexts


def _build_evaluators():
    judge_llm = get_judge_llm()

    return {
        "answer_relevancy": AnswerRelevancyEvaluator(llm=judge_llm),
        "context_relevancy": ContextRelevancyEvaluator(llm=judge_llm),
        "faithfulness": FaithfulnessEvaluator(llm=judge_llm),
    }


def _evaluate_result(question: str, result: dict, evaluators: dict):
    answer = result["answer"]
    sources = result["sources"]
    contexts = _extract_contexts(sources)

    answer_rel = evaluators["answer_relevancy"].evaluate(
        query=question,
        response=answer,
        contexts=contexts,
    )

    context_rel = evaluators["context_relevancy"].evaluate(
        query=question,
        response=answer,
        contexts=contexts,
    )

    faithfulness = evaluators["faithfulness"].evaluate(
        query=question,
        response=answer,
        contexts=contexts,
    )

    return {
        "metrics": {
            "answer_relevancy": _safe_score(answer_rel),
            "context_relevancy": _safe_score(context_rel),
            "faithfulness": _safe_score(faithfulness),
        },
        "feedback": {
            "answer_relevancy": getattr(answer_rel, "feedback", None),
            "context_relevancy": getattr(context_rel, "feedback", None),
            "faithfulness": getattr(faithfulness, "feedback", None),
        },
    }


def compare_two_configs_with_eval(
    question: str,
    options: QueryOptions,
    config_a: PipelineOverrides,
    config_b: PipelineOverrides,
    reference_answer: Optional[str] = None,
):
    logger.info("compare_two_configs_with_eval started | question=%r", question)

    evaluators = _build_evaluators()

    result_a = run_profiled_query(question, options, config_a)
    result_b = run_profiled_query(question, options, config_b)

    eval_a = _evaluate_result(question, result_a, evaluators)
    eval_b = _evaluate_result(question, result_b, evaluators)

    profile_a = result_a["profile"]
    profile_b = result_b["profile"]

    metrics_a = eval_a["metrics"]
    metrics_b = eval_b["metrics"]
    metrics_a["answer_correctness"] = _compute_answer_correctness(
        result_a["answer"], reference_answer
    )
    metrics_b["answer_correctness"] = _compute_answer_correctness(
        result_b["answer"], reference_answer
    )

    output = {
        "question": question,
        "filters": {
            "folder": options.folder,
            "folder_rel": options.folder_rel,
            "file_name": options.file_name,
            "relative_path": options.relative_path,
        },
        "config_a": {
            "profile": profile_a,
            "quality": eval_a,
            "answer": result_a["answer"],
            "sources": result_a["sources"],
        },
        "config_b": {
            "profile": profile_b,
            "quality": eval_b,
            "answer": result_b["answer"],
            "sources": result_b["sources"],
        },
        "diff": {
            "latency": {
                "retrieval_ms_diff": round(profile_a["retrieval_ms"] - profile_b["retrieval_ms"], 3),
                "rerank_ms_diff": round(profile_a["rerank_ms"] - profile_b["rerank_ms"], 3),
                "synthesis_ms_diff": round(profile_a["synthesis_ms"] - profile_b["synthesis_ms"], 3),
                "total_ms_diff": round(profile_a["total_ms"] - profile_b["total_ms"], 3),
            },
            "nodes": {
                "retrieved_nodes_count_diff": profile_a["retrieved_nodes_count"] - profile_b["retrieved_nodes_count"],
                "postprocessed_nodes_count_diff": profile_a["postprocessed_nodes_count"] - profile_b["postprocessed_nodes_count"],
            },
            "quality": {
                "answer_relevancy_diff": (
                    round(metrics_a["answer_relevancy"] - metrics_b["answer_relevancy"], 3)
                    if metrics_a["answer_relevancy"] is not None and metrics_b["answer_relevancy"] is not None
                    else None
                ),
                "context_relevancy_diff": (
                    round(metrics_a["context_relevancy"] - metrics_b["context_relevancy"], 3)
                    if metrics_a["context_relevancy"] is not None and metrics_b["context_relevancy"] is not None
                    else None
                ),
                "faithfulness_diff": (
                    round(metrics_a["faithfulness"] - metrics_b["faithfulness"], 3)
                    if metrics_a["faithfulness"] is not None and metrics_b["faithfulness"] is not None
                    else None
                ),
                "answer_correctness_diff": (
                    round(
                        metrics_a["answer_correctness"]
                        - metrics_b["answer_correctness"],
                        3,
                    )
                    if metrics_a["answer_correctness"] is not None
                    and metrics_b["answer_correctness"] is not None
                    else None
                ),
                "context_precision_diff": None,
            },
        },
    }

    logger.info("compare_two_configs_with_eval completed")
    return output


def compare_tutor_eval_to_baseline(eval_output: dict, baseline_path: str):
    """Сравнить ``summary`` прогона tutor regression с baseline JSON (как у ``eval_results``)."""
    from app.eval_service import compare_tutor_eval_to_baseline as _impl

    return _impl(eval_output, baseline_path)


def compare(eval_output: dict, baseline_path: str):
    """Алиас для скриптов: ``compare_eval.compare(results, \"eval_results/tutor_baseline.json\")``."""
    return compare_tutor_eval_to_baseline(eval_output, baseline_path)
