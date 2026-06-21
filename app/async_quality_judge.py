"""Background (post-response) LLM judge for a sampled fraction of /ask requests."""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from fastapi import BackgroundTasks

from app.config import get_settings
from app.eval_service import _extract_contexts, _safe_score, build_evaluators
from app.guardrails import redact_sensitive_text
from app.logging_config import log_event, setup_logging
from app.metrics import record_quality_judge

logger = setup_logging()

_MAX_SOURCES = 10
_MAX_SNIPPET_LEN = 2000


def _snapshot_sources_for_judge(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for src in sources[:_MAX_SOURCES]:
        if not isinstance(src, dict):
            continue
        text = (src.get("text") or "").strip()
        if len(text) > _MAX_SNIPPET_LEN:
            text = text[:_MAX_SNIPPET_LEN]
        out.append(
            {
                "relative_path": src.get("relative_path"),
                "file_name": src.get("file_name"),
                "text": text,
            }
        )
    return out


def schedule_async_quality_judge_if_sampled(
    *,
    background_tasks: BackgroundTasks,
    request_id: str,
    question: str,
    answer: str,
    sources: list[dict[str, Any]],
    query_type: str | None,
) -> None:
    """After HTTP response, optionally run LlamaIndex evaluators and record scores."""
    settings = get_settings()
    if not settings.enable_async_quality_judge:
        return
    if settings.async_quality_judge_sample_rate <= 0:
        return
    if random.random() >= settings.async_quality_judge_sample_rate:
        return
    if not (settings.openai_api_key or "").strip():
        return
    if not (answer or "").strip():
        return

    snap = _snapshot_sources_for_judge(sources)
    contexts = _extract_contexts(snap)
    if not contexts:
        log_event(
            logger,
            logging.DEBUG,
            "async_quality_judge_skipped",
            request_id=request_id,
            reason="no_context_snippets",
        )
        return

    background_tasks.add_task(
        run_async_quality_judge_task,
        request_id,
        question,
        answer,
        snap,
        (query_type or "unknown").strip() or "unknown",
    )


def run_async_quality_judge_task(
    request_id: str,
    question: str,
    answer: str,
    sources: list[dict[str, Any]],
    query_type: str,
) -> None:
    started = time.perf_counter()
    settings = get_settings()
    model = settings.eval_judge_llm or settings.llm_model

    def _finish(*, scores: dict[str, float] | None = None, error: str | None = None) -> None:
        latency_ms = (time.perf_counter() - started) * 1000
        record_quality_judge(
            request_id=request_id,
            scores=scores or {},
            model=model,
            query_type=query_type,
            latency_ms=round(latency_ms, 3),
            error=error,
        )

    try:
        contexts = _extract_contexts(sources)
        if not contexts:
            _finish(error="no_context")
            return

        evaluators = build_evaluators()
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

        raw_scores = {
            "answer_relevancy": _safe_score(answer_rel),
            "context_relevancy": _safe_score(context_rel),
            "faithfulness": _safe_score(faithfulness),
        }
        scores = {k: v for k, v in raw_scores.items() if v is not None}

        log_event(
            logger,
            logging.INFO,
            "async_quality_judge_completed",
            request_id=request_id,
            query_type=query_type,
            scores=scores,
            question_preview=redact_sensitive_text(question[:120]),
        )
        _finish(scores=scores)
    except Exception as e:  # noqa: BLE001 - evaluator/LLM stack errors are heterogeneous; degrade to metrics only
        log_event(
            logger,
            logging.ERROR,
            "async_quality_judge_failed",
            request_id=request_id,
            error_type=type(e).__name__,
            error=str(e)[:240],
        )
        _finish(error=f"{type(e).__name__}: {e}"[:240])
