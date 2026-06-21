"""
Content hashes and partial reindex helpers (iteration 16 tail).

SHA-256 over normalized extracted text per doc_id; persisted next to Chroma DB.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from app.logging_config import setup_logging

logger = setup_logging()

SCHEMA_VERSION = 1
_CHROMA_ID_BATCH = 80
_FILE_MANIFEST_SCHEMA_VERSION = 1


def content_hash_state_path(chroma_dir: Path) -> Path:
    return chroma_dir / "ingestion_content_hashes.json"


def build_file_manifest(data_dir: Path, supported_exts: set[str] | frozenset[str]) -> dict[str, Any]:
    """Cheap file-level fingerprint used before expensive PDF/HTML extraction."""
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(p for p in data_dir.rglob("*") if p.suffix.lower() in supported_exts):
        try:
            st = path.stat()
            rel = path.relative_to(data_dir).as_posix()
        except OSError as exc:
            logger.warning("ingestion_file_manifest_stat_failed | path=%s | error=%s", path, exc)
            continue
        files[rel] = {
            "size": int(st.st_size),
            "mtime_ns": int(st.st_mtime_ns),
            "ext": path.suffix.lower(),
        }
    return {
        "schema_version": _FILE_MANIFEST_SCHEMA_VERSION,
        "files": files,
    }


def file_manifest_matches(stored: dict[str, Any] | None, current_manifest: dict[str, Any]) -> bool:
    if not stored:
        return False
    if int(stored.get("schema_version") or 0) != _FILE_MANIFEST_SCHEMA_VERSION:
        return False
    return stored.get("files") == current_manifest.get("files")


def can_skip_ingest_without_parsing(
    *,
    reset: bool,
    build_to_staging: bool,
    enable_partial_reindex: bool,
    embed_model: str,
    retrieval_fingerprint: str,
    current_file_manifest: dict[str, Any],
    stored: dict[str, Any] | None,
) -> bool:
    """True when file/settings fingerprints prove the active index is already current."""
    if reset or not build_to_staging or not enable_partial_reindex:
        return False
    if not stored:
        return False
    if str(stored.get("embed_model") or "") != embed_model:
        return False
    if str(stored.get("retrieval_fingerprint") or "") != retrieval_fingerprint:
        return False
    hashes = stored.get("hashes")
    if not isinstance(hashes, dict) or not hashes:
        return False
    return file_manifest_matches(stored.get("file_manifest"), current_file_manifest)


def compute_retrieval_fingerprint(split_strategy: str, chunk_size: int, chunk_overlap: int, window_size: int) -> str:
    raw = f"{split_strategy}|{chunk_size}|{chunk_overlap}|{window_size}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def compute_doc_content_hashes(documents: list[Any]) -> dict[str, str]:
    """Stable hash per doc_id after load + expand + metadata (before LLM enrichment)."""
    groups: dict[str, list[Document]] = {}
    for doc in documents:
        doc_id = str((doc.metadata or {}).get("doc_id") or "").strip()
        if not doc_id:
            continue
        groups.setdefault(doc_id, []).append(doc)

    out: dict[str, str] = {}
    for doc_id, group in groups.items():

        def _sort_key(d: Any) -> tuple[str, str]:
            m = d.metadata or {}
            return (str(m.get("section_path") or ""), str(m.get("section_title") or ""))

        sorted_group = sorted(group, key=_sort_key)
        parts: list[str] = []
        for d in sorted_group:
            text = (d.text or "").strip()
            if text:
                parts.append(text)
        combined = "\n\n".join(parts)
        normalized = "\n".join(line.rstrip() for line in combined.splitlines()).strip()
        out[doc_id] = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return out


def load_content_hash_state(chroma_dir: Path) -> dict[str, Any] | None:
    path = content_hash_state_path(chroma_dir)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - unreadable json is logged and returns None gracefully
        logger.warning("ingestion_content_hashes unreadable | path=%s | error=%s", path, exc)
        return None
    if not isinstance(raw, dict):
        return None
    if int(raw.get("schema_version") or 0) != SCHEMA_VERSION:
        return None
    hashes = raw.get("hashes")
    if not isinstance(hashes, dict):
        return None
    return raw


def save_content_hash_state(
    chroma_dir: Path,
    *,
    embed_model: str,
    retrieval_fingerprint: str,
    hashes: dict[str, str],
    file_manifest: dict[str, Any] | None = None,
    source_fragments: int | None = None,
    nodes_count: int | None = None,
) -> None:
    chroma_dir.mkdir(parents=True, exist_ok=True)
    path = content_hash_state_path(chroma_dir)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "embed_model": embed_model,
        "retrieval_fingerprint": retrieval_fingerprint,
        "hashes": dict(sorted(hashes.items())),
    }
    if file_manifest is not None:
        payload["file_manifest"] = file_manifest
    if source_fragments is not None:
        payload["source_fragments"] = max(0, int(source_fragments))
    if nodes_count is not None:
        payload["nodes_count"] = max(0, int(nodes_count))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def plan_partial_reindex(
    *,
    reset: bool,
    build_to_staging: bool,
    enable_partial_reindex: bool,
    embed_model: str,
    retrieval_fingerprint: str,
    current_hashes: dict[str, str],
    stored: dict[str, Any] | None,
) -> tuple[bool, set[str], set[str]]:
    """
    Returns (use_partial, unchanged_doc_ids, dirty_doc_ids).
    When use_partial is False, dirty_doc_ids is all doc_ids in current_hashes (full rebuild semantics).
    """
    all_ids = set(current_hashes.keys())
    if reset or not build_to_staging or not enable_partial_reindex:
        return False, set(), all_ids
    if not stored:
        return False, set(), all_ids
    if str(stored.get("embed_model") or "") != embed_model:
        return False, set(), all_ids
    if str(stored.get("retrieval_fingerprint") or "") != retrieval_fingerprint:
        return False, set(), all_ids
    prev = stored.get("hashes") or {}
    if not isinstance(prev, dict):
        return False, set(), all_ids
    unchanged: set[str] = set()
    for doc_id, h in current_hashes.items():
        if prev.get(doc_id) == h:
            unchanged.add(doc_id)
    dirty = all_ids - unchanged
    if not unchanged:
        return False, set(), dirty
    return True, unchanged, dirty


def _sanitize_metadata(meta: dict[str, Any] | None) -> dict[str, Any]:
    if not meta:
        return {}
    out: dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            out[str(k)] = str(v)
    return out


def _node_content_metadata(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Nested node metadata from a serialized LlamaIndex `_node_content` payload."""
    if not meta:
        return {}
    node_content = meta.get("_node_content")
    if not isinstance(node_content, str) or not node_content:
        return {}
    try:
        payload = json.loads(node_content)
    except (TypeError, ValueError):
        return {}
    nested = payload.get("metadata") if isinstance(payload, dict) else None
    return nested if isinstance(nested, dict) else {}


def _stored_metadata_doc_id(meta: dict[str, Any] | None) -> str:
    """Read the stable source path from Chroma or a LlamaIndex node payload."""
    if not meta:
        return ""
    direct = str(meta.get("relative_path") or "").strip()
    if direct:
        return direct
    nested = _node_content_metadata(meta)
    return str(nested.get("relative_path") or nested.get("doc_id") or "").strip()


def copy_chroma_vectors_by_doc_ids(
    client: Any,
    source_collection_name: str,
    target_collection: Any,
    doc_ids: set[str],
) -> tuple[int, set[str]]:
    """Copy all vectors whose stable doc id (relative_path) is in doc_ids from source into target.

    Returns (copied_vector_count, covered_doc_ids). Callers must compare covered_doc_ids
    against the requested set: a collection can mix nodes with top-level `relative_path`
    and nodes whose metadata lives only in `_node_content`, so a non-zero copy count
    does not prove every requested document was copied.
    """
    if not doc_ids:
        return 0, set()
    source = client.get_collection(source_collection_name)
    ids_list = sorted(doc_ids)
    total = 0
    covered: set[str] = set()
    added_ids: set[str] = set()
    for i in range(0, len(ids_list), _CHROMA_ID_BATCH):
        batch = ids_list[i : i + _CHROMA_ID_BATCH]
        res = source.get(
            where={"relative_path": {"$in": batch}},
            include=["embeddings", "documents", "metadatas"],
        )
        ids = res.get("ids") or []
        if not ids:
            continue
        embeddings = res.get("embeddings")
        documents = res.get("documents")
        metadatas = res.get("metadatas")
        if embeddings is None or len(embeddings) != len(ids):
            logger.warning(
                "chroma_copy_missing_embeddings | source=%s | batch=%s",
                source_collection_name,
                len(batch),
            )
            continue
        docs_list = documents if documents is not None else [""] * len(ids)
        meta_list = metadatas if metadatas is not None else [{}] * len(ids)
        sanitized = [_sanitize_metadata(m if isinstance(m, dict) else {}) for m in meta_list]
        target_collection.add(ids=ids, embeddings=embeddings, documents=docs_list, metadatas=sanitized)
        total += len(ids)
        added_ids.update(ids)
        for m in meta_list:
            if isinstance(m, dict):
                rel = str(m.get("relative_path") or "").strip()
                if rel:
                    covered.add(rel)

    missing = doc_ids - covered
    if missing:
        # Some LlamaIndex versions keep user metadata only in `_node_content`,
        # which makes Chroma's metadata filter unable to see `relative_path`.
        page_size = 1000
        for offset in range(0, source.count(), page_size):
            res = source.get(
                limit=page_size,
                offset=offset,
                include=["embeddings", "documents", "metadatas"],
            )
            ids = res.get("ids") or []
            embeddings = res.get("embeddings")
            documents = res.get("documents")
            metadatas = res.get("metadatas") or []
            if embeddings is None or len(embeddings) != len(ids):
                logger.warning(
                    "chroma_copy_scan_page_skipped | source=%s | offset=%s",
                    source_collection_name,
                    offset,
                )
                continue
            indexes = [
                index
                for index, metadata in enumerate(metadatas)
                if ids[index] not in added_ids and _stored_metadata_doc_id(metadata) in missing
            ]
            if not indexes:
                continue
            target_collection.add(
                ids=[ids[index] for index in indexes],
                embeddings=[embeddings[index] for index in indexes],
                documents=[documents[index] for index in indexes] if documents is not None else [""] * len(indexes),
                metadatas=[_sanitize_metadata(metadatas[index]) for index in indexes],
            )
            total += len(indexes)
            added_ids.update(ids[index] for index in indexes)
            covered.update(_stored_metadata_doc_id(metadatas[index]) for index in indexes)
            if not (missing - covered):
                break
        missing = doc_ids - covered
    if missing:
        logger.warning(
            "chroma_copy_doc_ids_uncovered | source=%s | missing=%s",
            source_collection_name,
            sorted(missing),
        )
    return total, covered


_MERGE_KEYS_FROM_CHROMA = frozenset({"topic", "key_concepts", "concepts", "doc_type", "difficulty"})


def _extract_merge_metadata(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Merge keys from top-level Chroma metadata, else from the nested `_node_content` payload."""
    if not isinstance(meta, dict) or not meta:
        return {}
    merged = {k: meta[k] for k in _MERGE_KEYS_FROM_CHROMA if k in meta and meta[k] is not None}
    if merged:
        return merged
    nested = _node_content_metadata(meta)
    return {k: nested[k] for k in _MERGE_KEYS_FROM_CHROMA if k in nested and nested[k] is not None}


def fetch_merge_metadata_for_doc_ids(
    client: Any,
    collection_name: str,
    doc_ids: set[str],
) -> dict[str, dict[str, Any]]:
    """Sample one chunk per doc_id from active index to restore LLM metadata for unchanged docs (graph rebuild)."""
    if not doc_ids:
        return {}
    col = client.get_collection(collection_name)
    out: dict[str, dict[str, Any]] = {}
    for doc_id in doc_ids:
        try:
            res = col.get(where={"relative_path": doc_id}, limit=1, include=["metadatas"])
            metas = res.get("metadatas") or []
            if not metas or not metas[0]:
                continue
            merged = _extract_merge_metadata(metas[0])
            if merged:
                out[doc_id] = merged
        except Exception as _exc:  # noqa: BLE001
            logger.debug("fetch_merge_metadata_where_failed | doc_id=%s | error=%s", doc_id, _exc)
            continue
    missing = doc_ids - set(out)
    if missing:
        # Same `_node_content`-only layout as in copy_chroma_vectors_by_doc_ids:
        # the where-filter cannot see relative_path, so scan and match by parsed payload.
        try:
            page_size = 1000
            for offset in range(0, col.count(), page_size):
                res = col.get(limit=page_size, offset=offset, include=["metadatas"])
                for meta in res.get("metadatas") or []:
                    did = _stored_metadata_doc_id(meta)
                    if did not in missing or did in out:
                        continue
                    merged = _extract_merge_metadata(meta)
                    if merged:
                        out[did] = merged
                if not (missing - set(out)):
                    break
        except Exception as _exc:  # noqa: BLE001 - merge metadata is best-effort, graph rebuild survives without it.
            logger.debug("fetch_merge_metadata_scan_failed | error=%s", _exc)
    return out


def apply_merge_metadata_to_documents(documents: list[Any], merge_by_doc: dict[str, dict[str, Any]]) -> None:
    for doc in documents:
        doc_id = str((doc.metadata or {}).get("doc_id") or "").strip()
        extra = merge_by_doc.get(doc_id)
        if not extra:
            continue
        doc.metadata = dict(doc.metadata or {})
        doc.metadata.update(extra)
