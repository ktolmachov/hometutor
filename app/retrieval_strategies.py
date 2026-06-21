"""Построение query engine по режиму retrieval (реестр стратегий).

Выбор продукта (rag profile) и упаковка ``ctx.trace[\"retrieval_routing\"]``
сосредоточены в ``app.retrieval_router`` (ADR‑021a A1: router ≠ profile resolver);
этот модуль отвечает только за сборку LlamaIndex engine по уже выбранному режиму.

Новые режимы добавлять в ``STRATEGY_REGISTRY`` и в ``KNOWN_RETRIEVAL_MODES`` в ``config.py``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.response_synthesizers import get_response_synthesizer
from llama_index.core.schema import QueryBundle
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters

from app.hybrid_retrieval import build_bm25_only_retriever, build_hybrid_retriever
from app.logging_config import log_event, setup_logging
from app.models import QueryContext

logger = setup_logging()


def _merge_filters(
    base: MetadataFilters | None, extra_filters: list[MetadataFilter]
) -> MetadataFilters | None:
    if not extra_filters:
        return base
    if base is None:
        return MetadataFilters(filters=list(extra_filters))
    return MetadataFilters(filters=list(base.filters) + list(extra_filters))


class DocThenChunkRetriever:
    """Двухуровневый retriever: сначала document summaries, затем чанки внутри документов."""

    def __init__(
        self,
        summary_index,
        base_index,
        similarity_top_k: int,
        doc_top_k: int,
        base_filters: MetadataFilters | None = None,
        doc_queries: list[str] | None = None,
    ):
        self._summary_index = summary_index
        self._base_index = base_index
        self._similarity_top_k = similarity_top_k
        self._doc_top_k = doc_top_k
        self._base_filters = base_filters
        self._doc_queries = [item for item in (doc_queries or []) if item]

    @staticmethod
    def _build_doc_candidates(summary_nodes) -> list[dict[str, str]]:
        candidates: list[dict[str, str]] = []

        for node in summary_nodes:
            metadata = getattr(node, "metadata", {}) or {}
            candidate = {
                "doc_id": metadata.get("doc_id") or "",
                "relative_path": metadata.get("relative_path") or "",
            }
            if not candidate["doc_id"] and not candidate["relative_path"]:
                continue
            if candidate not in candidates:
                candidates.append(candidate)

        return candidates

    def _retrieve_chunks_for_document(self, query_str: str, candidate: dict[str, str]):
        filter_attempts: list[list[MetadataFilter]] = []

        doc_id = candidate.get("doc_id")
        if doc_id:
            filter_attempts.append([MetadataFilter(key="doc_id", value=doc_id)])

        relative_path = candidate.get("relative_path")
        if relative_path:
            filter_attempts.append([MetadataFilter(key="relative_path", value=relative_path)])

        for extra_filters in filter_attempts:
            filters = _merge_filters(self._base_filters, extra_filters)
            chunk_retriever = self._base_index.as_retriever(
                similarity_top_k=self._similarity_top_k,
                filters=filters,
            )
            chunk_nodes = chunk_retriever.retrieve(query_str)
            if chunk_nodes:
                return chunk_nodes

        return []

    def retrieve(self, query_bundle: QueryBundle):
        query_str = getattr(query_bundle, "query_str", None) or str(query_bundle)

        summary_retriever = self._summary_index.as_retriever(
            similarity_top_k=self._doc_top_k
        )
        summary_queries = [query_str] + [item for item in self._doc_queries if item != query_str]
        doc_candidates: list[dict[str, str]] = []
        for summary_query in summary_queries:
            summary_nodes = summary_retriever.retrieve(summary_query)
            for candidate in self._build_doc_candidates(summary_nodes):
                if candidate not in doc_candidates:
                    doc_candidates.append(candidate)

        if not doc_candidates:
            log_event(
                logger,
                logging.INFO,
                "doc_then_chunk_no_document_match",
            )
            return []

        all_chunk_nodes = []
        seen_node_ids: set[str] = set()
        for candidate in doc_candidates:
            chunk_nodes = self._retrieve_chunks_for_document(query_str, candidate)
            for chunk_node in chunk_nodes:
                node_obj = getattr(chunk_node, "node", chunk_node)
                node_id = getattr(node_obj, "node_id", None) or getattr(node_obj, "id_", None)
                dedupe_key = node_id or repr(getattr(node_obj, "metadata", {})) + (getattr(node_obj, "text", "") or "")
                if dedupe_key in seen_node_ids:
                    continue
                seen_node_ids.add(dedupe_key)
                all_chunk_nodes.append(chunk_node)

        log_event(
            logger,
            logging.INFO,
            "doc_then_chunk_completed",
            doc_count=len(doc_candidates),
            chunk_count=len(all_chunk_nodes),
        )
        return all_chunk_nodes


StrategyBuildFn = Callable[..., Any]


def _build_hybrid(
    *,
    index,
    collection,
    llm,
    effective_params: dict[str, Any],
    filters,
    effective_prompt,
    postprocessors,
    **_kwargs: Any,
) -> RetrieverQueryEngine:
    retriever = build_hybrid_retriever(
        index, collection, effective_params["similarity_top_k"], filters
    )
    synthesizer = get_response_synthesizer(llm=llm, text_qa_template=effective_prompt)
    return RetrieverQueryEngine(
        retriever=retriever,
        node_postprocessors=postprocessors,
        response_synthesizer=synthesizer,
    )


def _build_bm25_only(
    *,
    collection,
    llm,
    effective_params: dict[str, Any],
    filters,
    effective_prompt,
    postprocessors,
    **_kwargs: Any,
) -> RetrieverQueryEngine:
    retriever = build_bm25_only_retriever(
        collection, effective_params["similarity_top_k"], filters
    )
    synthesizer = get_response_synthesizer(llm=llm, text_qa_template=effective_prompt)
    return RetrieverQueryEngine(
        retriever=retriever,
        node_postprocessors=postprocessors,
        response_synthesizer=synthesizer,
    )


def _build_doc_then_chunk(
    *,
    index,
    summary_index,
    llm,
    effective_params: dict[str, Any],
    filters,
    effective_prompt,
    postprocessors,
    query_context: Optional[QueryContext],
    **_kwargs: Any,
) -> RetrieverQueryEngine | Any:
    if summary_index is None:
        log_event(
            logger,
            logging.WARNING,
            "doc_then_chunk_summary_index_missing",
            fallback_mode="vector_only",
        )
        return index.as_query_engine(
            llm=llm,
            similarity_top_k=effective_params["similarity_top_k"],
            node_postprocessors=postprocessors,
            text_qa_template=effective_prompt,
            filters=filters,
        )
    doc_top_k = effective_params.get("doc_top_k", 5)
    retriever = DocThenChunkRetriever(
        summary_index=summary_index,
        base_index=index,
        similarity_top_k=effective_params["similarity_top_k"],
        doc_top_k=doc_top_k,
        base_filters=filters,
        doc_queries=(query_context.subquestions if query_context else None),
    )
    synthesizer = get_response_synthesizer(llm=llm, text_qa_template=effective_prompt)
    return RetrieverQueryEngine(
        retriever=retriever,
        node_postprocessors=postprocessors,
        response_synthesizer=synthesizer,
    )


def _build_vector_only(
    *,
    index,
    llm,
    effective_params: dict[str, Any],
    filters,
    effective_prompt,
    postprocessors,
    **_kwargs: Any,
) -> Any:
    return index.as_query_engine(
        llm=llm,
        similarity_top_k=effective_params["similarity_top_k"],
        node_postprocessors=postprocessors,
        text_qa_template=effective_prompt,
        filters=filters,
    )


STRATEGY_REGISTRY: dict[str, StrategyBuildFn] = {
    "hybrid": _build_hybrid,
    "bm25_only": _build_bm25_only,
    "doc_then_chunk": _build_doc_then_chunk,
    "vector_only": _build_vector_only,
}


def normalize_retrieval_mode(retrieval_mode: str) -> str:
    """Свернуть в известный ключ реестра (остальное — vector_only)."""
    if retrieval_mode in STRATEGY_REGISTRY:
        return retrieval_mode
    return "vector_only"


def build_query_engine_for_retrieval_mode(
    *,
    retrieval_mode: str,
    index,
    llm,
    collection,
    summary_index,
    effective_params: dict[str, Any],
    filters,
    effective_prompt,
    postprocessors,
    query_context: Optional[QueryContext],
) -> Any:
    mode = normalize_retrieval_mode(retrieval_mode)
    builder = STRATEGY_REGISTRY[mode]
    return builder(
        retrieval_mode=mode,
        index=index,
        llm=llm,
        collection=collection,
        summary_index=summary_index,
        effective_params=effective_params,
        filters=filters,
        effective_prompt=effective_prompt,
        postprocessors=postprocessors,
        query_context=query_context,
    )
