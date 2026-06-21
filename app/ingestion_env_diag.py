"""Ingestion environment diagnostics and preflight logging."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from app.config import BASE_DIR
from app.logging_config import setup_logging

logger = setup_logging()


def _resolve_embed_api_base(settings: Any) -> str:
    s = settings
    resolved = getattr(s, "embed_api_base_resolved", None)
    if resolved is None:
        resolved = getattr(s, "embed_api_base", None) or getattr(
            s, "openai_api_base", "https://openrouter.ai/api/v1"
        )
    return str(resolved)


def _ingest_env_settings_dict(settings: Any, retrieval_settings: Any = None) -> dict[str, object]:
    """Keys as in .env, for grep and documentation checks."""
    s = settings
    rs = retrieval_settings
    split_strategy = (
        getattr(rs, "split_strategy", None)
        if rs is not None
        else None
    ) or "sentence_window"
    return {
        "EMBED_API_BASE": _resolve_embed_api_base(s),
        "EMBED_MODEL": getattr(s, "embed_model", "perplexity/pplx-embed-v1-0.6b"),
        "EMBED_DIMENSIONS": getattr(s, "embed_dimensions", 1024),
        "EMBED_BATCH_SIZE": getattr(s, "embed_batch_size", 32),
        "EMBED_REQUEST_TIMEOUT": getattr(s, "embed_request_timeout", 60),
        "EMBED_CONNECT_TIMEOUT_SEC": getattr(s, "embed_connect_timeout_sec", 10.0),
        "ENABLE_METADATA_ENRICHMENT": getattr(s, "enable_metadata_enrichment", True),
        "ENABLE_DOCUMENT_SUMMARIES": getattr(s, "enable_document_summaries", True),
        "SPLIT_STRATEGY": split_strategy,
    }


def _embed_env_sources() -> dict[str, object]:
    """Diagnostic-only comparison of raw ``os.environ`` with the on-disk ``.env``.

    Runtime configuration must still come from ``get_settings()`` / pydantic.
    This intentionally reads process environment to expose shell/CI overrides
    that differ from the local ``.env`` file.
    """
    names = (
        "EMBED_API_BASE",
        "EMBED_MODEL",
        "EMBED_DIMENSIONS",
        "EMBED_BATCH_SIZE",
        "EMBED_NUM_WORKERS",
    )
    dotenv_path = BASE_DIR / ".env"
    dotenv_raw = dotenv_values(dotenv_path) if dotenv_path.exists() else {}
    dotenv_values_map = {
        name: str(dotenv_raw[name])
        for name in names
        if dotenv_raw.get(name) is not None
    }
    process_values = {name: os.environ[name] for name in names if name in os.environ}
    differs_from_dotenv = {
        name: value
        for name, value in process_values.items()
        if name in dotenv_values_map and dotenv_values_map[name] != value
    }
    process_only = {
        name: value
        for name, value in process_values.items()
        if name not in dotenv_values_map
    }
    return {
        "dotenv_path": str(dotenv_path),
        "dotenv": dotenv_values_map,
        "process": process_values,
        "differs_from_dotenv": differs_from_dotenv,
        "process_only": process_only,
    }


def _chunking_retrieval_dict(retrieval_settings: Any) -> dict[str, object]:
    rs = retrieval_settings
    return {
        "rag_profile": getattr(rs, "rag_profile", "fast"),
        "retrieval_mode": getattr(rs, "retrieval_mode", "vector_only"),
        "split_strategy": getattr(rs, "split_strategy", "sentence_window"),
        "window_size": getattr(rs, "window_size", 2),
        "chunk_size": getattr(rs, "chunk_size", 700),
        "chunk_overlap": getattr(rs, "chunk_overlap", 50),
        "similarity_top_k": getattr(rs, "similarity_top_k", 10),
        "enable_reranker": getattr(rs, "enable_reranker", True),
        "rerank_top_n": getattr(rs, "rerank_top_n", 4),
        "rerank_model": getattr(rs, "rerank_model", "BAAI/bge-reranker-base"),
        "doc_top_k": getattr(rs, "doc_top_k", 5),
    }


def _log_ingest_settings_early(
    *,
    settings: Any,
    retrieval_settings: Any,
    reset: bool,
    data_directory: Path,
    chroma_persist: Path,
) -> None:
    """Log EMBED_* and chunking settings before long document loading starts."""
    payload = {
        "ingest_phase": "startup_settings",
        "reset": reset,
        "paths": {
            "data_dir": str(data_directory),
            "chroma_persist": str(chroma_persist),
        },
        "ingest_env_settings": _ingest_env_settings_dict(settings, retrieval_settings),
        "embed_env_sources": _embed_env_sources(),
        "chunking_retrieval": _chunking_retrieval_dict(retrieval_settings),
    }
    logger.info("Ingest startup settings | %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _log_ingest_settings_snapshot(
    *,
    settings: Any,
    retrieval_settings: Any,
    reset: bool,
    build_to_staging: bool,
    use_partial_reindex: bool,
    partial_unchanged_docs: int,
    partial_dirty_docs: int,
    target_chunk_collection: str,
    target_summary_collection: str,
    chroma_persist: Path,
    data_directory: Path,
    raw_documents: int,
    unique_doc_ids: int,
    retrieval_fingerprint: str,
    embed_model: object | None = None,
) -> None:
    """Emit one JSON settings snapshot for long ingest runs."""
    s = settings
    rs = retrieval_settings
    ingestion_override = (str(getattr(s, "ingestion_model", "") or "").strip() or None)
    llm_model = getattr(s, "llm_model", "gpt-4o-mini")
    ingestion_llm = ingestion_override or llm_model
    env_block = _ingest_env_settings_dict(s, rs)
    embed_api_resolved = str(env_block["EMBED_API_BASE"])
    embed_model_val = str(env_block["EMBED_MODEL"])
    embed_dimensions = int(env_block["EMBED_DIMENSIONS"])
    embed_batch = int(env_block["EMBED_BATCH_SIZE"])
    embed_req_timeout = int(env_block["EMBED_REQUEST_TIMEOUT"])
    embed_conn_timeout = float(env_block["EMBED_CONNECT_TIMEOUT_SEC"])
    meta_enrich = bool(env_block["ENABLE_METADATA_ENRICHMENT"])
    doc_summaries = bool(env_block["ENABLE_DOCUMENT_SUMMARIES"])
    payload: dict[str, object] = {
        "ingest_phase": "settings_snapshot",
        "reset": reset,
        "build_to_staging": build_to_staging,
        "use_partial_reindex": use_partial_reindex,
        "partial_unchanged_docs": partial_unchanged_docs,
        "partial_dirty_docs": partial_dirty_docs,
        "paths": {
            "data_dir": str(data_directory),
            "chroma_persist": str(chroma_persist),
        },
        "collections": {
            "target_chunk": target_chunk_collection,
            "target_summary": target_summary_collection,
            "active_chunk": getattr(s, "collection_name", "home_rag"),
            "active_summary": getattr(s, "summary_collection_name", "home_rag_summaries"),
        },
        "documents": {
            "raw_fragments": raw_documents,
            "unique_doc_ids": unique_doc_ids,
            "retrieval_fingerprint": retrieval_fingerprint,
        },
        "ingest_env_settings": dict(env_block),
        "embed_env_sources": _embed_env_sources(),
        "embedding": {
            "embed_model": embed_model_val,
            "embed_dimensions": embed_dimensions,
            "embed_api_base": embed_api_resolved,
            "embed_batch_size": embed_batch,
            "embed_request_timeout_sec": embed_req_timeout,
            "embed_connect_timeout_sec": embed_conn_timeout,
            "embed_model_impl": type(embed_model).__name__ if embed_model is not None else None,
        },
        "llm_api": {
            "openai_api_base": getattr(s, "openai_api_base", "https://openrouter.ai/api/v1"),
            "llm_model": llm_model,
            "ingestion_model_effective": ingestion_llm,
            "ingestion_model_override": ingestion_override,
            "ingestion_model_dormant": not meta_enrich and not doc_summaries,
            "llm_request_timeout_sec": getattr(s, "llm_request_timeout", 60),
            "llm_connect_timeout_sec": getattr(s, "llm_connect_timeout_sec", 10.0),
            "openai_api_key_configured": bool(getattr(s, "openai_api_key", None)),
        },
        "ingest_features": {
            "enable_metadata_enrichment": meta_enrich,
            "enable_document_summaries": doc_summaries,
            "enable_partial_reindex": getattr(s, "enable_partial_reindex", True),
            "offline_mode": getattr(s, "offline_mode", False),
        },
        "chunking_retrieval": _chunking_retrieval_dict(rs),
    }
    logger.info("Ingest settings snapshot | %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _validate_embed_model_available(embed_model: object, settings: Any) -> None:
    """Fail fast before loading data or deleting Chroma collections."""
    get_text_embedding = getattr(embed_model, "get_text_embedding", None)
    if not callable(get_text_embedding):
        return

    expected_dimensions = int(getattr(settings, "embed_dimensions", 0) or 0)
    configured_model = str(getattr(settings, "embed_model", "") or "")
    api_base = str(getattr(settings, "embed_api_base_resolved", "") or "")
    batch_size = max(1, int(getattr(settings, "embed_batch_size", 1) or 1))
    sample_text = "ping " * 300
    get_text_embedding_batch = getattr(embed_model, "get_text_embedding_batch", None)
    try:
        if callable(get_text_embedding_batch):
            sample_batch = [f"{sample_text}{idx}" for idx in range(batch_size)]
            embeddings = get_text_embedding_batch(sample_batch, show_progress=False)
            embedding = embeddings[0]
            checked_batch = len(sample_batch)
        else:
            embedding = get_text_embedding(sample_text)
            checked_batch = 1
    except Exception as exc:  # noqa: BLE001 - provider/SDK errors are heterogeneous and need effective settings context.
        raise RuntimeError(
            "Embeddings preflight failed before indexing. "
            f"EMBED_MODEL={configured_model!r}, "
            f"EMBED_API_BASE={api_base!r}, "
            f"EMBED_DIMENSIONS={expected_dimensions or 'provider-default'}, "
            f"EMBED_BATCH_SIZE={batch_size!r}, "
            f"embed_env_sources={_embed_env_sources()!r}. "
            "Check .env, clear any shell-level EMBED_* overrides, and keep OpenRouter ingest batch size conservative."
        ) from exc

    actual_dimensions = len(embedding)
    if expected_dimensions and actual_dimensions != expected_dimensions:
        raise RuntimeError(
            "Embeddings preflight returned unexpected vector size. "
            f"Expected EMBED_DIMENSIONS={expected_dimensions}, got {actual_dimensions}. "
            f"EMBED_MODEL={configured_model!r}."
        )

    logger.info(
        "Embeddings preflight passed | configured_model=%s | llama_index_model_name=%s | llama_index_text_engine=%s | dimensions=%s | api_base=%s | checked_batch=%s",
        configured_model,
        getattr(embed_model, "model_name", None),
        getattr(embed_model, "_text_engine", None),
        actual_dimensions,
        api_base,
        checked_batch,
    )
