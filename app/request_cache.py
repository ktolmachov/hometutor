"""Request caching and deduplication for LLM API calls (P0.2)."""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import sqlite3
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_llm_cache_hit_ctx: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "llm_cache_hit",
    default=None,
)


def reset_llm_cache_hit_flag() -> None:
    """Clear per-request cache-hit marker before an LLM call."""
    _llm_cache_hit_ctx.set(None)


def consume_llm_cache_hit() -> bool:
    """Return whether the last cache lookup was a hit; clears the marker."""
    value = _llm_cache_hit_ctx.get()
    _llm_cache_hit_ctx.set(None)
    return value is True


def _mark_cache_lookup(*, hit: bool) -> None:
    _llm_cache_hit_ctx.set(hit)


def _extract_response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    message = getattr(response, "message", None)
    content = getattr(message, "content", None) if message is not None else None
    if isinstance(content, str):
        return content
    if isinstance(response, dict):
        for key in ("text", "content", "message"):
            value = response.get(key)
            if isinstance(value, str):
                return value
    return json.dumps(response, default=str)


def _serialize_cached_response(response: Any) -> str:
    return json.dumps({"text": _extract_response_text(response)}, ensure_ascii=False)


def _deserialize_cached_response(raw: str) -> Any:
    try:
        from llama_index.core.base.llms.types import ChatMessage, ChatResponse
    except ImportError:  # pragma: no cover - llama_index is always installed in runtime.
        data = json.loads(raw)
        return {"text": data.get("text") or ""}

    data = json.loads(raw)
    text = str(data.get("text") or "")
    message = ChatMessage(role="assistant", content=text)
    return ChatResponse(message=message, text=text)


class RequestCache:
    """LRU cache for API requests with TTL (time-to-live)."""

    def __init__(
        self,
        maxsize: int = 100,
        ttl_seconds: int = 10,
        *,
        persist: bool = False,
        db_path: Path | str | None = None,
    ):
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self.persist = bool(persist)
        self.db_path = Path(db_path) if db_path else None
        self.cache: OrderedDict[str, Any] = OrderedDict()
        self.timestamps: dict[str, float] = {}
        self.hits = 0
        self.misses = 0
        if self.persist and self.db_path is not None:
            self._ensure_sqlite_schema()

    def _ensure_sqlite_schema(self) -> None:
        assert self.db_path is not None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path), timeout=5) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_request_cache (
                    request_hash TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    def _hash_request(self, model: str, messages: list[dict[str, Any]], **kwargs) -> str:
        request_dict = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature"),
            "max_tokens": kwargs.get("max_tokens"),
            "top_p": kwargs.get("top_p"),
        }
        request_str = json.dumps(request_dict, sort_keys=True, default=str)
        return hashlib.sha256(request_str.encode()).hexdigest()

    def _is_expired(self, request_hash: str) -> bool:
        timestamp = self.timestamps.get(request_hash)
        if timestamp is None:
            return True
        return time.time() - timestamp > self.ttl_seconds

    def _load_from_sqlite(self, request_hash: str) -> Any | None:
        if not self.persist or self.db_path is None:
            return None
        try:
            with sqlite3.connect(str(self.db_path), timeout=5) as conn:
                row = conn.execute(
                    "SELECT response_json, created_at FROM llm_request_cache WHERE request_hash = ?",
                    (request_hash,),
                ).fetchone()
        except sqlite3.Error as exc:  # noqa: BLE001 - cache store must not break LLM path.
            logger.warning("LLM cache sqlite read failed: %s", exc)
            return None
        if row is None:
            return None
        response_json, created_at = row
        if time.time() - float(created_at) > self.ttl_seconds:
            try:
                with sqlite3.connect(str(self.db_path), timeout=5) as conn:
                    conn.execute(
                        "DELETE FROM llm_request_cache WHERE request_hash = ?",
                        (request_hash,),
                    )
                    conn.commit()
            except sqlite3.Error:
                return None
            return None
        try:
            return _deserialize_cached_response(str(response_json))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("LLM cache sqlite payload invalid for %s: %s", request_hash[:8], exc)
            return None

    def _store_in_sqlite(self, request_hash: str, response: Any) -> None:
        if not self.persist or self.db_path is None:
            return
        try:
            payload = _serialize_cached_response(response)
            now = time.time()
            with sqlite3.connect(str(self.db_path), timeout=5) as conn:
                conn.execute(
                    """
                    INSERT INTO llm_request_cache (request_hash, response_json, created_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(request_hash) DO UPDATE SET
                        response_json = excluded.response_json,
                        created_at = excluded.created_at
                    """,
                    (request_hash, payload, now),
                )
                conn.execute(
                    "DELETE FROM llm_request_cache WHERE created_at < ?",
                    (now - self.ttl_seconds,),
                )
                conn.commit()
        except sqlite3.Error as exc:  # noqa: BLE001 - cache store must not break LLM path.
            logger.warning("LLM cache sqlite write failed: %s", exc)

    def get(self, model: str, messages: list[dict[str, Any]], **kwargs) -> Optional[Any]:
        request_hash = self._hash_request(model, messages, **kwargs)

        if request_hash in self.cache and not self._is_expired(request_hash):
            self.cache.move_to_end(request_hash)
            self.hits += 1
            _mark_cache_lookup(hit=True)
            logger.info(
                "Cache hit",
                extra={
                    "request_hash": request_hash[:8],
                    "age_seconds": time.time() - self.timestamps[request_hash],
                },
            )
            return self.cache[request_hash]

        if request_hash in self.cache:
            del self.cache[request_hash]
            self.timestamps.pop(request_hash, None)

        sqlite_response = self._load_from_sqlite(request_hash)
        if sqlite_response is not None:
            if len(self.cache) >= self.maxsize:
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
                self.timestamps.pop(oldest_key, None)
            self.cache[request_hash] = sqlite_response
            self.timestamps[request_hash] = time.time()
            self.cache.move_to_end(request_hash)
            self.hits += 1
            _mark_cache_lookup(hit=True)
            logger.info(
                "Cache hit (sqlite)",
                extra={"request_hash": request_hash[:8]},
            )
            return sqlite_response

        self.misses += 1
        _mark_cache_lookup(hit=False)
        logger.debug("Cache miss for hash %s...", request_hash[:8])
        return None

    def set(self, model: str, messages: list[dict[str, Any]], response: Any, **kwargs) -> None:
        request_hash = self._hash_request(model, messages, **kwargs)

        if len(self.cache) >= self.maxsize:
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
            self.timestamps.pop(oldest_key, None)
            logger.debug("Evicted oldest cache entry (size limit %s)", self.maxsize)

        self.cache[request_hash] = response
        self.timestamps[request_hash] = time.time()
        self.cache.move_to_end(request_hash)
        self._store_in_sqlite(request_hash, response)
        logger.debug("Cached response for hash %s...", request_hash[:8])

    def clear(self) -> None:
        self.cache.clear()
        self.timestamps.clear()
        self.hits = 0
        self.misses = 0
        if self.persist and self.db_path is not None:
            try:
                with sqlite3.connect(str(self.db_path), timeout=5) as conn:
                    conn.execute("DELETE FROM llm_request_cache")
                    conn.commit()
            except sqlite3.Error as exc:  # noqa: BLE001 - test/admin cleanup only.
                logger.warning("LLM cache sqlite clear failed: %s", exc)
        logger.info("Cache cleared")

    def get_stats(self) -> dict[str, Any]:
        return {
            "size": len(self.cache),
            "maxsize": self.maxsize,
            "ttl_seconds": self.ttl_seconds,
            "persist": self.persist,
            "hits": self.hits,
            "misses": self.misses,
        }


_request_cache: Optional[RequestCache] = None


def get_request_cache(maxsize: int | None = None, ttl_seconds: int | None = None) -> RequestCache:
    global _request_cache

    if _request_cache is None:
        from app.config import get_settings

        settings = get_settings()
        _request_cache = RequestCache(
            maxsize=maxsize if maxsize is not None else settings.llm_request_cache_maxsize,
            ttl_seconds=ttl_seconds if ttl_seconds is not None else settings.llm_request_cache_ttl_sec,
            persist=settings.llm_request_cache_persist,
            db_path=settings.llm_request_cache_db_path,
        )
        logger.info(
            "Initialized global request cache",
            extra={
                "maxsize": _request_cache.maxsize,
                "ttl_seconds": _request_cache.ttl_seconds,
                "persist": _request_cache.persist,
            },
        )

    return _request_cache


def reset_request_cache() -> None:
    global _request_cache
    if _request_cache is not None:
        _request_cache.clear()
    _request_cache = None
