import time
from typing import Optional

from llama_index.core import get_response_synthesizer
from llama_index.core.schema import QueryBundle

from app.hybrid_retrieval import build_hybrid_retriever
from app.logging_config import setup_logging
from app.models import PipelineOverrides, QueryOptions
from app.pipeline_factory import (
    QA_PROMPT,
    build_filters,
    build_postprocessors,
    resolve_pipeline_params,
)
from app.retrieval_cache import get_base_services
from app.utils import safe_preview

logger = setup_logging()


def run_profiled_query(
    question: str,
    options: QueryOptions,
    overrides: Optional[PipelineOverrides] = None,
):
    total_started = time.perf_counter()

    services = get_base_services()
    index = services["index"]
    llm = services["llm"]
    collection = services["collection"]

    resolved = resolve_pipeline_params(overrides)
    filters = build_filters(options)
    postprocessors = build_postprocessors(resolved)

    retriever_started = time.perf_counter()
    retrieval_mode = resolved.get("retrieval_mode", "vector_only")
    if retrieval_mode == "hybrid":
        retriever = build_hybrid_retriever(
            index, collection, resolved["similarity_top_k"], filters
        )
    else:
        retriever = index.as_retriever(
            similarity_top_k=resolved["similarity_top_k"],
            filters=filters,
        )
    query_bundle = QueryBundle(question)
    retrieved_nodes = retriever.retrieve(query_bundle)
    retrieval_ms = (time.perf_counter() - retriever_started) * 1000

    logger.info(
        "Profiled retrieval completed | question=%r | retrieved_nodes=%s | retrieval_ms=%.3f | filters=%s | top_k=%s",
        question,
        len(retrieved_nodes),
        retrieval_ms,
        filters,
        resolved["similarity_top_k"],
    )

    rerank_started = time.perf_counter()
    processed_nodes = retrieved_nodes
    for postprocessor in postprocessors:
        processed_nodes = postprocessor.postprocess_nodes(
            processed_nodes,
            query_bundle=query_bundle,
        )
    rerank_ms = (time.perf_counter() - rerank_started) * 1000

    logger.info(
        "Profiled postprocessing completed | input_nodes=%s | output_nodes=%s | rerank_ms=%.3f",
        len(retrieved_nodes),
        len(processed_nodes),
        rerank_ms,
    )

    synthesis_started = time.perf_counter()
    response_synthesizer = get_response_synthesizer(
        llm=llm,
        text_qa_template=QA_PROMPT,
    )
    response = response_synthesizer.synthesize(
        query=question,
        nodes=processed_nodes,
    )
    synthesis_ms = (time.perf_counter() - synthesis_started) * 1000
    total_ms = (time.perf_counter() - total_started) * 1000

    logger.info(
        "Profiled synthesis completed | synthesis_ms=%.3f | total_ms=%.3f",
        synthesis_ms,
        total_ms,
    )

    sources = []
    for idx, node in enumerate(processed_nodes, start=1):
        try:
            source_node = getattr(node, "node", node)
            metadata = getattr(source_node, "metadata", {}) or {}
            text_value = getattr(source_node, "text", None)
            score = getattr(node, "score", None)

            sources.append(
                {
                    "file_name": metadata.get("file_name"),
                    "folder_name": metadata.get("folder_name"),
                    "folder_rel": metadata.get("folder_rel"),
                    "relative_path": metadata.get("relative_path"),
                    "page": metadata.get("page_label", "?"),
                    "score": score,
                    "text": (text_value or "")[:500],
                }
            )

            logger.info(
                "Profiled source #%s | path=%r | page=%r | score=%r | text_preview=%r",
                idx,
                metadata.get("relative_path"),
                metadata.get("page_label", "?"),
                score,
                safe_preview(text_value, 200),
            )
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            logger.exception("Failed to parse profiled source #%s", idx)

    return {
        "answer": str(response),
        "sources": sources,
        "profile": {
            "profile": resolved["profile"],
            "retrieval_mode": retrieval_mode,
            "retrieval_ms": round(retrieval_ms, 3),
            "rerank_ms": round(rerank_ms, 3),
            "synthesis_ms": round(synthesis_ms, 3),
            "total_ms": round(total_ms, 3),
            "retrieved_nodes_count": len(retrieved_nodes),
            "postprocessed_nodes_count": len(processed_nodes),
            "filters": repr(filters),
            "similarity_top_k": resolved["similarity_top_k"],
            "rerank_enabled": resolved["enable_reranker"],
            "rerank_top_n": resolved["rerank_top_n"] if resolved["enable_reranker"] else None,
            "rerank_model": resolved["rerank_model"] if resolved["enable_reranker"] else None,
            "split_strategy": resolved["split_strategy"],
            "window_size": resolved["window_size"],
        },
    }
