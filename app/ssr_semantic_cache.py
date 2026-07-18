"""Semantic (embedding-based) cache lookup for SSR explanations.

Complements the exact-key cache with similarity-based matching. Most learner contexts
are similar day-to-day (same weak concepts, similar flashcard counts). This layer finds
cached explanations for semantically similar contexts, dramatically increasing hit rate.

How it works:
1. Compute a lightweight embedding of the context dict (JSON -> embedding)
2. Store embeddings alongside cached explanations
3. On cache miss with exact key, search for semantically similar cached contexts
4. Return cached explanation if similarity > threshold (default 0.95)

Fallback: If embeddings unavailable (model not loaded), just use exact-match cache.

Token and latency overhead: ~5ms per lookup, negligible vs LLM cost (~2-5s).
"""
from __future__ import annotations

import json
import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

_EMBEDDINGS_MODEL = None
_MODEL_LOAD_ATTEMPTED = False
_MODEL_LOCK = threading.Lock()
_CACHED_EMBEDDINGS: dict[str, tuple[Any, "np.ndarray"]] = {}  # key -> (text, embedding)


def _load_embeddings_model():
    """Load the optional model once, using only an existing local snapshot."""
    global _EMBEDDINGS_MODEL, _MODEL_LOAD_ATTEMPTED
    if _MODEL_LOAD_ATTEMPTED:
        return _EMBEDDINGS_MODEL
    with _MODEL_LOCK:
        if _MODEL_LOAD_ATTEMPTED:
            return _EMBEDDINGS_MODEL
        _MODEL_LOAD_ATTEMPTED = True
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(
                "all-MiniLM-L6-v2",
                device="cpu",
                local_files_only=True,
            )
            _EMBEDDINGS_MODEL = model
            logger.debug("ssr_semantic_cache_model_loaded")
            return model
        except ImportError:
            logger.debug("ssr_semantic_cache_model_unavailable: sentence_transformers not installed")
            return None
        except Exception as exc:
            logger.debug(
                "ssr_semantic_cache_local_model_unavailable",
                extra={"error": str(exc)[:100]},
            )
            return None


def _context_to_string(ctx: dict[str, Any]) -> str:
    """Serialize context dict to a stable string for embedding."""
    items = []
    for k in sorted(ctx.keys()):
        v = ctx[k]
        if isinstance(v, (list, dict)):
            v = json.dumps(v, ensure_ascii=False, sort_keys=True)
        items.append(f"{k}={v}")
    return " ".join(items)


def semantic_cache_lookup(
    ctx: dict[str, Any],
    existing_cache: dict[str, tuple[Any, str]],
    threshold: float = 0.95,
) -> str | None:
    """Search for a cached explanation with semantic similarity to the given context.

    Args:
        ctx: context dict (same structure as _build_ssr_llm_learning_context)
        existing_cache: the exact-match cache (for fallback and comparison)
        threshold: cosine similarity threshold (0–1; 0.95 = very similar)

    Returns:
        Cached explanation text if found and fresh; None otherwise.
    """
    model = _load_embeddings_model()
    if model is None:
        try:
            from app.ssr_ai.telemetry import record_ssr_ai_auxiliary_event

            record_ssr_ai_auxiliary_event(
                level="L2",
                category="semantic_cache",
                detail={"outcome": "model_unavailable"},
            )
        except Exception:  # noqa: BLE001
            pass
        return None  # Embeddings unavailable; caller should use exact-match cache

    try:
        import numpy as np

        query_str = _context_to_string(ctx)
        query_embedding = np.array(model.encode(query_str, normalize_embeddings=True))

        # Cosine similarity: dot product of normalized vectors (they're already normalized)
        def _cosine_sim(v1: np.ndarray, v2: np.ndarray) -> float:
            return float(np.dot(v1, v2))

        # Search cached embeddings for similar context
        best_match_key: str | None = None
        best_sim = threshold  # Only return if similarity >= threshold
        for cached_key, (cached_text, cached_emb) in _CACHED_EMBEDDINGS.items():
            if cached_key not in existing_cache:
                continue  # Entry was expired; skip
            cached_emb_arr = np.array(cached_emb)
            sim = _cosine_sim(query_embedding, cached_emb_arr)
            if sim > best_sim:
                best_sim = sim
                best_match_key = cached_key

        if best_match_key:
            cached_entry = existing_cache.get(best_match_key)
            if cached_entry:
                logger.debug(
                    "ssr_semantic_cache_hit",
                    extra={"similarity": round(best_sim, 3), "original_key": best_match_key[:20]},
                )
                try:
                    from app.ssr_ai.telemetry import record_ssr_ai_auxiliary_event

                    record_ssr_ai_auxiliary_event(
                        level="L2",
                        category="semantic_cache",
                        detail={"outcome": "hit", "similarity": round(best_sim, 4)},
                    )
                except Exception:  # noqa: BLE001
                    pass
                return str(cached_entry[1])  # Return the cached text

    except Exception as exc:  # noqa: BLE001
        logger.debug("ssr_semantic_cache_lookup_failed", extra={"error": str(exc)[:100]})
        try:
            from app.ssr_ai.telemetry import record_ssr_ai_auxiliary_event

            record_ssr_ai_auxiliary_event(
                level="L2",
                category="semantic_cache",
                detail={"outcome": "lookup_failed", "error": str(exc)[:120]},
            )
        except Exception:  # noqa: BLE001
            pass
        return None

    try:
        from app.ssr_ai.telemetry import record_ssr_ai_auxiliary_event

        record_ssr_ai_auxiliary_event(
            level="L2",
            category="semantic_cache",
            detail={"outcome": "miss"},
        )
    except Exception:  # noqa: BLE001
        pass

    return None


def semantic_cache_store(
    key: str,
    ctx: dict[str, Any],
    text: str,
) -> None:
    """Store an explanation with its semantic embedding for future similarity matching.

    Call this after caching a newly-generated explanation.
    """
    model = _load_embeddings_model()
    if model is None:
        return  # Embeddings unavailable; skip semantic caching

    try:
        ctx_str = _context_to_string(ctx)
        embedding = model.encode(ctx_str, normalize_embeddings=True)
        _CACHED_EMBEDDINGS[key] = (text, embedding)
        logger.debug("ssr_semantic_cache_stored", extra={"key": key[:20]})
    except Exception as exc:  # noqa: BLE001
        logger.debug("ssr_semantic_cache_store_failed", extra={"error": str(exc)[:100]})


def clear_semantic_cache() -> None:
    """Clear the semantic cache (called on app restart or manual reset)."""
    global _CACHED_EMBEDDINGS
    _CACHED_EMBEDDINGS.clear()
