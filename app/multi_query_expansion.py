"""Flag-gated multi-query retrieval expansion (merge + dedup by chunk_id)."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional

from llama_index.core.schema import NodeWithScore, QueryBundle

from app.config import get_retrieval_settings, get_settings
from app.latency_budget import _thresholds_for, resolve_query_surface
from app.llm_resilience import complete_with_resilience
from app.logging_config import log_event, setup_logging
from app.models import QueryContext, QueryExecutionPlan, QueryOptions
from app.prompts.multi_query_expansion import (
    PROMPT_ID,
    format_multi_query_expansion_prompt,
    parse_multi_query_variants,
)
from app.provider import get_rewrite_llm
from app.query_routing import KEYWORD_QUERY
from app.utils import safe_preview

logger = setup_logging()

# Conservative per-variant hybrid retrieval estimate for budget pre-check (ms).
_VARIANT_RETRIEVAL_ESTIMATE_MS = 1500
_EXPANSION_LLM_ESTIMATE_MS = 400


def _chunk_id_from_node(node_with_score: Any) -> str:
    node_obj = getattr(node_with_score, "node", node_with_score)
    metadata = getattr(node_obj, "metadata", {}) or {}
    chunk_id = metadata.get("chunk_id") or metadata.get("id")
    if chunk_id:
        return str(chunk_id)
    node_id = getattr(node_obj, "node_id", None) or getattr(node_obj, "id_", None)
    if node_id:
        return str(node_id)
    text = getattr(node_obj, "text", "") or ""
    rel = metadata.get("relative_path") or metadata.get("file_name") or ""
    return f"{rel}:{hash(text) & 0xFFFF_FFFF}"


def should_expand_queries(
    *,
    execution_plan: QueryExecutionPlan,
    query_context: QueryContext,
) -> tuple[bool, str | None]:
    """Architect gating: flag + rewrite + qa/overview + not bm25_only + no subquestions."""
    retrieval_settings = get_retrieval_settings()
    runtime_settings = get_settings()

    if not retrieval_settings.enable_multi_query:
        return False, "flag_off"
    if not runtime_settings.enable_rewrite:
        return False, "rewrite_off"

    effective_query = (query_context.effective_query or "").strip()
    if not effective_query:
        return False, "rewrite_off"

    query_type = execution_plan.query_type
    if query_type in (KEYWORD_QUERY, "keyword"):
        return False, "keyword_path"
    if query_type not in ("qa", "overview"):
        return False, "keyword_path"

    if execution_plan.retrieval_mode == "bm25_only":
        return False, "keyword_path"

    if query_type == "overview" and query_context.subquestions:
        return False, "subquestions_active"

    return True, None


def _dedupe_query_strings(queries: list[str], *, anchor: str) -> tuple[list[str], int]:
    """Anchor first; remove duplicate/near-duplicate strings (case-insensitive)."""
    anchor_norm = anchor.strip()
    result: list[str] = []
    seen: set[str] = set()

    if anchor_norm:
        result.append(anchor_norm)
        seen.add(anchor_norm.casefold())

    removed = 0
    for query in queries:
        normalized = " ".join(str(query).split()).strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        result.append(normalized)

    return result, removed


def expand_queries(
    effective_query: str,
    *,
    multi_query_count: int,
    trace: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    """Single LLM call; degrade to anchor-only on failure or <2 variants."""
    anchor = (effective_query or "").strip()
    trace.update(
        {
            "expansion_enabled": False,
            "variant_count": 1 if anchor else 0,
            "expansion_degraded": False,
            "prompt_id": PROMPT_ID,
        }
    )
    if not anchor:
        trace["expansion_degraded"] = True
        return [], trace

    t0 = time.perf_counter()
    variants: list[str] = []
    try:
        llm = get_rewrite_llm()
        prompt = format_multi_query_expansion_prompt(
            effective_query=anchor,
            variant_count=multi_query_count,
        )
        response = complete_with_resilience(llm, prompt, stage="multi_query_expansion")
        raw = getattr(response, "text", str(response))
        variants = parse_multi_query_variants(raw, max_count=multi_query_count)
    except Exception as exc:  # noqa: BLE001 - expansion must degrade gracefully.
        log_event(
            logger,
            logging.WARNING,
            "multi_query_expansion_llm_failed",
            error=str(exc),
        )
        trace["expansion_degraded"] = True
        trace["expansion_error"] = str(exc)

    expansion_ms = round((time.perf_counter() - t0) * 1000, 3)
    trace["expansion_ms"] = expansion_ms

    merged, dup_removed = _dedupe_query_strings(variants, anchor=anchor)
    trace["duplicate_variants_removed"] = dup_removed

    if len(merged) < 2:
        trace["expansion_degraded"] = True
        merged = [anchor]
    else:
        trace["expansion_enabled"] = True

    trace["variant_count"] = len(merged)
    trace["variant_queries"] = [safe_preview(q, 120) for q in merged]
    return merged, trace


def merge_deduped_candidates(
    variant_results: list[list[Any]],
    *,
    top_k: int | None = None,
) -> list[Any]:
    """Max score per chunk_id wins; tie-break lowest variant index (stable order)."""
    best: dict[str, tuple[float, int, Any]] = {}

    for variant_index, nodes in enumerate(variant_results):
        for node in nodes or []:
            chunk_id = _chunk_id_from_node(node)
            score = float(getattr(node, "score", 0.0) or 0.0)
            current = best.get(chunk_id)
            if current is None or score > current[0] or (
                score == current[0] and variant_index < current[1]
            ):
                best[chunk_id] = (score, variant_index, node)

    ordered = sorted(best.values(), key=lambda item: (-item[0], item[1]))
    merged = [item[2] for item in ordered]
    if top_k is not None and top_k > 0:
        return merged[:top_k]
    return merged


def _budget_allows_variant_fanout(
    options: QueryOptions,
    variant_count: int,
    *,
    elapsed_ms: float = 0.0,
) -> bool:
    """Pre-check: degrade when estimated fan-out would exceed query hard budget."""
    if variant_count <= 1:
        return True
    surface = resolve_query_surface(options)
    thresholds = _thresholds_for(surface, "cold")
    estimate = (
        elapsed_ms
        + _EXPANSION_LLM_ESTIMATE_MS
        + _VARIANT_RETRIEVAL_ESTIMATE_MS * variant_count
    )
    return estimate <= thresholds.hard_ms


def run_multi_query_retrieval(
    *,
    base_retriever: Any,
    variant_queries: list[str],
    trace: dict[str, Any],
    max_workers: int | None = None,
) -> list[list[Any]]:
    """Parallel per-variant hybrid retrieval via ThreadPoolExecutor."""
    if not variant_queries:
        return []

    workers = min(len(variant_queries), max_workers or 4, 4)
    t0 = time.perf_counter()
    results: list[list[Any]] = [[] for _ in variant_queries]

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="multi-query") as executor:
        future_map = {
            executor.submit(
                base_retriever.retrieve,
                QueryBundle(query_str=query),
            ): idx
            for idx, query in enumerate(variant_queries)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                results[idx] = list(future.result() or [])
            except Exception as exc:  # noqa: BLE001 - partial variant failure is tolerated.
                log_event(
                    logger,
                    logging.WARNING,
                    "multi_query_variant_retrieval_failed",
                    variant_index=idx,
                    error=str(exc),
                )
                results[idx] = []

    trace["variant_retrieval_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return results


class MultiQueryFusionRetriever:
    """Wrap a base retriever; fan-out variant queries then merge/dedup by chunk_id."""

    def __init__(
        self,
        base_retriever: Any,
        *,
        variant_queries: list[str],
        trace_sink: dict[str, Any],
        similarity_top_k: int,
    ):
        self._base_retriever = base_retriever
        self._variant_queries = list(variant_queries)
        self._trace_sink = trace_sink
        self._similarity_top_k = similarity_top_k

    def retrieve(self, query_bundle: QueryBundle | None = None):
        del query_bundle  # variants drive fan-out; anchor already included in list.
        t_merge = time.perf_counter()
        variant_results = run_multi_query_retrieval(
            base_retriever=self._base_retriever,
            variant_queries=self._variant_queries,
            trace=self._trace_sink,
            max_workers=min(len(self._variant_queries), 4),
        )
        merged = merge_deduped_candidates(
            variant_results,
            top_k=self._similarity_top_k,
        )
        self._trace_sink["merge_ms"] = round((time.perf_counter() - t_merge) * 1000, 3)
        return merged


def prepare_multi_query_expansion(
    *,
    execution_plan: QueryExecutionPlan,
    query_context: QueryContext,
    options: QueryOptions,
) -> tuple[list[str] | None, dict[str, Any]]:
    """Evaluate gating, budget, and optional LLM expansion; return trace payload."""
    should_run, skip_reason = should_expand_queries(
        execution_plan=execution_plan,
        query_context=query_context,
    )
    trace: dict[str, Any] = {
        "expansion_enabled": False,
        "expansion_degraded": False,
    }
    if not should_run:
        trace["expansion_skipped_reason"] = skip_reason
        trace["variant_count"] = 0
        return None, trace

    retrieval_settings = get_retrieval_settings()
    variant_queries, trace = expand_queries(
        query_context.effective_query,
        multi_query_count=retrieval_settings.multi_query_count,
        trace=trace,
    )

    if not trace.get("expansion_enabled"):
        return None, trace

    if not _budget_allows_variant_fanout(
        options,
        len(variant_queries),
        elapsed_ms=float(trace.get("expansion_ms") or 0.0),
    ):
        trace["expansion_enabled"] = False
        trace["expansion_degraded"] = True
        trace["expansion_skipped_reason"] = "budget_exceeded"
        trace["variant_count"] = 1
        return None, trace

    return variant_queries, trace


def wrap_engine_for_multi_query(
    engine: Any,
    *,
    variant_queries: list[str],
    trace_sink: dict[str, Any],
    similarity_top_k: int,
) -> Any:
    """Replace engine retriever with multi-query fusion wrapper."""
    base_retriever = getattr(engine, "_retriever", None) or getattr(engine, "retriever", None)
    if base_retriever is None:
        log_event(logger, logging.WARNING, "multi_query_wrap_missing_retriever")
        return engine

    wrapper = MultiQueryFusionRetriever(
        base_retriever,
        variant_queries=variant_queries,
        trace_sink=trace_sink,
        similarity_top_k=similarity_top_k,
    )
    if hasattr(engine, "_retriever"):
        engine._retriever = wrapper
    elif hasattr(engine, "retriever"):
        engine.retriever = wrapper
    return engine


__all__ = [
    "MultiQueryFusionRetriever",
    "expand_queries",
    "merge_deduped_candidates",
    "prepare_multi_query_expansion",
    "run_multi_query_retrieval",
    "should_expand_queries",
    "wrap_engine_for_multi_query",
]
