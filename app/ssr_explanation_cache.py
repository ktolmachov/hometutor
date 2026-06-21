"""Backend-safe SSR explanation cache and feedback metadata helpers."""
from __future__ import annotations

import contextvars
from collections import OrderedDict
from typing import Any

_SSR_LLM_EXPLANATION_CACHE_TTL_SEC = 3600
_SSR_LLM_EXPLANATION_CACHE_MAX_ENTRIES = 256

_SSR_LLM_EXPLANATION_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()

_ssr_explanation_feedback_ctx: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "ssr_explanation_feedback_ctx", default=None
)


def _ssr_feedback_ctx_reset() -> None:
    _ssr_explanation_feedback_ctx.set(None)


def _ssr_feedback_ctx_set(*, outcome: str, latency_ms: float = 0.0) -> None:
    _ssr_explanation_feedback_ctx.set(
        {"explanation_outcome": str(outcome), "latency_ms": float(latency_ms)}
    )


def peek_ssr_explanation_feedback_meta() -> dict[str, Any]:
    """Return a copy of the last SSR explanation outcome for thumbs analytics."""
    raw = _ssr_explanation_feedback_ctx.get()
    return dict(raw) if isinstance(raw, dict) else {}


def prime_ssr_explanation_feedback_meta_for_tests(*, outcome: str, latency_ms: float = 0.0) -> None:
    """Test hook: inject feedback metadata as if an explanation pass had just finished."""
    _ssr_feedback_ctx_set(outcome=outcome, latency_ms=latency_ms)


def _cache_put_exact(key: str, now: float, text: str) -> None:
    if key in _SSR_LLM_EXPLANATION_CACHE:
        del _SSR_LLM_EXPLANATION_CACHE[key]
    _SSR_LLM_EXPLANATION_CACHE[key] = (now, text)
    while len(_SSR_LLM_EXPLANATION_CACHE) > _SSR_LLM_EXPLANATION_CACHE_MAX_ENTRIES:
        _SSR_LLM_EXPLANATION_CACHE.popitem(last=False)


def _cache_get_exact(key: str) -> tuple[float, str] | None:
    pair = _SSR_LLM_EXPLANATION_CACHE.get(key)
    if pair is None:
        return None
    _SSR_LLM_EXPLANATION_CACHE.move_to_end(key)
    return pair


def _clip_ssr_explanation(text: str, *, max_words: int = 200) -> str:
    words = (text or "").strip().split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(" .,;:") + "."
