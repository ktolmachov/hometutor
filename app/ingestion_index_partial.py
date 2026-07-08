"""Incremental partial reindex: named phases + thin _build_index_partial orchestrator."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore

import app.ingestion as ing
from app import ingestion_support as ing_sup
from app.course_folder_filter import is_user_source_path
from app.ingestion_content_state import (
    apply_merge_metadata_to_documents,
    build_file_manifest,
    copy_chroma_vectors_by_doc_ids,
    fetch_merge_metadata_for_doc_ids,
    save_content_hash_state,
)
from app.ingestion_index_nodes import _build_nodes, _embed_and_store
from app.index_diff import update_snapshot_after_index
from app.index_lifecycle import apply_index_activation_hooks
from app.index_registry import get_active_collection_names
from app.knowledge_graph import write_staging_knowledge_graph_bundle
from app.metrics import record_ingestion_run
from app.retrieval_cache import activate_staging_index


def _partial_setup_phase(
    *,
    chroma_backend,
    target_collection_name: str,
    target_summary_collection_name: str,
    unchanged_ids: set[str],
    dirty_ids: set[str],
) -> tuple[Any, Any, str, str, int]:
    """Setup phase: validate active index, delete staging collections, copy unchanged vectors.

    Returns:
        tuple: (client, collection, active_chunks, active_summaries, copied_chunks)
    """
    active_chunks, active_summaries = get_active_collection_names()
    client = chroma_backend.get_client()
    try:
        ac = chroma_backend.get_collection(client, active_chunks)
        if ac.count() == 0:
            raise RuntimeError("active_index_empty")
    except Exception as exc:  # noqa: BLE001 - normalize backend availability errors for callers.
        raise RuntimeError(f"active_index_unavailable: {exc}") from exc

    chroma_backend.delete_collection(client, target_collection_name)
    chroma_backend.delete_collection(client, target_summary_collection_name)

    collection = chroma_backend.get_or_create_collection(client, target_collection_name)
    copied_chunks, covered_ids = copy_chroma_vectors_by_doc_ids(client, active_chunks, collection, unchanged_ids)
    if copied_chunks == 0 and unchanged_ids:
        raise RuntimeError("partial_chunk_copy_zero")
    missing_ids = unchanged_ids - covered_ids
    if missing_ids:
        # Incomplete copy would silently drop these documents from the new generation;
        # raising here routes the run into the full-rebuild fallback instead.
        raise RuntimeError(f"partial_chunk_copy_incomplete: missing={sorted(missing_ids)}")

    ing.logger.info(
        "Partial reindex started | dirty=%s unchanged=%s",
        len(dirty_ids),
        len(unchanged_ids),
    )
    return client, collection, active_chunks, active_summaries, copied_chunks


def _partial_enrichment_phase(
    *,
    documents: list[Document],
    dirty_ids: set[str],
    unchanged_ids: set[str],
    ingestion_run_started: float,
    client,
    active_chunks: str,
) -> tuple[list[Document], list[Document], dict, list[Document]]:
    """Enrichment phase: enrich dirty documents, fetch and apply merge metadata."""
    dirty_docs = [d for d in documents if (d.metadata or {}).get("doc_id") in dirty_ids]
    unchanged_docs = [d for d in documents if (d.metadata or {}).get("doc_id") in unchanged_ids]

    enriched_dirty, summary_docs, enrichment_stats = ing._enrich_documents(
        dirty_docs,
        ingest_t0=ingestion_run_started,
    )
    ing.logger.info(
        "Enrichment complete | documents_processed=%s",
        enrichment_stats.get("unique_doc_ids", 0),
    )

    merge_meta = fetch_merge_metadata_for_doc_ids(client, active_chunks, unchanged_ids)
    apply_merge_metadata_to_documents(unchanged_docs, merge_meta)
    all_docs_graph = enriched_dirty + unchanged_docs

    return enriched_dirty, summary_docs, enrichment_stats, all_docs_graph


def _partial_node_building_phase(
    *,
    enriched_dirty: list[Document],
) -> list:
    """Node building phase: contextualize and build nodes from dirty documents."""
    contextualized_dirty = ing._apply_contextualized_chunks(enriched_dirty)
    for doc in contextualized_dirty:
        ing._configure_document_for_metadata_aware_split(doc)
    dirty_nodes = _build_nodes(contextualized_dirty)
    ing.logger.info("Nodes built for partial indexing | count=%s", len(dirty_nodes))
    return dirty_nodes


def _partial_embedding_phase(
    *,
    dirty_nodes: list,
    embed_model,
    collection,
) -> None:
    """Embedding phase: embed and store dirty nodes."""
    vector_store = ChromaVectorStore(chroma_collection=collection)
    if dirty_nodes:
        _embed_and_store(dirty_nodes, embed_model, vector_store)


def _partial_summary_phase(
    *,
    summary_docs: list[Document],
    chroma_backend,
    client,
    target_summary_collection_name: str,
    active_summaries: str,
    unchanged_ids: set[str],
    embed_model,
    settings,
) -> None:
    """Summary phase: handle document summaries if enabled."""
    if settings.enable_document_summaries:
        summary_collection = chroma_backend.get_or_create_collection(client, target_summary_collection_name)
        copied_sum, covered_sum = copy_chroma_vectors_by_doc_ids(client, active_summaries, summary_collection, unchanged_ids)
        if copied_sum == 0 and unchanged_ids and summary_collection.count() == 0:
            ing.logger.warning("partial_summary_copy_zero | unchanged=%s", len(unchanged_ids))
        elif unchanged_ids - covered_sum:
            # Summaries are optional per doc (generation can fail), so warn instead of raising.
            ing.logger.warning(
                "partial_summary_copy_incomplete | missing=%s",
                len(unchanged_ids - covered_sum),
            )
        summary_vector_store = ChromaVectorStore(chroma_collection=summary_collection)
        summary_storage_context = StorageContext.from_defaults(vector_store=summary_vector_store)
        if summary_docs:
            VectorStoreIndex.from_documents(
                summary_docs,
                storage_context=summary_storage_context,
                embed_model=embed_model,
                show_progress=True,
            )
    else:
        chroma_backend.get_or_create_collection(client, target_summary_collection_name)


def _partial_graph_refresh_phase(
    *,
    all_docs_graph: list[Document],
    target_collection_name: str,
    current_hashes: dict[str, str],
) -> dict[str, object]:
    """Graph refresh phase: write staging knowledge graph (best-effort)."""
    graph_refresh: dict[str, object] = {"ok": False, "error": None, "gate_passed": False, "published": False}
    graph_hashes = {
        path: content_hash
        for path, content_hash in current_hashes.items()
        if is_user_source_path(path)
    }
    try:
        graph_stats = write_staging_knowledge_graph_bundle(
            all_docs_graph,
            target_collection_name,
            source_paths=sorted(graph_hashes),
            source_content_hashes=sorted(set(graph_hashes.values())),
        )
        graph_refresh = {"ok": True, **graph_stats}
    except Exception as exc:  # noqa: BLE001 - graph refresh is best-effort during partial reindex.
        ing.logger.exception("knowledge_graph_refresh_failed")
        graph_refresh = {"ok": False, "error": str(exc), "gate_passed": False, "published": False}
    return graph_refresh


def _partial_finalization_phase(
    *,
    collection,
    target_collection_name: str,
    target_summary_collection_name: str,
    chroma_dir: Path,
    embed_model,
    settings,
    retrieval_fp: str,
    ingestion_run_started: float,
    dirty_ids: set[str],
    unchanged_ids: set[str],
    copied_chunks: int,
    dirty_nodes: list,
    summary_docs: list[Document],
    enrichment_stats: dict,
    activated_index_state: dict,
    graph_refresh: dict[str, object],
    current_hashes: dict[str, str],
) -> None:
    """Finalization phase: save state, activate index, record metrics."""
    total_nodes = collection.count()
    ing.logger.info(
        "Partial indexing completed | collection=%s | copied_chunks=%s | dirty_nodes=%s | total_nodes=%s",
        target_collection_name,
        copied_chunks,
        len(dirty_nodes),
        total_nodes,
    )

    save_content_hash_state(
        chroma_dir,
        embed_model=settings.embed_model,
        retrieval_fingerprint=retrieval_fp,
        hashes=current_hashes,
        file_manifest=build_file_manifest(ing.DATA_DIR, ing.get_doc_supported_exts()),
        source_fragments=int(ing._ingestion_status.get("total_files", 0) or 0),
        nodes_count=total_nodes,
    )
    update_snapshot_after_index()

    _ingest_summary = ing.build_ingest_run_summary(
        run_kind="partial",
        unique_documents=len(unchanged_ids) + len(dirty_ids),
        source_fragments=int(ing._ingestion_status.get("total_files", 0) or 0),
        nodes_count=total_nodes,
        partial_rebuilt_docs=len(dirty_ids),
        partial_unchanged_docs=len(unchanged_ids),
    )
    ing._ingestion_status.update(
        {
            "status": "completed",
            "lifecycle_phase": "idle",
            "processed_files": ing._ingestion_status.get("total_files", 0),
            "current_file": None,
            "finished_at": time.time(),
            "ingest_run_summary": _ingest_summary,
            "cost": {
                **enrichment_stats,
                "run_type": "partial_reindex",
                "partial_unchanged_doc_ids": len(unchanged_ids),
                "partial_dirty_doc_ids": len(dirty_ids),
                "copied_chunk_vectors": copied_chunks,
                "duration_sec": round(time.perf_counter() - ingestion_run_started, 3),
                "nodes_count": total_nodes,
                "new_chunk_nodes": len(dirty_nodes),
                "summary_documents": len(summary_docs),
                "target_collection_name": target_collection_name,
                "target_summary_collection_name": target_summary_collection_name,
                "activation_pending": False,
                "activated_index_state": activated_index_state,
                "knowledge_graph_refresh": graph_refresh,
            },
        }
    )
    ing._print_ingest_run_summary(_ingest_summary)
    try:
        retrieve_fn = ing_sup.build_ingest_tail_retrieve_fn()
    except Exception as exc:  # noqa: BLE001 - tail retrieval setup must not block ingest success.
        ing.logger.warning("first_session_retrieve_fn_unavailable | error=%s", exc)
        retrieve_fn = None
    ing_sup.run_first_session_precompute_tail(
        docs_root=ing.DATA_DIR / "docs",
        retrieve_fn=retrieve_fn,
        logger=ing.logger,
    )
    record_ingestion_run(
        run_type="partial_reindex",
        total_files=ing._ingestion_status.get("total_files", 0),
        processed_files=ing._ingestion_status.get("total_files", 0),
        unique_doc_ids=enrichment_stats["unique_doc_ids"],
        nodes_count=total_nodes,
        summary_documents=len(summary_docs),
        duration_sec=time.perf_counter() - ingestion_run_started,
        estimated_cost_usd=enrichment_stats["estimated_cost_usd"],
        token_usage=enrichment_stats["token_usage"],
        enrichment_stats={
            "metadata_enrichment_calls": enrichment_stats["metadata_enrichment_calls"],
            "summary_calls": enrichment_stats["summary_calls"],
            "metadata_enrichment_successes": enrichment_stats["metadata_enrichment_successes"],
            "summary_successes": enrichment_stats["summary_successes"],
        },
    )


def _build_index_partial(
    *,
    documents: list[Document],
    current_hashes: dict[str, str],
    unchanged_ids: set[str],
    dirty_ids: set[str],
    ingestion_run_started: float,
    chroma_dir: Path,
    chroma_backend,
    target_collection_name: str,
    target_summary_collection_name: str,
    embed_model,
    settings,
    retrieval_fp: str,
) -> None:
    """Orchestrator for incremental staging reindex: delegates to phase functions."""
    client, collection, active_chunks, active_summaries, copied_chunks = _partial_setup_phase(
        chroma_backend=chroma_backend,
        target_collection_name=target_collection_name,
        target_summary_collection_name=target_summary_collection_name,
        unchanged_ids=unchanged_ids,
        dirty_ids=dirty_ids,
    )
    enriched_dirty, summary_docs, enrichment_stats, all_docs_graph = _partial_enrichment_phase(
        documents=documents,
        dirty_ids=dirty_ids,
        unchanged_ids=unchanged_ids,
        ingestion_run_started=ingestion_run_started,
        client=client,
        active_chunks=active_chunks,
    )
    dirty_nodes = _partial_node_building_phase(enriched_dirty=enriched_dirty)
    _partial_embedding_phase(dirty_nodes=dirty_nodes, embed_model=embed_model, collection=collection)
    _partial_summary_phase(
        summary_docs=summary_docs,
        chroma_backend=chroma_backend,
        client=client,
        target_summary_collection_name=target_summary_collection_name,
        active_summaries=active_summaries,
        unchanged_ids=unchanged_ids,
        embed_model=embed_model,
        settings=settings,
    )
    graph_refresh = _partial_graph_refresh_phase(
        all_docs_graph=all_docs_graph,
        target_collection_name=target_collection_name,
        current_hashes=current_hashes,
    )
    activated_index_state = activate_staging_index(
        target_collection_name,
        target_summary_collection_name,
    )
    apply_index_activation_hooks(reset=False)
    _partial_finalization_phase(
        collection=collection,
        target_collection_name=target_collection_name,
        target_summary_collection_name=target_summary_collection_name,
        chroma_dir=chroma_dir,
        embed_model=embed_model,
        settings=settings,
        retrieval_fp=retrieval_fp,
        ingestion_run_started=ingestion_run_started,
        dirty_ids=dirty_ids,
        unchanged_ids=unchanged_ids,
        copied_chunks=copied_chunks,
        dirty_nodes=dirty_nodes,
        summary_docs=summary_docs,
        enrichment_stats=enrichment_stats,
        activated_index_state=activated_index_state,
        graph_refresh=graph_refresh,
        current_hashes=current_hashes,
    )
