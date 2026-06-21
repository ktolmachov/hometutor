"""Index build / reindex orchestration; uses ``app.ingestion`` for document load/enrich."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from llama_index.core import Document

import app.ingestion as ing
from app.chroma_vector_backend import get_default_chroma_backend
from app.config import get_retrieval_settings, get_settings
from app.ingestion_content_state import (
    build_file_manifest,
    compute_doc_content_hashes,
    compute_retrieval_fingerprint,
    load_content_hash_state,
    plan_partial_reindex,
)
from app.ingestion_env_diag import (
    _log_ingest_settings_early,
    _log_ingest_settings_snapshot,
    _validate_embed_model_available,
)
from app.ingestion_index_full import _build_index_try_noop_skip, _run_full_reindex_pipeline
from app.ingestion_index_nodes import (  # re-export for tests importing from ingestion_loader
    _build_nodes,
    _embed_and_store,
)
from app.ingestion_index_partial import _build_index_partial
from app.provider import get_embed_model


def _build_staging_collection_name(base_collection_name: str, started_at: float | None = None) -> str:
    """Build a unique staging collection name for a non-destructive reindex run."""
    version = int((started_at if started_at is not None else time.time()) * 1000)
    return f"{base_collection_name}{ing.STAGING_COLLECTION_SEPARATOR}{version}"


def _build_index_execute_reindex_attempt(
    *,
    reset: bool,
    settings: Any,
    data_dir: Path,
    chroma_dir: Path,
    started_at: float,
    ingestion_run_started: float,
) -> None:
    prep = _prepare_reindex_attempt_inputs(
        reset=reset,
        data_dir=data_dir,
        chroma_dir=chroma_dir,
    )
    rs0 = prep["retrieval_settings"]
    retrieval_fp = prep["retrieval_fp"]
    file_manifest = prep["file_manifest"]
    file_count = prep["file_count"]
    chroma_backend = prep["chroma_backend"]
    client = prep["client"]
    build_to_staging = prep["build_to_staging"]
    stored = prep["stored"]

    if _should_skip_reindex_attempt(
        reset=reset,
        build_to_staging=build_to_staging,
        settings=settings,
        retrieval_fp=retrieval_fp,
        file_manifest=file_manifest,
        stored=stored,
        chroma_dir=chroma_dir,
        chroma_backend=chroma_backend,
        client=client,
        file_count=file_count,
        ingestion_run_started=ingestion_run_started,
    ):
        return

    embed_model = get_embed_model()
    _validate_embed_model_available(embed_model, settings)

    documents, current_hashes, unique_doc_ids = _load_documents_and_emit_progress(
        data_dir=data_dir,
        chroma_dir=chroma_dir,
        file_manifest=file_manifest,
        ingestion_run_started=ingestion_run_started,
        file_count=file_count,
    )

    _run_reindex_orchestration(
        reset=reset,
        settings=settings,
        build_to_staging=build_to_staging,
        started_at=started_at,
        retrieval_fp=retrieval_fp,
        current_hashes=current_hashes,
        stored=stored,
        rs0=rs0,
        chroma_dir=chroma_dir,
        data_dir=data_dir,
        documents=documents,
        unique_doc_ids=unique_doc_ids,
        embed_model=embed_model,
        ingestion_run_started=ingestion_run_started,
        chroma_backend=chroma_backend,
        client=client,
        file_manifest=file_manifest,
    )


def _run_reindex_orchestration(
    *,
    reset: bool,
    settings: Any,
    build_to_staging: bool,
    started_at: float,
    retrieval_fp: str,
    current_hashes: dict[str, str],
    stored: dict[str, object] | None,
    rs0: Any,
    chroma_dir: Path,
    data_dir: Path,
    documents: list[Document],
    unique_doc_ids: set[str | None],
    embed_model: Any,
    ingestion_run_started: float,
    chroma_backend: Any,
    client: Any,
    file_manifest: dict[str, Any],
) -> None:
    target_collection_name, target_summary_collection_name = _resolve_reindex_target_collections(
        settings=settings,
        build_to_staging=build_to_staging,
        started_at=started_at,
    )
    use_partial, unchanged_ids, dirty_ids = _plan_partial_reindex_with_logging(
        reset=reset,
        build_to_staging=build_to_staging,
        settings=settings,
        retrieval_fp=retrieval_fp,
        current_hashes=current_hashes,
        stored=stored,
        rs0=rs0,
        target_collection_name=target_collection_name,
        target_summary_collection_name=target_summary_collection_name,
        chroma_dir=chroma_dir,
        data_dir=data_dir,
        documents=documents,
        unique_doc_ids=unique_doc_ids,
        embed_model=embed_model,
    )
    if _run_partial_reindex_or_fallback(
        use_partial=use_partial,
        build_to_staging=build_to_staging,
        documents=documents,
        current_hashes=current_hashes,
        unchanged_ids=unchanged_ids,
        dirty_ids=dirty_ids,
        started_at=started_at,
        ingestion_run_started=ingestion_run_started,
        chroma_dir=chroma_dir,
        chroma_backend=chroma_backend,
        target_collection_name=target_collection_name,
        target_summary_collection_name=target_summary_collection_name,
        embed_model=embed_model,
        settings=settings,
        retrieval_fp=retrieval_fp,
    ):
        return

    _run_full_reindex_pipeline(
        documents=documents,
        ingestion_run_started=ingestion_run_started,
        chroma_backend=chroma_backend,
        client=client,
        target_collection_name=target_collection_name,
        target_summary_collection_name=target_summary_collection_name,
        embed_model=embed_model,
        settings=settings,
        build_to_staging=build_to_staging,
        chroma_dir=chroma_dir,
        retrieval_fp=retrieval_fp,
        current_hashes=current_hashes,
        file_manifest=file_manifest,
    )


def _prepare_reindex_attempt_inputs(
    *,
    reset: bool,
    data_dir: Path,
    chroma_dir: Path,
) -> dict[str, Any]:
    retrieval_settings = get_retrieval_settings()
    retrieval_fp = compute_retrieval_fingerprint(
        retrieval_settings.split_strategy,
        retrieval_settings.chunk_size,
        retrieval_settings.chunk_overlap,
        retrieval_settings.window_size,
    )
    file_manifest = build_file_manifest(data_dir, ing.get_doc_supported_exts())
    file_count = len(file_manifest.get("files") or {})
    if not file_count:
        raise ValueError("В папке data нет поддерживаемых документов")

    chroma_dir.mkdir(parents=True, exist_ok=True)
    chroma_backend = get_default_chroma_backend(chroma_dir)
    client = chroma_backend.get_client()
    return {
        "retrieval_settings": retrieval_settings,
        "retrieval_fp": retrieval_fp,
        "file_manifest": file_manifest,
        "file_count": file_count,
        "chroma_backend": chroma_backend,
        "client": client,
        "build_to_staging": not reset,
        "stored": load_content_hash_state(chroma_dir),
    }


def _should_skip_reindex_attempt(
    *,
    reset: bool,
    build_to_staging: bool,
    settings: Any,
    retrieval_fp: str,
    file_manifest: dict[str, Any],
    stored: dict[str, object] | None,
    chroma_dir: Path,
    chroma_backend: Any,
    client: Any,
    file_count: int,
    ingestion_run_started: float,
) -> bool:
    return _build_index_try_noop_skip(
        reset=reset,
        build_to_staging=build_to_staging,
        settings=settings,
        retrieval_fp=retrieval_fp,
        file_manifest=file_manifest,
        stored=stored,
        chroma_dir=chroma_dir,
        chroma_backend=chroma_backend,
        client=client,
        file_count=file_count,
        ingestion_run_started=ingestion_run_started,
    )


def _resolve_reindex_target_collections(
    *,
    settings: Any,
    build_to_staging: bool,
    started_at: float,
) -> tuple[str, str]:
    if build_to_staging:
        # T2: build a new index in staging without touching the active collections.
        target_collection_name = _build_staging_collection_name(
            settings.collection_name,
            started_at=started_at,
        )
        target_summary_collection_name = _build_staging_collection_name(
            settings.summary_collection_name,
            started_at=started_at,
        )
        ing.logger.info(
            "Preparing staging collections for reindex | active_collection=%s | staging_collection=%s | active_summary_collection=%s | staging_summary_collection=%s",
            settings.collection_name,
            target_collection_name,
            settings.summary_collection_name,
            target_summary_collection_name,
        )
        return target_collection_name, target_summary_collection_name
    # reset=True remains the explicit hard-reset path used by tests/manual rebuilds.
    return settings.collection_name, settings.summary_collection_name


def _plan_partial_reindex_with_logging(
    *,
    reset: bool,
    build_to_staging: bool,
    settings: Any,
    retrieval_fp: str,
    current_hashes: dict[str, str],
    stored: dict[str, object] | None,
    rs0: Any,
    target_collection_name: str,
    target_summary_collection_name: str,
    chroma_dir: Path,
    data_dir: Path,
    documents: list[Document],
    unique_doc_ids: set[str | None],
    embed_model: Any,
) -> tuple[bool, set[str], set[str]]:
    use_partial, unchanged_ids, dirty_ids = plan_partial_reindex(
        reset=reset,
        build_to_staging=build_to_staging,
        enable_partial_reindex=settings.enable_partial_reindex,
        embed_model=settings.embed_model,
        retrieval_fingerprint=retrieval_fp,
        current_hashes=current_hashes,
        stored=stored,
    )
    _log_ingest_settings_snapshot(
        settings=settings,
        retrieval_settings=rs0,
        reset=reset,
        build_to_staging=build_to_staging,
        use_partial_reindex=use_partial,
        partial_unchanged_docs=len(unchanged_ids),
        partial_dirty_docs=len(dirty_ids),
        target_chunk_collection=target_collection_name,
        target_summary_collection=target_summary_collection_name,
        chroma_persist=chroma_dir,
        data_directory=data_dir,
        raw_documents=len(documents),
        unique_doc_ids=len(unique_doc_ids),
        retrieval_fingerprint=retrieval_fp,
        embed_model=embed_model,
    )
    return use_partial, unchanged_ids, dirty_ids


def _run_partial_reindex_or_fallback(
    *,
    use_partial: bool,
    build_to_staging: bool,
    documents: list[Document],
    current_hashes: dict[str, str],
    unchanged_ids: set[str],
    dirty_ids: set[str],
    started_at: float,
    ingestion_run_started: float,
    chroma_dir: Path,
    chroma_backend: Any,
    target_collection_name: str,
    target_summary_collection_name: str,
    embed_model: Any,
    settings: Any,
    retrieval_fp: str,
) -> bool:
    if not (use_partial and build_to_staging):
        return False
    try:
        _build_index_partial(
            documents=documents,
            current_hashes=current_hashes,
            unchanged_ids=unchanged_ids,
            dirty_ids=dirty_ids,
            ingestion_run_started=ingestion_run_started,
            chroma_dir=chroma_dir,
            chroma_backend=chroma_backend,
            target_collection_name=target_collection_name,
            target_summary_collection_name=target_summary_collection_name,
            embed_model=embed_model,
            settings=settings,
            retrieval_fp=retrieval_fp,
        )
        return True
    except Exception as exc:  # noqa: BLE001 - fallback to full reindex on partial pipeline failure.
        ing.logger.warning("partial_reindex_fallback | error=%s", exc, exc_info=True)
        return False


def _load_documents_and_emit_progress(
    *,
    data_dir: Path,
    chroma_dir: Path,
    file_manifest: dict[str, Any],
    ingestion_run_started: float,
    file_count: int,
) -> tuple[list[Document], dict[str, str], set[str | None]]:
    documents = ing._load_documents_with_extraction_cache(
        data_dir=data_dir,
        chroma_dir=chroma_dir,
        file_manifest=file_manifest,
        started_monotonic=ingestion_run_started,
    )
    ing._ingestion_status["total_files"] = len(documents)
    ing.logger.info("Documents loaded from data | fragments=%s", len(documents))
    if not documents:
        raise ValueError("В папке data нет поддерживаемых документов")

    current_hashes = compute_doc_content_hashes(documents)
    # После _add_metadata doc_id уже выставлен, можно корректно посчитать document-level.
    unique_doc_ids = {doc.metadata.get("doc_id") for doc in documents}
    ing._print_ingest_progress(
        phase="documents_loaded",
        processed=len(documents),
        total=len(documents),
        current=None,
        started_monotonic=ingestion_run_started,
        extra=f"unique_docs={len(unique_doc_ids)} source_files={file_count}",
    )
    return documents, current_hashes, unique_doc_ids


def build_index(reset: bool = False) -> None:
    settings = get_settings()
    data_dir = ing.DATA_DIR
    chroma_dir = ing.CHROMA_DIR

    if not settings.openai_api_key:
        # PR smoke: e2e_run_stack выставляет HOME_RAG_E2E_OFFLINE и пустой ключ — reindex не должен ронять worker
        # до обновления ing._ingestion_status (иначе /reindex/status вечно «idle» и E2E ждут таймаут).
        if settings.home_rag_e2e_offline:
            ing.logger.info("build_index skipped: HOME_RAG_E2E_OFFLINE without OPENAI_API_KEY")
            ing._ingestion_status.update(
                {
                    "status": "completed",
                    "lifecycle_phase": "idle",
                    "finished_at": time.time(),
                    "error": None,
                    "ingest_run_summary": None,
                }
            )
            return
        raise ValueError("OPENAI_API_KEY не найден в .env")

    if not data_dir.exists():
        raise FileNotFoundError(f"Папка data не найдена: {data_dir}")

    started_at = time.time()
    ingestion_run_started = time.perf_counter()
    ing._ingestion_status.update(
        {
            "status": "running",
            "lifecycle_phase": "building",
            "total_files": 0,
            "processed_files": 0,
            "current_file": None,
            "started_at": started_at,
            "finished_at": None,
            "error": None,
            "cost": None,
        }
    )

    _log_ingest_settings_early(
        settings=settings,
        retrieval_settings=get_retrieval_settings(),
        reset=reset,
        data_directory=data_dir,
        chroma_persist=chroma_dir,
    )
    try:
        _build_index_execute_reindex_attempt(
            reset=reset,
            settings=settings,
            data_dir=data_dir,
            chroma_dir=chroma_dir,
            started_at=started_at,
            ingestion_run_started=ingestion_run_started,
        )
    except Exception as exc:  # noqa: BLE001 - top-level ingestion status must record unexpected failure.
        ing._ingestion_status.update(
            {
                "status": "failed",
                "lifecycle_phase": "failed",
                "error": str(exc),
                "finished_at": time.time(),
            }
        )
        raise
