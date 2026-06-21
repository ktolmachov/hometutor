"""Persisted extracted-document cache for ingestion (split from ``app.ingestion``)."""

import json
import os
from pathlib import Path

from llama_index.core import Document

from app.config import DATA_DIR
from app.logging_config import setup_logging

logger = setup_logging()
EXTRACTED_DOCUMENT_CACHE_NAME = "ingestion_extracted_documents.json"
_EXTRACTED_DOCUMENT_CACHE_SCHEMA = 1


def _extracted_document_cache_path(chroma_dir: Path) -> Path:
    return chroma_dir / EXTRACTED_DOCUMENT_CACHE_NAME


def _document_cache_key(doc: Document) -> str:
    metadata = doc.metadata or {}
    rel = str(metadata.get("relative_path") or metadata.get("doc_id") or "").strip()
    if rel:
        return rel
    file_path_raw = str(metadata.get("file_path") or "").strip()
    if not file_path_raw:
        return ""
    try:
        return Path(file_path_raw).relative_to(DATA_DIR).as_posix()
    except ValueError:
        return Path(file_path_raw).name


def _json_safe_cache_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe_cache_value(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _json_safe_cache_value(v) for k, v in value.items()}
    return str(value)


def _serialize_document_for_cache(doc: Document) -> dict[str, object]:
    return {
        "text": doc.text or "",
        "metadata": _json_safe_cache_value(dict(doc.metadata or {})),
        "excluded_embed_metadata_keys": list(doc.excluded_embed_metadata_keys or []),
        "excluded_llm_metadata_keys": list(doc.excluded_llm_metadata_keys or []),
    }


def _deserialize_document_from_cache(raw: dict[str, object]) -> Document | None:
    text = raw.get("text")
    metadata = raw.get("metadata")
    if not isinstance(text, str) or not isinstance(metadata, dict):
        return None
    return Document(
        text=text,
        metadata=metadata,
        excluded_embed_metadata_keys=list(raw.get("excluded_embed_metadata_keys") or []),
        excluded_llm_metadata_keys=list(raw.get("excluded_llm_metadata_keys") or []),
    )


def _load_extracted_document_cache(chroma_dir: Path) -> dict[str, object] | None:
    path = _extracted_document_cache_path(chroma_dir)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("extracted_document_cache_unreadable | path=%s | error=%s", path, exc)
        return None
    if not isinstance(raw, dict):
        return None
    if int(raw.get("schema_version") or 0) != _EXTRACTED_DOCUMENT_CACHE_SCHEMA:
        return None
    if not isinstance(raw.get("file_manifest"), dict) or not isinstance(raw.get("documents_by_file"), dict):
        return None
    return raw


def _save_extracted_document_cache(
    chroma_dir: Path,
    *,
    file_manifest: dict[str, object],
    documents: list[Document],
) -> None:
    docs_by_file: dict[str, list[dict[str, object]]] = {}
    for doc in documents:
        key = _document_cache_key(doc)
        if not key:
            continue
        docs_by_file.setdefault(key, []).append(_serialize_document_for_cache(doc))

    payload = {
        "schema_version": _EXTRACTED_DOCUMENT_CACHE_SCHEMA,
        "file_manifest": file_manifest,
        "documents_by_file": docs_by_file,
    }
    path = _extracted_document_cache_path(chroma_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
