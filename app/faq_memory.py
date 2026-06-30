"""
FAQ-память: Chroma collection + дедупликация по эмбеддингу (итерация 16 tail).

Legacy ``faq_memory.jsonl`` однократно импортируется при первом обращении, затем hot path — только Chroma.
"""

from __future__ import annotations

import json
import logging
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from chromadb.errors import ChromaError, NotFoundError
from filelock import FileLock, Timeout

from app.chroma_vector_backend import get_default_chroma_backend
from app.config import BASE_DIR, CHROMA_DIR, get_settings
from app.logging_config import setup_logging
from app.provider import normalize_openai_compatible_api_base


logger = setup_logging()

FAQ_MEMORY_PATH = Path(get_settings().faq_memory_path)

_migration_lock = Path(__file__).resolve().parent.parent / ".faq_chroma_migration.lock"
_faq_embed_unavailable_until = 0.0


def _chroma_persist_dir() -> Path:
    return CHROMA_DIR


def _get_embed_model():
    from app.provider import get_embed_model

    return get_embed_model()


def _is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower()
    return h in {"127.0.0.1", "localhost", "::1"} or h.endswith(".local")


def _loopback_tcp_reachable(api_base: str, *, timeout_sec: float) -> bool:
    parsed = urlparse(api_base)
    host = parsed.hostname or ""
    if not host or not _is_loopback_host(host):
        return True
    port = parsed.port or (443 if (parsed.scheme or "http").lower() == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def _faq_embed_circuit_open() -> bool:
    return time.monotonic() < _faq_embed_unavailable_until


def _record_faq_embed_failure(reason: str, error: Exception | None = None) -> None:
    global _faq_embed_unavailable_until
    settings = get_settings()
    cooldown = float(getattr(settings, "faq_embedding_failure_cooldown_sec", 60.0) or 0.0)
    if cooldown > 0:
        _faq_embed_unavailable_until = time.monotonic() + cooldown
    if error is None:
        logger.warning("FAQ embedding temporarily disabled | reason=%s | cooldown_sec=%s", reason, cooldown)
    else:
        logger.warning(
            "FAQ embedding temporarily disabled | reason=%s | cooldown_sec=%s | error=%s",
            reason,
            cooldown,
            error,
        )


def _faq_embedding_ready() -> bool:
    if _faq_embed_circuit_open():
        return False
    settings = get_settings()
    api_base = normalize_openai_compatible_api_base(str(getattr(settings, "embed_api_base_resolved", "") or ""))
    if not api_base:
        return True
    timeout = float(getattr(settings, "faq_embedding_probe_timeout_sec", 0.25) or 0.25)
    if _loopback_tcp_reachable(api_base, timeout_sec=timeout):
        return True
    _record_faq_embed_failure("loopback_unreachable")
    return False


def reset_faq_embed_circuit_for_tests() -> None:
    global _faq_embed_unavailable_until
    _faq_embed_unavailable_until = 0.0


def _distance_to_score(distance: float | None) -> float:
    """Chroma cosine space: distance = 1 - cosine_similarity для нормированных векторов."""
    if distance is None:
        return 0.0
    try:
        return max(0.0, min(1.0, 1.0 - float(distance)))
    except (TypeError, ValueError):
        return 0.0


def _get_faq_collection():
    settings = get_settings()
    backend = get_default_chroma_backend(_chroma_persist_dir())
    client = backend.get_client()
    name = settings.faq_memory_collection_name
    return backend.get_or_create_collection(
        client,
        name,
        metadata={"hnsw:space": "cosine"},
    )


def _sources_from_meta(meta: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    if not meta:
        return []
    raw = meta.get("sources_json")
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _migrate_jsonl_to_chroma_if_needed() -> None:
    """Однократный импорт строк из JSONL в Chroma (с блокировкой)."""
    if not FAQ_MEMORY_PATH.exists() or FAQ_MEMORY_PATH.stat().st_size == 0:
        return
    if not _faq_embedding_ready():
        logger.info("FAQ migration skipped: embedding endpoint unavailable")
        return

    backend = get_default_chroma_backend(_chroma_persist_dir())
    client = backend.get_client()
    settings = get_settings()
    name = settings.faq_memory_collection_name
    try:
        col = backend.get_collection(client, name)
        if col.count() > 0:
            FAQ_MEMORY_PATH.write_text("", encoding="utf-8")
            return
    except NotFoundError:
        pass
    except ChromaError as e:
        logger.warning("FAQ migration: chroma collection probe failed | error=%s", e)

    _migration_lock.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(_migration_lock):
        try:
            col = backend.get_collection(client, name)
            if col.count() > 0:
                FAQ_MEMORY_PATH.write_text("", encoding="utf-8")
                return
        except NotFoundError:
            pass
        except ChromaError as e:
            logger.warning("FAQ migration: chroma collection probe (locked) failed | error=%s", e)

        collection = backend.get_or_create_collection(
            client,
            name,
            metadata={"hnsw:space": "cosine"},
        )
        try:
            embed_model = _get_embed_model()
        except Exception as e:  # noqa: BLE001 - embed/network stack may fail opaquely; skip migration
            _record_faq_embed_failure("embed_model_unavailable", e)
            logger.error("FAQ migration: embed model unavailable | error=%s", e, exc_info=True)
            return

        lines: List[str] = []
        try:
            with open(FAQ_MEMORY_PATH, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
        except OSError as e:
            logger.warning("FAQ migration: read failed | path=%s | error=%s", FAQ_MEMORY_PATH, e)
            return

        ids: List[str] = []
        embeddings: List[List[float]] = []
        metadatas: List[Dict[str, Any]] = []
        documents: List[str] = []

        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            q = str(record.get("question") or "").strip()
            if not q:
                continue
            emb = record.get("embedding")
            if not isinstance(emb, list):
                try:
                    emb = embed_model.get_text_embedding(q)
                except Exception as ex:  # noqa: BLE001 - embedding provider errors are heterogeneous
                    _record_faq_embed_failure("migration_embed_failed", ex)
                    logger.error("FAQ migration: skip line (embed failed) | error=%s", ex, exc_info=True)
                    continue
            a = str(record.get("answer") or "")
            sources = record.get("sources") or []
            sid = str(record.get("id") or uuid.uuid4())
            ids.append(sid)
            embeddings.append(emb)
            metadatas.append(
                {
                    "answer": a[:32000],
                    "sources_json": json.dumps(sources, ensure_ascii=False)[:60000],
                }
            )
            documents.append(q)

        if ids:
            batch = 64
            for i in range(0, len(ids), batch):
                collection.add(
                    ids=ids[i : i + batch],
                    embeddings=embeddings[i : i + batch],
                    metadatas=metadatas[i : i + batch],
                    documents=documents[i : i + batch],
                )
            logger.info("FAQ migration: imported | lines=%s | collection=%s", len(ids), name)

        try:
            with open(FAQ_MEMORY_PATH, "w", encoding="utf-8") as out:
                out.write("")
        except OSError as e:
            logger.warning("FAQ migration: truncate jsonl failed | error=%s", e)


def save_interaction(question: str, answer: str, sources: List[Dict[str, Any]]) -> None:
    """Сохранить вопрос/ответ/источники в FAQ (Chroma), с дедупликацией."""
    if not _faq_embedding_ready():
        logger.info("FAQ save skipped: embedding endpoint unavailable")
        return
    _migrate_jsonl_to_chroma_if_needed()

    try:
        embed_model = _get_embed_model()
        embedding = embed_model.get_text_embedding(question)
    except Exception as e:  # noqa: BLE001 - embed stack may fail opaquely; skip save
        _record_faq_embed_failure("save_embed_failed", e)
        logger.error("FAQ: failed to embed question, skipping save | error=%s", e, exc_info=True)
        return

    settings = get_settings()
    collection = _get_faq_collection()

    try:
        near = collection.query(
            query_embeddings=[embedding],
            n_results=1,
            include=["distances"],
        )
        dists = near.get("distances") or []
        if dists and dists[0]:
            best = _distance_to_score(dists[0][0])
            if best >= settings.faq_dedup_min_score:
                logger.debug(
                    "FAQ: skip duplicate | score=%s | threshold=%s",
                    best,
                    settings.faq_dedup_min_score,
                )
                return
    except ChromaError as e:
        logger.warning("FAQ: dedup query failed, continuing with add | error=%s", e)

    q = (question or "").strip()
    meta = {
        "answer": (answer or "")[:32000],
        "sources_json": json.dumps(sources or [], ensure_ascii=False)[:60000],
    }
    rid = str(uuid.uuid4())
    try:
        collection.add(
            ids=[rid],
            embeddings=[embedding],
            metadatas=[meta],
            documents=[q],
        )
    except ChromaError as e:
        logger.warning("FAQ: chroma add failed | error=%s", e)


def find_similar_questions(
    question: str,
    top_k: int = 3,
    min_score: float = 0.7,
) -> List[Dict[str, Any]]:
    """Найти похожие вопросы по эмбеддингам (Chroma)."""
    if not _faq_embedding_ready():
        logger.info("FAQ search skipped: embedding endpoint unavailable")
        return []
    _migrate_jsonl_to_chroma_if_needed()

    try:
        embed_model = _get_embed_model()
        query_embedding = embed_model.get_text_embedding(question)
    except Exception as e:  # noqa: BLE001 - embed stack may fail opaquely; empty results
        _record_faq_embed_failure("search_embed_failed", e)
        logger.error("FAQ: failed to embed query, skipping search | error=%s", e, exc_info=True)
        return []

    collection = _get_faq_collection()
    try:
        if collection.count() == 0:
            return []
    except ChromaError as e:
        logger.warning("FAQ: collection count failed | error=%s", e)
        return []

    try:
        raw = collection.query(
            query_embeddings=[query_embedding],
            n_results=max(1, top_k),
            include=["distances", "metadatas", "documents"],
        )
    except ChromaError as e:
        logger.warning("FAQ: chroma query failed | error=%s", e)
        return []

    dists = (raw.get("distances") or [[]])[0]
    docs = (raw.get("documents") or [[]])[0]
    metas = (raw.get("metadatas") or [[]])[0]

    candidates: List[Dict[str, Any]] = []
    for i, dist in enumerate(dists):
        score = _distance_to_score(dist)
        if score < min_score:
            continue
        meta = metas[i] if i < len(metas) else {}
        doc_q = docs[i] if i < len(docs) else ""
        answer = ""
        if isinstance(meta, dict):
            answer = str(meta.get("answer") or "")
        candidates.append(
            {
                "question": doc_q,
                "answer": answer,
                "sources": _sources_from_meta(meta if isinstance(meta, dict) else None),
                "score": score,
            }
        )

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_k]


def clear_faq_memory_file() -> None:
    """Очистить FAQ: коллекция Chroma и legacy JSONL."""
    settings = get_settings()
    backend = get_default_chroma_backend(_chroma_persist_dir())
    client = backend.get_client()
    name = settings.faq_memory_collection_name
    backend.delete_collection(client, name)

    lock_path = Path(str(FAQ_MEMORY_PATH) + ".lock")
    FAQ_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(lock_path):
            FAQ_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            FAQ_MEMORY_PATH.write_text("", encoding="utf-8")
        logger.info("FAQ memory cleared | chroma_collection=%s | jsonl=%s", name, FAQ_MEMORY_PATH)
    except (OSError, Timeout) as e:
        logger.warning("FAQ: failed to clear jsonl | path=%s | error=%s", FAQ_MEMORY_PATH, e)
