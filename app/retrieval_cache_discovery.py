"""Chroma collection name discovery helpers for retrieval_cache.

Extracted from retrieval_cache.py (AR-2026-05-29-003).
All functions are stateless except via the passed raise_empty_fn callback.
"""
from __future__ import annotations

from typing import Any

from chromadb.errors import NotFoundError

from app.chroma_vector_backend import get_default_chroma_backend
from app.config import CHROMA_DIR
from app.logging_config import setup_logging
from app.rag_runtime_preferences import effective_settings

logger = setup_logging()

_DEFAULT_CHUNKS_COLLECTION = "home_rag"
_DEFAULT_SUMMARY_COLLECTION = "home_rag_summaries"


def _settings():
    return effective_settings()


def _chroma_dir():
    return CHROMA_DIR


def _collection_count(client: Any, name: str) -> int | None:
    try:
        return int(client.get_collection(name).count())
    except NotFoundError:
        return None
    except Exception:  # noqa: BLE001 - Chroma count probe must not break resolution heuristics.
        return None


def _is_summary_collection_name(name: str) -> bool:
    lower = name.lower()
    return "summar" in lower or lower.endswith("_summaries")


def _is_staging_collection_name(name: str) -> bool:
    return "__staging__" in name


def _pick_non_empty_collection(client: Any, candidates: list[str]) -> str | None:
    for name in candidates:
        count = _collection_count(client, name)
        if count is not None and count > 0:
            return name
    return None


def _staging_run_suffix(collection_name: str) -> str | None:
    marker = "__staging__"
    if marker not in collection_name:
        return None
    return collection_name.rsplit(marker, 1)[-1]


def _discover_staging_chunks_collection(client: Any, base_name: str) -> str | None:
    """Recover from interrupted reindex: use the newest non-empty staging chunks collection."""
    prefix = f"{base_name}__staging__"
    backend = get_default_chroma_backend(_chroma_dir())
    candidates: list[tuple[int, str]] = []
    for name in backend.list_collections(client):
        if not name.startswith(prefix):
            continue
        count = _collection_count(client, name)
        if count is None or count <= 0:
            continue
        candidates.append((count, name))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    picked = candidates[0][1]
    logger.warning(
        "Recovered unactivated staging chunks collection | base=%s | staging=%s | count=%s",
        base_name,
        picked,
        candidates[0][0],
    )
    return picked


def _discover_staging_summary_collection(client: Any, base_summary: str, chunks_name: str) -> str | None:
    suffix = _staging_run_suffix(chunks_name)
    if suffix is None:
        return None
    bases = [
        base_summary,
        _DEFAULT_SUMMARY_COLLECTION,
        _settings().summary_collection_name,
    ]
    seen: set[str] = set()
    for base in bases:
        if not base or base in seen:
            continue
        seen.add(base)
        candidate = f"{base}__staging__{suffix}"
        count = _collection_count(client, candidate)
        if count is not None and count > 0:
            logger.warning(
                "Recovered unactivated staging summary collection | base=%s | staging=%s | count=%s",
                base,
                candidate,
                count,
            )
            return candidate
    return None


def _discover_chunks_collection(client: Any, preferred: str) -> str | None:
    settings = _settings()
    fallback_names = [
        preferred,
        _DEFAULT_CHUNKS_COLLECTION,
        settings.collection_name,
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for name in fallback_names:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    picked = _pick_non_empty_collection(client, ordered)
    if picked is not None:
        return picked

    backend = get_default_chroma_backend(_chroma_dir())
    skip = {settings.faq_memory_collection_name}
    scored: list[tuple[int, str]] = []
    for name in backend.list_collections(client):
        if name in skip or _is_summary_collection_name(name) or _is_staging_collection_name(name):
            continue
        count = _collection_count(client, name)
        if count is None or count <= 0:
            continue
        scored.append((count, name))
    if not scored:
        for base_name in (preferred, settings.collection_name):
            staging = _discover_staging_chunks_collection(client, base_name)
            if staging is not None:
                return staging
        return None
    scored.sort(reverse=True)
    return scored[0][1]


def _discover_summary_collection(client: Any, preferred: str, chunks_name: str) -> str | None:
    derived = f"{chunks_name}_summaries"
    fallback_names = [
        preferred,
        derived,
        _DEFAULT_SUMMARY_COLLECTION,
        _settings().summary_collection_name,
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for name in fallback_names:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    picked = _pick_non_empty_collection(client, ordered)
    if picked is not None:
        return picked

    staging_summary = _discover_staging_summary_collection(client, preferred, chunks_name)
    if staging_summary is not None:
        return staging_summary

    backend = get_default_chroma_backend(_chroma_dir())
    scored: list[tuple[int, str]] = []
    for name in backend.list_collections(client):
        if not _is_summary_collection_name(name) or _is_staging_collection_name(name):
            continue
        count = _collection_count(client, name)
        if count is None or count <= 0:
            continue
        scored.append((count, name))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]


def _resolve_active_collection_names(
    client: Any,
    chunks_name: str,
    summary_name: str,
    *,
    chroma_dir: Any,
    raise_empty_fn: Any,
) -> tuple[str, str]:
    """Map registry/env collection names to existing Chroma collections when possible."""
    settings = _settings()
    resolved_chunks = chunks_name
    if _collection_count(client, chunks_name) is None:
        discovered = _discover_chunks_collection(client, chunks_name)
        if discovered is None:
            raise_empty_fn(chroma_dir=chroma_dir, collection_name=chunks_name)
        resolved_chunks = discovered

    resolved_summary = summary_name
    if settings.enable_document_summaries:
        summary_missing = _collection_count(client, summary_name) is None
        chunks_resolved = resolved_chunks != chunks_name
        if summary_missing or chunks_resolved:
            discovered_summary = _discover_summary_collection(client, summary_name, resolved_chunks)
            if discovered_summary is None:
                logger.warning(
                    "Summary collection missing; topics catalog may be empty | requested=%s | chunks=%s",
                    summary_name,
                    resolved_chunks,
                )
            else:
                resolved_summary = discovered_summary

    if resolved_chunks != chunks_name or resolved_summary != summary_name:
        logger.warning(
            "Resolved Chroma collection names | requested_chunks=%s | resolved_chunks=%s | requested_summary=%s | resolved_summary=%s",
            chunks_name,
            resolved_chunks,
            summary_name,
            resolved_summary,
        )
        from app.index_registry import adopt_discovered_collections

        adopt_discovered_collections(resolved_chunks, resolved_summary)
    return resolved_chunks, resolved_summary


def _require_chroma_collection(
    client: Any,
    collection_name: str,
    *,
    chroma_dir: Any,
    raise_empty_fn: Any,
) -> Any:
    try:
        return client.get_collection(collection_name)
    except NotFoundError:
        raise_empty_fn(chroma_dir=chroma_dir, collection_name=collection_name)
