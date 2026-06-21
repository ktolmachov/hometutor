import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore

from app.chroma_vector_backend import get_default_chroma_backend
from app.retrieval_cache_discovery import (
    _chroma_dir,
    _collection_count,
    _require_chroma_collection as _disc_require_collection,
    _resolve_active_collection_names as _disc_resolve_collections,
    _settings,
)
from app.hybrid_retrieval import invalidate_bm25_cache
from app.index_diff import get_index_embed_model
from app.graph_generation_paths import promote_staging_bundle
from app.index_registry import activate_staging_generation, mark_activation_failed
from app.knowledge_graph import invalidate_knowledge_graph_singleton
from app.index_state import get_active_collection_names, load_active_index_state
from app.logging_config import setup_logging
from app.provider import get_embed_model, get_llm, get_quiz_llm

logger = setup_logging()
OPENAI_API_KEY = None

_lock = threading.Lock()
_reindex_condition = threading.Condition()
_reindex_in_progress = False

REINDEX_WAIT_TIMEOUT_SEC = 300

_cached_client = None
_cached_collection = None
_cached_vector_store = None
_cached_storage_context = None
_cached_embed_model = None
_cached_llm = None
_cached_quiz_llm = None
_cached_index = None
_cached_summary_collection = None
_cached_summary_vector_store = None
_cached_summary_storage_context = None
_cached_summary_index = None
_cached_empty = False  # negative-result cache: True after first EmptyIndexError until clear


@dataclass
class CacheEntry:
    engine: Any
    created_at: float
    last_accessed: float


_query_engine_cache: "OrderedDict[Any, CacheEntry]" = OrderedDict()

_cache_stats = {
    "hits": 0,
    "misses": 0,
    "evictions": 0,
    "expired": 0,
}

_latency_stats = {
    "hit_count": 0,
    "miss_count": 0,
    "hit_total_ms": 0.0,
    "miss_total_ms": 0.0,
    "last_hit_latency_ms": None,
    "last_miss_latency_ms": None,
}


class ReindexInProgressError(RuntimeError):
    """Raised when retrieval is attempted while reindex is still running."""


class EmptyIndexError(RuntimeError):
    """Raised when the Chroma collection has no indexed documents."""


class EmbedModelMismatchError(RuntimeError):
    """Raised when index was built with a different embed model than current settings."""


def _mark_index_empty() -> None:
    global _cached_empty
    _cached_empty = True


def _raise_empty_index(*, chroma_dir: Any, collection_name: str | None = None) -> None:
    _mark_index_empty()
    if collection_name:
        logger.warning(
            "Chroma collection does not exist | collection=%s | chroma_dir=%s",
            collection_name,
            chroma_dir,
        )
    raise EmptyIndexError("Индекс пуст. Запустите индексацию: POST /reindex") from None


def _resolve_active_collection_names(
    client: Any,
    chunks_name: str,
    summary_name: str,
    *,
    chroma_dir: Any,
) -> tuple[str, str]:
    return _disc_resolve_collections(
        client, chunks_name, summary_name, chroma_dir=chroma_dir, raise_empty_fn=_raise_empty_index
    )


def _require_chroma_collection(client: Any, collection_name: str, *, chroma_dir: Any) -> Any:
    return _disc_require_collection(
        client, collection_name, chroma_dir=chroma_dir, raise_empty_fn=_raise_empty_index
    )


def _now() -> float:
    return time.time()


def _is_expired(entry: CacheEntry) -> bool:
    return (_now() - entry.created_at) > _settings().query_engine_ttl_sec


def _purge_expired_locked():
    expired_keys = []
    for key, entry in list(_query_engine_cache.items()):
        if _is_expired(entry):
            expired_keys.append(key)

    for key in expired_keys:
        _query_engine_cache.pop(key, None)
        _cache_stats["expired"] += 1

    if expired_keys:
        logger.info(
            "Expired query engines purged | count=%s | cache_size=%s",
            len(expired_keys),
            len(_query_engine_cache),
        )


def _evict_if_needed_locked():
    while len(_query_engine_cache) > _settings().query_engine_cache_size:
        evicted_key, _ = _query_engine_cache.popitem(last=False)
        _cache_stats["evictions"] += 1
        logger.info(
            "LRU eviction performed | evicted_key=%r | cache_size=%s",
            evicted_key,
            len(_query_engine_cache),
        )


def _record_hit_latency(latency_ms: float):
    _latency_stats["hit_count"] += 1
    _latency_stats["hit_total_ms"] += latency_ms
    _latency_stats["last_hit_latency_ms"] = round(latency_ms, 3)


def _record_miss_latency(latency_ms: float):
    _latency_stats["miss_count"] += 1
    _latency_stats["miss_total_ms"] += latency_ms
    _latency_stats["last_miss_latency_ms"] = round(latency_ms, 3)


def _avg(total: float, count: int):
    if count == 0:
        return None
    return round(total / count, 3)


def reindex_begin():
    global _reindex_in_progress
    with _reindex_condition:
        _reindex_in_progress = True
    logger.info("Reindex started: active index remains available while staging rebuild runs")


def try_reindex_begin() -> bool:
    global _reindex_in_progress
    with _reindex_condition:
        if _reindex_in_progress:
            return False
        _reindex_in_progress = True
    logger.info("Reindex started: active index remains available while staging rebuild runs")
    return True


def reindex_end():
    global _reindex_in_progress
    with _reindex_condition:
        _reindex_in_progress = False
        _reindex_condition.notify_all()
    logger.info("Reindex finished")


def is_reindex_in_progress() -> bool:
    with _reindex_condition:
        return _reindex_in_progress


def is_base_services_ready() -> bool:
    """Return True if base services (embedding model + index) are already cached.

    Used by bootstrap to skip heavy init when services haven't warmed up yet.
    """
    return _cached_index is not None


def wait_if_reindexing(timeout_sec: float = REINDEX_WAIT_TIMEOUT_SEC) -> None:
    with _reindex_condition:
        if not _reindex_in_progress:
            return
        logger.info("Reindex in progress, waiting up to %s sec...", timeout_sec)
        _reindex_condition.wait(timeout=timeout_sec)
        if _reindex_in_progress:
            raise ReindexInProgressError(
                "Переиндексация не завершилась за отведённое время. Повторите запрос позже."
            )


def get_active_index_state() -> dict[str, Any]:
    return load_active_index_state()


def activate_staging_index(
    collection_name: str,
    summary_collection_name: str,
) -> dict[str, Any]:
    client = get_default_chroma_backend(_chroma_dir()).get_client()
    try:
        collection = client.get_collection(collection_name)
        if collection.count() == 0:
            raise EmptyIndexError("Cannot activate an empty staging index")

        settings = _settings()
        if settings.enable_document_summaries:
            sc = client.get_collection(summary_collection_name)
            summary_docs = sc.count()
        else:
            summary_docs = None

        new_active = activate_staging_generation(
            chunks_collection=collection_name,
            summaries_collection=summary_collection_name,
            embed_model=settings.embed_model,
            documents_count=None,
            nodes_count=collection.count(),
            summary_documents_count=summary_docs,
        )
        generation_id = str(new_active.get("generation_id") or "")
        from app.knowledge_graph_bundle import (
            bind_promoted_course_graph,
            retarget_staging_bundle_generation,
        )

        retarget_staging_bundle_generation(collection_name, generation_id)
        if promote_staging_bundle(collection_name, generation_id):
            bind_promoted_course_graph(generation_id)
    except EmptyIndexError:
        mark_activation_failed(
            chunks_collection=collection_name,
            summaries_collection=summary_collection_name,
            error="empty_staging_index",
        )
        raise
    except Exception as exc:  # noqa: BLE001 — catch-all cleanup: record failure reason before re-raising.
        mark_activation_failed(
            chunks_collection=collection_name,
            summaries_collection=summary_collection_name,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise

    state = load_active_index_state()
    clear_retrieval_cache()
    invalidate_bm25_cache(clear_disk=True)
    logger.info(
        "Staging index activated | collection=%s | summary_collection=%s | version_marker=%s",
        state["collection_name"],
        state["summary_collection_name"],
        state["version_marker"],
    )
    return state


def clear_retrieval_cache():
    global _cached_client
    global _cached_collection
    global _cached_vector_store
    global _cached_storage_context
    global _cached_embed_model
    global _cached_llm
    global _cached_quiz_llm
    global _cached_index
    global _cached_summary_collection
    global _cached_summary_vector_store
    global _cached_summary_storage_context
    global _cached_summary_index
    global _query_engine_cache
    global _cached_empty

    with _lock:
        _cached_empty = False
        _cached_client = None
        _cached_collection = None
        _cached_vector_store = None
        _cached_storage_context = None
        _cached_embed_model = None
        _cached_llm = None
        _cached_quiz_llm = None
        _cached_index = None
        _cached_summary_collection = None
        _cached_summary_vector_store = None
        _cached_summary_storage_context = None
        _cached_summary_index = None
        _query_engine_cache = OrderedDict()

        _cache_stats["hits"] = 0
        _cache_stats["misses"] = 0
        _cache_stats["evictions"] = 0
        _cache_stats["expired"] = 0

        _latency_stats["hit_count"] = 0
        _latency_stats["miss_count"] = 0
        _latency_stats["hit_total_ms"] = 0.0
        _latency_stats["miss_total_ms"] = 0.0
        _latency_stats["last_hit_latency_ms"] = None
        _latency_stats["last_miss_latency_ms"] = None

    invalidate_bm25_cache()
    invalidate_knowledge_graph_singleton()
    from app.knowledge_service import invalidate_catalog_cache
    invalidate_catalog_cache()
    from app.index_diff import invalidate_index_stats_cache
    invalidate_index_stats_cache()
    from app.api_services import invalidate_readiness_cache
    invalidate_readiness_cache()
    logger.info("Retrieval cache cleared")


def get_cache_stats():
    settings = _settings()
    with _lock:
        _purge_expired_locked()

        return {
            "base_services_initialized": _cached_index is not None,
            "reindex_in_progress": is_reindex_in_progress(),
            "active_index_state": load_active_index_state(),
            "query_engine_cache_size": len(_query_engine_cache),
            "query_engine_cache_capacity": settings.query_engine_cache_size,
            "query_engine_ttl_sec": settings.query_engine_ttl_sec,
            "hits": _cache_stats["hits"],
            "misses": _cache_stats["misses"],
            "evictions": _cache_stats["evictions"],
            "expired": _cache_stats["expired"],
            "latency": {
                "hit_count": _latency_stats["hit_count"],
                "miss_count": _latency_stats["miss_count"],
                "hit_latency_avg_ms": _avg(_latency_stats["hit_total_ms"], _latency_stats["hit_count"]),
                "miss_latency_avg_ms": _avg(_latency_stats["miss_total_ms"], _latency_stats["miss_count"]),
                "last_hit_latency_ms": _latency_stats["last_hit_latency_ms"],
                "last_miss_latency_ms": _latency_stats["last_miss_latency_ms"],
            },
            "keys": [repr(k) for k in _query_engine_cache.keys()],
        }


def get_cached_client():
    """Return the already-warmed Chroma client if available, else None."""
    with _lock:
        return _cached_client


def get_cached_quiz_llm():
    """Один экземпляр LLM для квизов (как ``llm`` для RAG), создаётся вместе с base services."""
    return get_base_services()["quiz_llm"]


def get_base_services():
    global _cached_client
    global _cached_collection
    global _cached_vector_store
    global _cached_storage_context
    global _cached_embed_model
    global _cached_llm
    global _cached_quiz_llm
    global _cached_index
    global _cached_summary_collection
    global _cached_summary_vector_store
    global _cached_summary_storage_context
    global _cached_summary_index
    global _cached_empty

    with _lock:
        if _cached_empty:
            raise EmptyIndexError("Индекс пуст. Запустите индексацию: POST /reindex")
        if _cached_index is not None:
            return {
                "client": _cached_client,
                "collection": _cached_collection,
                "vector_store": _cached_vector_store,
                "storage_context": _cached_storage_context,
                "embed_model": _cached_embed_model,
                "llm": _cached_llm,
                "quiz_llm": _cached_quiz_llm,
                "index": _cached_index,
                "summary_collection": _cached_summary_collection,
                "summary_vector_store": _cached_summary_vector_store,
                "summary_storage_context": _cached_summary_storage_context,
                "summary_index": _cached_summary_index,
            }

        settings = _settings()
        effective_api_key = OPENAI_API_KEY or settings.openai_api_key
        if not effective_api_key:
            raise ValueError("OPENAI_API_KEY не найден в .env")

        index_embed_model = get_index_embed_model()
        if index_embed_model and index_embed_model != settings.embed_model:
            raise EmbedModelMismatchError(
                "Индекс был построен с другой EMBED_MODEL. "
                f"В индексе: {index_embed_model!r}, в .env: {settings.embed_model!r}. "
                "Запустите полную переиндексацию (POST /reindex), чтобы обновить вектора."
            )

        logger.info("Initializing retrieval base services...")

        chroma_dir = _chroma_dir()
        _cached_client = get_default_chroma_backend(_chroma_dir()).get_client()
        active_collection_name, active_summary_collection_name = get_active_collection_names()
        active_collection_name, active_summary_collection_name = _resolve_active_collection_names(
            _cached_client,
            active_collection_name,
            active_summary_collection_name,
            chroma_dir=chroma_dir,
        )
        _cached_collection = _require_chroma_collection(
            _cached_client,
            active_collection_name,
            chroma_dir=chroma_dir,
        )
        if _cached_collection.count() == 0:
            logger.warning(
                "Chroma collection is empty | collection=%s | chroma_dir=%s",
                active_collection_name,
                chroma_dir,
            )
            _raise_empty_index(chroma_dir=chroma_dir, collection_name=active_collection_name)

        _cached_vector_store = ChromaVectorStore(chroma_collection=_cached_collection)
        _cached_storage_context = StorageContext.from_defaults(vector_store=_cached_vector_store)

        _cached_embed_model = get_embed_model()
        _cached_llm = get_llm()
        _cached_quiz_llm = get_quiz_llm()

        _cached_index = VectorStoreIndex.from_vector_store(
            vector_store=_cached_vector_store,
            storage_context=_cached_storage_context,
            embed_model=_cached_embed_model,
        )

        if settings.enable_document_summaries and _collection_count(
            _cached_client, active_summary_collection_name
        ) is not None:
            _cached_summary_collection = _require_chroma_collection(
                _cached_client,
                active_summary_collection_name,
                chroma_dir=chroma_dir,
            )
            _cached_summary_vector_store = ChromaVectorStore(
                chroma_collection=_cached_summary_collection
            )
            _cached_summary_storage_context = StorageContext.from_defaults(
                vector_store=_cached_summary_vector_store
            )
            _cached_summary_index = VectorStoreIndex.from_vector_store(
                vector_store=_cached_summary_vector_store,
                storage_context=_cached_summary_storage_context,
                embed_model=_cached_embed_model,
            )
        elif settings.enable_document_summaries:
            logger.warning(
                "Summary collection unavailable; topics catalog will be empty | collection=%s",
                active_summary_collection_name,
            )

        logger.info("Retrieval base services initialized successfully")

        return {
            "client": _cached_client,
            "collection": _cached_collection,
            "vector_store": _cached_vector_store,
            "storage_context": _cached_storage_context,
            "embed_model": _cached_embed_model,
            "llm": _cached_llm,
            "quiz_llm": _cached_quiz_llm,
            "index": _cached_index,
            "summary_collection": _cached_summary_collection,
            "summary_vector_store": _cached_summary_vector_store,
            "summary_storage_context": _cached_summary_storage_context,
            "summary_index": _cached_summary_index,
        }


def set_cached_query_engine(cache_key, engine):
    started = time.perf_counter()
    settings = _settings()

    with _lock:
        _purge_expired_locked()

        entry = CacheEntry(
            engine=engine,
            created_at=_now(),
            last_accessed=_now(),
        )
        _query_engine_cache[cache_key] = entry
        _query_engine_cache.move_to_end(cache_key)

        _evict_if_needed_locked()

        latency_ms = (time.perf_counter() - started) * 1000

        logger.info(
            "Query engine cached | cache_key=%r | cache_size=%s | ttl_sec=%s | capacity=%s | store_latency_ms=%.3f",
            cache_key,
            len(_query_engine_cache),
            settings.query_engine_ttl_sec,
            settings.query_engine_cache_size,
            latency_ms,
        )


def get_query_engine_cache_result(cache_key):
    started = time.perf_counter()

    with _lock:
        _purge_expired_locked()

        entry = _query_engine_cache.get(cache_key)
        if entry is None:
            _cache_stats["misses"] += 1
            latency_ms = (time.perf_counter() - started) * 1000
            _record_miss_latency(latency_ms)

            logger.info(
                "Query engine cache miss | cache_key=%r | cache_size=%s | latency_ms=%.3f",
                cache_key,
                len(_query_engine_cache),
                latency_ms,
            )
            return {
                "engine": None,
                "cache_hit": False,
                "cache_latency_ms": round(latency_ms, 3),
            }

        if _is_expired(entry):
            _query_engine_cache.pop(cache_key, None)
            _cache_stats["misses"] += 1
            _cache_stats["expired"] += 1
            latency_ms = (time.perf_counter() - started) * 1000
            _record_miss_latency(latency_ms)

            logger.info(
                "Query engine cache expired | cache_key=%r | cache_size=%s | latency_ms=%.3f",
                cache_key,
                len(_query_engine_cache),
                latency_ms,
            )
            return {
                "engine": None,
                "cache_hit": False,
                "cache_latency_ms": round(latency_ms, 3),
            }

        entry.last_accessed = _now()
        _query_engine_cache.move_to_end(cache_key)
        _cache_stats["hits"] += 1
        latency_ms = (time.perf_counter() - started) * 1000
        _record_hit_latency(latency_ms)

        logger.info(
            "Query engine cache hit | cache_key=%r | cache_size=%s | latency_ms=%.3f",
            cache_key,
            len(_query_engine_cache),
            latency_ms,
        )
        return {
            "engine": entry.engine,
            "cache_hit": True,
            "cache_latency_ms": round(latency_ms, 3),
        }
