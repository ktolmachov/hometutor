"""Full reindex path: noop skip, enrichment/write/activation/cost phases, full pipeline."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore

import app.ingestion as ing
from app import ingestion_support as ing_sup
from app.ingestion_content_state import (
    build_file_manifest,
    can_skip_ingest_without_parsing,
    save_content_hash_state,
)
from app.ingestion_index_nodes import _build_nodes, _embed_and_store
from app.index_diff import update_snapshot_after_index
from app.index_lifecycle import apply_index_activation_hooks
from app.index_registry import activate_reset_generation, get_active_collection_names
from app.knowledge_graph import (
    get_active_knowledge_graph,
    write_generation_knowledge_graph_bundle,
    write_staging_knowledge_graph_bundle,
)
from app.metrics import record_ingestion_run
from app.retrieval_cache import activate_staging_index, clear_retrieval_cache


def _collection_has_vectors(chroma_backend, client, collection_name: str) -> tuple[bool, int]:
    try:
        col = chroma_backend.get_collection(client, collection_name)
        count = int(col.count())
        return count > 0, count
    except Exception as exc:  # noqa: BLE001 - Chroma backends raise different errors for missing collections.
        ing.logger.info("collection_not_available_for_noop | collection=%s | error=%s", collection_name, exc)
        return False, 0


def _build_index_try_noop_skip(
    *,
    reset: bool,
    build_to_staging: bool,
    settings: Any,
    retrieval_fp: str,
    file_manifest: dict[str, Any],
    stored: dict[str, object] | None,
    chroma_dir: Path,
    chroma_backend,
    client: Any,
    file_count: int,
    ingestion_run_started: float,
) -> bool:
    """Если индекс можно не пересобирать — обновляет статус и возвращает True."""
    if not can_skip_ingest_without_parsing(
        reset=reset,
        build_to_staging=build_to_staging,
        enable_partial_reindex=settings.enable_partial_reindex,
        embed_model=settings.embed_model,
        retrieval_fingerprint=retrieval_fp,
        current_file_manifest=file_manifest,
        stored=stored,
    ):
        return False
    active_chunks, _active_summaries = get_active_collection_names()
    active_ok, active_nodes = _collection_has_vectors(chroma_backend, client, active_chunks)
    if not active_ok:
        return False
    hashes = stored.get("hashes") if isinstance(stored, dict) else {}
    source_fragments = int(stored.get("source_fragments") or 0) if isinstance(stored, dict) else 0
    stored_nodes = int(stored.get("nodes_count") or active_nodes) if isinstance(stored, dict) else active_nodes
    _ingest_summary_noop = ing.build_ingest_run_summary(
        run_kind="noop",
        unique_documents=len(hashes) if isinstance(hashes, dict) else file_count,
        source_fragments=source_fragments,
        nodes_count=stored_nodes,
    )
    ing._ingestion_status.update(
        {
            "status": "completed",
            "lifecycle_phase": "idle",
            "total_files": source_fragments,
            "processed_files": source_fragments,
            "current_file": None,
            "finished_at": time.time(),
            "ingest_run_summary": _ingest_summary_noop,
            "cost": {
                "run_type": "noop_reindex",
                "duration_sec": round(time.perf_counter() - ingestion_run_started, 3),
                "nodes_count": active_nodes,
                "source_files": file_count,
                "target_collection_name": active_chunks,
                "activation_pending": False,
            },
        }
    )
    ing.logger.info("Ingest skipped: file manifest and retrieval settings unchanged")
    ing._print_ingest_run_summary(_ingest_summary_noop)
    return True


def _build_index_enrich_phase(
    documents: list[Document],
    *,
    ingestion_run_started: float,
) -> tuple[list[Document], list[Document], dict[str, Any], list]:
    """Обогащение документов, контекстуализация и построение нод для полной индексации."""
    documents, summary_documents, enrichment_stats = ing._enrich_documents(
        documents,
        ingest_t0=ingestion_run_started,
    )
    ing.logger.info(
        "Enrichment complete | documents_processed=%s",
        enrichment_stats.get("unique_doc_ids", 0),
    )
    ing._print_ingest_progress(
        phase="enrichment_done",
        processed=enrichment_stats.get("unique_doc_ids", 0) or 0,
        total=enrichment_stats.get("unique_doc_ids", 0) or 0,
        current=None,
        started_monotonic=ingestion_run_started,
    )
    ing.logger.info("Documents loaded | count=%s", len(documents))
    contextualized_documents = ing._apply_contextualized_chunks(documents)
    for doc in contextualized_documents:
        ing._configure_document_for_metadata_aware_split(doc)
    nodes = _build_nodes(contextualized_documents)
    ing.logger.info("Nodes built for indexing | count=%s", len(nodes))
    ing._print_ingest_progress(
        phase="nodes_built",
        processed=len(nodes),
        total=len(nodes),
        current=None,
        started_monotonic=ingestion_run_started,
    )
    return documents, summary_documents, enrichment_stats, nodes


def _build_index_write_chunk_and_summary_indexes(
    *,
    chroma_backend,
    client: Any,
    target_collection_name: str,
    target_summary_collection_name: str,
    nodes: list,
    summary_documents: list[Document],
    documents: list[Document],
    embed_model: Any,
    settings: Any,
    ingestion_run_started: float,
) -> None:
    """Удаление старых коллекций, индексация чанков и summaries."""
    chroma_backend.delete_collection(client, target_collection_name)
    ing.logger.info("Collection delete attempted before rebuild | collection=%s", target_collection_name)
    chroma_backend.delete_collection(client, target_summary_collection_name)
    ing.logger.info("Collection delete attempted before rebuild | collection=%s", target_summary_collection_name)
    collection = chroma_backend.get_or_create_collection(client, target_collection_name)
    vector_store = ChromaVectorStore(chroma_collection=collection)
    ing._print_ingest_progress(
        phase="vector_index_chunks_start",
        processed=0,
        total=len(nodes),
        current=target_collection_name,
        started_monotonic=ingestion_run_started,
    )
    _embed_and_store(nodes, embed_model, vector_store)
    ing._print_ingest_progress(
        phase="vector_index_chunks_done",
        processed=len(nodes),
        total=len(nodes),
        current=target_collection_name,
        started_monotonic=ingestion_run_started,
    )
    if settings.enable_document_summaries:
        summary_collection = chroma_backend.get_or_create_collection(client, target_summary_collection_name)
        summary_vector_store = ChromaVectorStore(chroma_collection=summary_collection)
        summary_storage_context = StorageContext.from_defaults(vector_store=summary_vector_store)
        if summary_documents:
            ing._print_ingest_progress(
                phase="vector_index_summaries_start",
                processed=0,
                total=len(summary_documents),
                current=target_summary_collection_name,
                started_monotonic=ingestion_run_started,
            )
            VectorStoreIndex.from_documents(
                summary_documents,
                storage_context=summary_storage_context,
                embed_model=embed_model,
                show_progress=True,
            )
            ing._print_ingest_progress(
                phase="vector_index_summaries_done",
                processed=len(summary_documents),
                total=len(summary_documents),
                current=target_summary_collection_name,
                started_monotonic=ingestion_run_started,
            )
            ing.logger.info(
                "Summary indexing completed | collection=%s | summaries=%s",
                target_summary_collection_name,
                len(summary_documents),
            )
        else:
            ing.logger.info(
                "No summary documents built; summary collection will be empty | collection=%s",
                target_summary_collection_name,
            )
    ing.logger.info(
        "Indexing completed | collection=%s | documents=%s | nodes=%s",
        target_collection_name,
        len(documents),
        len(nodes),
    )


def _build_index_activation_phase(
    *,
    build_to_staging: bool,
    documents: list[Document],
    target_collection_name: str,
    target_summary_collection_name: str,
    settings: Any,
    chroma_backend,
    client: Any,
    current_hashes: dict[str, str],
) -> tuple[dict[str, object], Any]:
    """Активация staging или reset-поколение, обновление knowledge graph."""
    graph_refresh: dict[str, object] = {"ok": False, "error": None, "gate_passed": False, "published": False}
    activated_index_state = None
    source_paths = sorted(current_hashes)
    source_content_hashes = sorted(set(current_hashes.values()))
    if build_to_staging:
        try:
            graph_stats = write_staging_knowledge_graph_bundle(
                documents,
                target_collection_name,
                source_paths=source_paths,
                source_content_hashes=source_content_hashes,
            )
            graph_refresh = {"ok": True, **graph_stats}
        except Exception as exc:  # noqa: BLE001 - graph refresh must not block index activation.
            ing.logger.exception("knowledge_graph_refresh_failed")
            graph_refresh = {"ok": False, "error": str(exc), "gate_passed": False, "published": False}
        activated_index_state = activate_staging_index(
            target_collection_name,
            target_summary_collection_name,
        )
        apply_index_activation_hooks(reset=False)
    else:
        existing_concepts = get_active_knowledge_graph().get_concepts()
        col_done = chroma_backend.get_collection(client, target_collection_name)
        nodes_n = col_done.count()
        sum_n = None
        if settings.enable_document_summaries:
            sum_n = chroma_backend.get_collection(client, target_summary_collection_name).count()
        activate_reset_generation(
            chunks_collection=target_collection_name,
            summaries_collection=target_summary_collection_name,
            embed_model=settings.embed_model,
            documents_count=len(documents),
            nodes_count=nodes_n,
            summary_documents_count=sum_n,
        )
        from app.index_registry import get_active_generation_view

        try:
            graph_stats = write_generation_knowledge_graph_bundle(
                documents,
                get_active_generation_view().generation_id,
                existing_concepts=existing_concepts,
                source_paths=source_paths,
                source_content_hashes=source_content_hashes,
            )
            graph_refresh = {"ok": True, **graph_stats}
        except Exception as exc:  # noqa: BLE001 - graph refresh must not block reset index activation.
            ing.logger.exception("knowledge_graph_refresh_failed")
            graph_refresh = {"ok": False, "error": str(exc), "gate_passed": False, "published": False}
        clear_retrieval_cache()
        from app.hybrid_retrieval import invalidate_bm25_cache as _inv_bm25
        _inv_bm25(clear_disk=True)
        apply_index_activation_hooks(reset=True)
    return graph_refresh, activated_index_state


def _build_index_cost_tracking_phase(
    *,
    chroma_dir: Path,
    retrieval_fp: str,
    current_hashes: dict[str, str],
    file_manifest: dict[str, Any],
    documents: list[Document],
    nodes: list,
    embed_model: Any,
    enrichment_stats: dict[str, Any],
    summary_documents: list[Document],
    target_collection_name: str,
    target_summary_collection_name: str,
    ingestion_run_started: float,
    activated_index_state: Any,
    graph_refresh: dict[str, object],
) -> None:
    """Сохранение хешей, сводка прогона, cost в статусе и запись метрик ingestion."""
    save_content_hash_state(
        chroma_dir,
        embed_model=embed_model,
        retrieval_fingerprint=retrieval_fp,
        hashes=current_hashes,
        file_manifest=file_manifest,
        source_fragments=len(documents),
        nodes_count=len(nodes),
    )
    update_snapshot_after_index()
    _ingest_summary_full = ing.build_ingest_run_summary(
        run_kind="full",
        unique_documents=int(enrichment_stats.get("unique_doc_ids") or 0),
        source_fragments=int(ing._ingestion_status.get("total_files", 0) or 0),
        nodes_count=len(nodes),
    )
    ing._ingestion_status.update(
        {
            "status": "completed",
            "lifecycle_phase": "idle",
            "processed_files": ing._ingestion_status.get("total_files", 0),
            "current_file": None,
            "finished_at": time.time(),
            "ingest_run_summary": _ingest_summary_full,
            "cost": {
                **enrichment_stats,
                "run_type": "full_reindex",
                "duration_sec": round(time.perf_counter() - ingestion_run_started, 3),
                "nodes_count": len(nodes),
                "summary_documents": len(summary_documents),
                "target_collection_name": target_collection_name,
                "target_summary_collection_name": target_summary_collection_name,
                "activation_pending": False,
                "activated_index_state": activated_index_state,
                "knowledge_graph_refresh": graph_refresh,
            },
        }
    )
    ing._print_ingest_run_summary(_ingest_summary_full)
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
        run_type="full_reindex",
        total_files=ing._ingestion_status.get("total_files", 0),
        processed_files=ing._ingestion_status.get("total_files", 0),
        unique_doc_ids=enrichment_stats["unique_doc_ids"],
        nodes_count=len(nodes),
        summary_documents=len(summary_documents),
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


def _run_full_reindex_pipeline(
    *,
    documents: list[Document],
    ingestion_run_started: float,
    chroma_backend: Any,
    client: Any,
    target_collection_name: str,
    target_summary_collection_name: str,
    embed_model: Any,
    settings: Any,
    build_to_staging: bool,
    chroma_dir: Path,
    retrieval_fp: str,
    current_hashes: dict[str, str],
    file_manifest: dict[str, Any],
) -> None:
    documents, summary_documents, enrichment_stats, nodes = _build_index_enrich_phase(
        documents,
        ingestion_run_started=ingestion_run_started,
    )

    # Всегда заменяем коллекции при полной индексации, чтобы повторный запуск не создавал дубликаты нод.
    # Параметр reset сохраняем для совместимости API/CLI; частичная переиндексация — выше (partial_reindex).
    _build_index_write_chunk_and_summary_indexes(
        chroma_backend=chroma_backend,
        client=client,
        target_collection_name=target_collection_name,
        target_summary_collection_name=target_summary_collection_name,
        nodes=nodes,
        summary_documents=summary_documents,
        documents=documents,
        embed_model=embed_model,
        settings=settings,
        ingestion_run_started=ingestion_run_started,
    )

    graph_refresh, activated_index_state = _build_index_activation_phase(
        build_to_staging=build_to_staging,
        documents=documents,
        target_collection_name=target_collection_name,
        target_summary_collection_name=target_summary_collection_name,
        settings=settings,
        chroma_backend=chroma_backend,
        client=client,
        current_hashes=current_hashes,
    )

    _build_index_cost_tracking_phase(
        chroma_dir=chroma_dir,
        retrieval_fp=retrieval_fp,
        current_hashes=current_hashes,
        file_manifest=file_manifest,
        documents=documents,
        nodes=nodes,
        embed_model=settings.embed_model,
        enrichment_stats=enrichment_stats,
        summary_documents=summary_documents,
        target_collection_name=target_collection_name,
        target_summary_collection_name=target_summary_collection_name,
        ingestion_run_started=ingestion_run_started,
        activated_index_state=activated_index_state,
        graph_refresh=graph_refresh,
    )
