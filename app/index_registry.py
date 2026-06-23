"""
Canonical index generation registry (blue-green).

Single source of truth: index_registry.json under HOME_RAG_HOME (INDEX_REGISTRY_PATH).
Migrates from legacy chroma_db/active_index.json or code-repo index_registry.json on first read.
"""

from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from app.config import get_settings
from app.logging_config import setup_logging

logger = setup_logging()

SCHEMA_VERSION = 1

_settings = get_settings()
REGISTRY_PATH = Path(_settings.index_registry_path)
REGISTRY_LOCK_PATH = Path(_settings.index_registry_lock_path)

# Legacy pointer (still read for one-shot migration)
LEGACY_ACTIVE_INDEX_PATH = Path(_settings.active_index_state_path)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(s: str, max_len: int = 48) -> str:
    t = re.sub(r"[^a-zA-Z0-9_]+", "_", (s or "").strip())[:max_len].strip("_")
    return t or "gen"


def _default_active_from_settings() -> dict[str, Any]:
    s = get_settings()
    cid = "legacy"
    return {
        "generation_id": cid,
        "chunks_collection": s.collection_name,
        "summaries_collection": s.summary_collection_name,
        "activated_at": None,
        "embed_model": None,
        "documents_count": None,
        "nodes_count": None,
        "summary_documents_count": None,
    }


def _empty_registry() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "index_version": 0,
        "active_generation": _default_active_from_settings(),
        "previous_generation": None,
        "staging_generation": None,
        "last_failed_generation": None,
    }


def _migrate_from_legacy_active_index() -> dict[str, Any] | None:
    if not LEGACY_ACTIVE_INDEX_PATH.exists():
        return None
    try:
        raw = json.loads(LEGACY_ACTIVE_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — file may have any JSON/IO corruption; log and migrate.
        logger.warning("Legacy active_index.json unreadable | path=%s | error=%s", LEGACY_ACTIVE_INDEX_PATH, exc)
        return None
    if not isinstance(raw, dict):
        return None
    chunks = str(raw.get("collection_name") or "").strip()
    summaries = str(raw.get("summary_collection_name") or "").strip()
    vm = str(raw.get("version_marker") or "").strip()
    activated_at = raw.get("activated_at")
    if activated_at is not None:
        activated_at = str(activated_at)
    if not chunks or not summaries:
        return None
    gid = "legacy"
    if vm and vm != chunks:
        gid = f"migrated_{_slug(vm, 40)}"
    reg = _empty_registry()
    reg["index_version"] = 1
    reg["active_generation"] = {
        "generation_id": gid,
        "chunks_collection": chunks,
        "summaries_collection": summaries,
        "activated_at": activated_at,
        "embed_model": None,
        "documents_count": None,
        "nodes_count": None,
        "summary_documents_count": None,
    }
    logger.info(
        "Migrated index registry from legacy active_index.json | generation_id=%s | chunks=%s",
        gid,
        chunks,
    )
    return reg


def _write_registry_disk_nolock(data: dict[str, Any]) -> None:
    """Assume FileLock already held. Atomic replace."""
    data = dict(data)
    data["schema_version"] = SCHEMA_VERSION
    tmp = REGISTRY_PATH.with_suffix(REGISTRY_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, REGISTRY_PATH)


def _load_registry_disk_nolock() -> dict[str, Any]:
    """Read registry file; if missing, migrate legacy or default. Caller must hold lock for writes after migrate."""
    if REGISTRY_PATH.exists():
        try:
            raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — registry file may have any JSON/IO corruption; return empty.
            logger.warning("Failed to read index registry | path=%s | error=%s", REGISTRY_PATH, exc)
            return copy.deepcopy(_empty_registry())
        if not isinstance(raw, dict):
            return copy.deepcopy(_empty_registry())
        if int(raw.get("schema_version") or 0) != SCHEMA_VERSION:
            base = _empty_registry()
            base.update(raw)
            base["schema_version"] = SCHEMA_VERSION
            base["index_version"] = int(raw.get("index_version") or 0)
            return base
        return raw

    from app.config import BASE_DIR, HOME_RAG_HOME

    legacy_registry = BASE_DIR / "index_registry.json"
    if (
        legacy_registry != REGISTRY_PATH
        and legacy_registry.exists()
        and HOME_RAG_HOME != BASE_DIR
    ):
        try:
            raw = json.loads(legacy_registry.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — migration best-effort only.
            logger.warning(
                "Failed to migrate index registry from code repo | from=%s | error=%s",
                legacy_registry,
                exc,
            )
            raw = None
        if isinstance(raw, dict):
            _write_registry_disk_nolock(raw)
            logger.info(
                "Migrated index_registry from code repo to HOME_RAG_HOME | from=%s | to=%s",
                legacy_registry,
                REGISTRY_PATH,
            )
            return raw

    migrated = _migrate_from_legacy_active_index()
    if migrated is not None:
        _write_registry_disk_nolock(migrated)
        return migrated

    return copy.deepcopy(_empty_registry())


def load_registry() -> dict[str, Any]:
    """Thread-safe read; returns a deep copy."""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(REGISTRY_LOCK_PATH), timeout=30)
    with lock:
        return copy.deepcopy(_load_registry_disk_nolock())


def save_registry_atomic(data: dict[str, Any]) -> None:
    """Write registry atomically with exclusive lock."""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(REGISTRY_LOCK_PATH), timeout=60)
    with lock:
        _write_registry_disk_nolock(data)
    logger.info(
        "Index registry saved | index_version=%s | active=%s",
        data.get("index_version"),
        (data.get("active_generation") or {}).get("chunks_collection"),
    )


@dataclass
class ActiveGenerationView:
    generation_id: str
    chunks_collection: str
    summaries_collection: str
    activated_at: str | None
    embed_model: str | None = None
    documents_count: int | None = None
    nodes_count: int | None = None
    summary_documents_count: int | None = None


def get_active_generation_view() -> ActiveGenerationView:
    reg = load_registry()
    ag = reg.get("active_generation") or {}
    s = get_settings()
    chunks = str(ag.get("chunks_collection") or "").strip() or s.collection_name
    summaries = str(ag.get("summaries_collection") or "").strip() or s.summary_collection_name
    gid = str(ag.get("generation_id") or "").strip() or "legacy"
    act = ag.get("activated_at")
    if act is not None:
        act = str(act)
    return ActiveGenerationView(
        generation_id=gid,
        chunks_collection=chunks,
        summaries_collection=summaries,
        activated_at=act,
        embed_model=ag.get("embed_model"),
        documents_count=ag.get("documents_count"),
        nodes_count=ag.get("nodes_count"),
        summary_documents_count=ag.get("summary_documents_count"),
    )


def get_active_collection_names() -> tuple[str, str]:
    v = get_active_generation_view()
    return v.chunks_collection, v.summaries_collection


def to_active_index_state_dict() -> dict[str, Any]:
    """Shape compatible with legacy load_active_index_state consumers."""
    reg = load_registry()
    ag = reg.get("active_generation") or {}
    s = get_settings()
    chunks = str(ag.get("chunks_collection") or "").strip() or s.collection_name
    summaries = str(ag.get("summaries_collection") or "").strip() or s.summary_collection_name
    gid = str(ag.get("generation_id") or "").strip() or "legacy"
    act = ag.get("activated_at")
    if act is not None:
        act = str(act)
    version_marker = f"{chunks}:{act}" if act else gid
    return {
        "collection_name": chunks,
        "summary_collection_name": summaries,
        "version_marker": version_marker,
        "activated_at": act,
        "generation_id": gid,
        "index_version": int(reg.get("index_version") or 0),
    }


def activate_staging_generation(
    *,
    chunks_collection: str,
    summaries_collection: str,
    embed_model: str | None = None,
    documents_count: int | None = None,
    nodes_count: int | None = None,
    summary_documents_count: int | None = None,
) -> dict[str, Any]:
    """
    Promote staging collections to active: bump index_version, move current active to previous.
    Returns the new active_generation dict (flattened for logging).
    """
    lock = FileLock(str(REGISTRY_LOCK_PATH), timeout=60)
    with lock:
        reg = _load_registry_disk_nolock()
        prev = reg.get("active_generation")
        activated_at = _utc_now_iso()
        new_gid = _slug(f"gen_{chunks_collection}_{activated_at}", 56)
        new_active = {
            "generation_id": new_gid,
            "chunks_collection": str(chunks_collection).strip(),
            "summaries_collection": str(summaries_collection).strip(),
            "activated_at": activated_at,
            "embed_model": embed_model,
            "documents_count": documents_count,
            "nodes_count": nodes_count,
            "summary_documents_count": summary_documents_count,
        }
        reg["previous_generation"] = prev
        reg["active_generation"] = new_active
        reg["staging_generation"] = None
        reg["last_failed_generation"] = None
        reg["index_version"] = int(reg.get("index_version") or 0) + 1
        _write_registry_disk_nolock(reg)
    logger.info(
        "Staging generation activated | index_version=%s | chunks=%s",
        reg["index_version"],
        new_active["chunks_collection"],
    )
    return new_active


def activate_reset_generation(
    *,
    chunks_collection: str,
    summaries_collection: str,
    embed_model: str | None = None,
    documents_count: int | None = None,
    nodes_count: int | None = None,
    summary_documents_count: int | None = None,
) -> dict[str, Any]:
    """After reset=True full rebuild into canonical collection names."""
    lock = FileLock(str(REGISTRY_LOCK_PATH), timeout=60)
    with lock:
        reg = _load_registry_disk_nolock()
        prev = reg.get("active_generation")
        activated_at = _utc_now_iso()
        new_gid = _slug(f"reset_{chunks_collection}_{activated_at}", 56)
        new_active = {
            "generation_id": new_gid,
            "chunks_collection": str(chunks_collection).strip(),
            "summaries_collection": str(summaries_collection).strip(),
            "activated_at": activated_at,
            "embed_model": embed_model,
            "documents_count": documents_count,
            "nodes_count": nodes_count,
            "summary_documents_count": summary_documents_count,
        }
        reg["previous_generation"] = prev
        reg["active_generation"] = new_active
        reg["staging_generation"] = None
        reg["last_failed_generation"] = None
        reg["index_version"] = int(reg.get("index_version") or 0) + 1
        _write_registry_disk_nolock(reg)
    return new_active


def mark_activation_failed(
    *,
    chunks_collection: str | None = None,
    summaries_collection: str | None = None,
    error: str | None = None,
) -> None:
    """Record failed staging activation without changing active generation."""
    lock = FileLock(str(REGISTRY_LOCK_PATH), timeout=60)
    with lock:
        reg = _load_registry_disk_nolock()
        reg["last_failed_generation"] = {
            "chunks_collection": chunks_collection,
            "summaries_collection": summaries_collection,
            "failed_at": _utc_now_iso(),
            "error": (error or "")[:2000],
        }
        _write_registry_disk_nolock(reg)
    logger.warning(
        "Index activation failed (active unchanged) | error=%s | staging_chunks=%s",
        error,
        chunks_collection,
    )


def adopt_discovered_collections(chunks_collection: str, summaries_collection: str) -> None:
    """Persist Chroma-discovered collection names when registry still points at defaults."""
    lock = FileLock(str(REGISTRY_LOCK_PATH), timeout=30)
    with lock:
        reg = _load_registry_disk_nolock()
        ag = dict(reg.get("active_generation") or {})
        if ag.get("activated_at"):
            return
        current_chunks = str(ag.get("chunks_collection") or "").strip()
        current_summaries = str(ag.get("summaries_collection") or "").strip()
        if current_chunks == chunks_collection and current_summaries == summaries_collection:
            return
        ag["chunks_collection"] = chunks_collection
        ag["summaries_collection"] = summaries_collection
        reg["active_generation"] = ag
        if int(reg.get("index_version") or 0) == 0:
            reg["index_version"] = 1
        _write_registry_disk_nolock(reg)
    logger.info(
        "Index registry adopted discovered Chroma collections | chunks=%s | summaries=%s",
        chunks_collection,
        summaries_collection,
    )


def get_index_version_public() -> dict[str, Any]:
    """Payload for GET /index/version and stats."""
    reg = load_registry()
    v = get_active_generation_view()
    return {
        "index_version": int(reg.get("index_version") or 0),
        "generation_id": v.generation_id,
        "chunks_collection": v.chunks_collection,
        "summaries_collection": v.summaries_collection,
        "activated_at": v.activated_at,
        "last_failed": reg.get("last_failed_generation"),
    }
