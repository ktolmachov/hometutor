from __future__ import annotations

import contextvars
from typing import Any

# Накопление usage основного LLM внутри window (см. answer_question → engine.query).
_llm_rag_gen_bucket: contextvars.ContextVar[list[dict[str, int]] | None] = contextvars.ContextVar(
    "llm_rag_gen_bucket",
    default=None,
)

# Роли сообщений каждого chat-вызова внутри того же window (wire-контракт для prompt smoke).
_llm_rag_gen_roles: contextvars.ContextVar[list[list[str]] | None] = contextvars.ContextVar(
    "llm_rag_gen_roles",
    default=None,
)

# Длительность (ms) каждого LLM-вызова внутри того же window. Позволяет честно
# разделить query_execute_ms на retrieval_ms (retrieval + rerank + postprocessors)
# и llm_ms (фактическая генерация), которые engine.query() объединяет в один таймер.
_llm_rag_gen_call_ms: contextvars.ContextVar[list[float] | None] = contextvars.ContextVar(
    "llm_rag_gen_call_ms",
    default=None,
)


def begin_llm_generation_token_accumulation() -> None:
    """Начать собирать токены вызовов get_llm() до ``consume_llm_generation_token_accumulation``."""
    _llm_rag_gen_bucket.set([])
    _llm_rag_gen_roles.set([])
    _llm_rag_gen_call_ms.set([])


def record_accumulated_llm_usage_from_llm_response(response: Any) -> None:
    """Добавить usage из одного ответа LlamaIndex LLM (chat/complete), если window открыт."""
    bucket = _llm_rag_gen_bucket.get()
    if bucket is None:
        return
    u = extract_token_usage(response)
    if u and (u.get("total_tokens") or u.get("prompt_tokens") or u.get("completion_tokens")):
        bucket.append(dict(u))


def record_llm_chat_message_roles(roles: list[str]) -> None:
    """Записать роли одного chat-запроса (как ушли на провод), если window открыт."""
    bucket = _llm_rag_gen_roles.get()
    if bucket is None:
        return
    cleaned = [str(r) for r in roles if str(r).strip()]
    if cleaned:
        bucket.append(cleaned)


def consume_llm_generation_token_accumulation() -> dict[str, int] | None:
    """Свернуть накопленные вызовы в один dict и закрыть window."""
    bucket = _llm_rag_gen_bucket.get()
    _llm_rag_gen_bucket.set(None)
    if not bucket:
        return None
    return merge_token_usage(*bucket)


def consume_llm_generation_message_roles() -> list[list[str]] | None:
    """Вернуть роли всех chat-вызовов window и закрыть его (None, если вызовов не было)."""
    bucket = _llm_rag_gen_roles.get()
    _llm_rag_gen_roles.set(None)
    return bucket or None


def record_llm_generation_call_ms(elapsed_ms: float) -> None:
    """Добавить длительность одного LLM-вызова (chat/complete), если window открыт."""
    bucket = _llm_rag_gen_call_ms.get()
    if bucket is None:
        return
    bucket.append(float(elapsed_ms))


def consume_llm_generation_call_ms() -> float | None:
    """Свернуть длительности всех LLM-вызовов window в сумму ms и закрыть его.

    None означает, что внутри window не было ни одного LLM-вызова (напр. ранний
    extractive-выход) — вызывающий код трактует это как llm_ms=0.
    """
    bucket = _llm_rag_gen_call_ms.get()
    _llm_rag_gen_call_ms.set(None)
    if not bucket:
        return None
    return round(sum(bucket), 3)


def _coerce_mapping(obj: Any) -> dict[str, Any] | None:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            out = dump()
            return out if isinstance(out, dict) else None
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            return None
    return None


MODEL_PRICING_PER_1M_TOKENS: dict[str, dict[str, float]] = {
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 5.00, "output": 15.00},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
    "text-embedding-3-large": {"input": 0.13, "output": 0.0},
}


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_usage(payload: dict[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(payload, dict):
        return None

    prompt_tokens = _safe_int(payload.get("prompt_tokens") or payload.get("input_tokens"))
    completion_tokens = _safe_int(payload.get("completion_tokens") or payload.get("output_tokens"))
    total_tokens = _safe_int(payload.get("total_tokens"))
    reasoning_tokens = _safe_int(payload.get("reasoning_tokens"))
    completion_details = payload.get("completion_tokens_details")
    if reasoning_tokens is None and isinstance(completion_details, dict):
        reasoning_tokens = _safe_int(completion_details.get("reasoning_tokens"))

    if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

    if prompt_tokens is None and completion_tokens is None and total_tokens is None:
        return None

    out = {
        "prompt_tokens": prompt_tokens or 0,
        "completion_tokens": completion_tokens or 0,
        "total_tokens": total_tokens or 0,
    }
    if reasoning_tokens is not None:
        out["reasoning_tokens"] = reasoning_tokens
    return out


def extract_token_usage(response: Any) -> dict[str, int] | None:
    if response is None:
        return None

    candidates: list[dict[str, Any] | None] = []

    if isinstance(response, dict):
        candidates.extend(
            [
                response.get("usage"),
                response.get("token_usage"),
                response,
            ]
        )

    for attr in ("usage", "token_usage", "additional_kwargs", "raw", "raw_response", "metadata"):
        value = getattr(response, attr, None)
        as_dict = _coerce_mapping(value)
        if as_dict is not None:
            candidates.extend(
                [
                    _coerce_mapping(as_dict.get("usage")),
                    _coerce_mapping(as_dict.get("token_usage")),
                    as_dict,
                ]
            )

    first_normalized: dict[str, int] | None = None
    for candidate in candidates:
        normalized = _normalize_usage(candidate)
        if normalized is None:
            continue
        if "reasoning_tokens" in normalized:
            return normalized
        if first_normalized is None:
            first_normalized = normalized

    return first_normalized


def merge_token_usage(*usages: dict[str, int] | None) -> dict[str, int] | None:
    merged = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    has_values = False

    for usage in usages:
        if not usage:
            continue
        has_values = True
        merged["prompt_tokens"] += usage.get("prompt_tokens", 0)
        merged["completion_tokens"] += usage.get("completion_tokens", 0)
        merged["total_tokens"] += usage.get("total_tokens", 0)
        if "reasoning_tokens" in usage:
            merged["reasoning_tokens"] = merged.get("reasoning_tokens", 0) + usage.get("reasoning_tokens", 0)

    return merged if has_values else None


def estimate_cost_usd(model: str | None, usage: dict[str, int] | None) -> float | None:
    if not model or not usage:
        return None

    pricing = None
    normalized_model = model.strip().lower()
    for key, value in MODEL_PRICING_PER_1M_TOKENS.items():
        if normalized_model == key or normalized_model.startswith(f"{key}-"):
            pricing = value
            break

    if pricing is None:
        # Safe fallback for chat models that are not yet explicitly listed.
        if normalized_model.startswith("gpt-5"):
            pricing = MODEL_PRICING_PER_1M_TOKENS["gpt-5-mini"]
        elif normalized_model.startswith("gpt-4o"):
            pricing = MODEL_PRICING_PER_1M_TOKENS["gpt-4o-mini"]
        else:
            # Local aliases, router model ids, previews: keep a non-null debug estimate.
            pricing = MODEL_PRICING_PER_1M_TOKENS["gpt-4o-mini"]

    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cost = (prompt_tokens / 1_000_000.0) * pricing["input"] + (completion_tokens / 1_000_000.0) * pricing["output"]
    return round(cost, 8)


def sum_costs(*costs: float | None) -> float | None:
    values = [value for value in costs if value is not None]
    if not values:
        return None
    return round(sum(values), 8)


def _estimate_text_tokens_rough(text: str) -> int:
    """~4 characters per token (no tiktoken); minimum 1 for non-empty text."""
    stripped = (text or "").strip()
    if not stripped:
        return 0
    return max(1, len(stripped) // 4)


def estimate_retrieval_embedding_usage(
    query_texts: list[str],
    *,
    embed_model: str | None,
) -> tuple[dict[str, int] | None, float | None]:
    """Approximate query-embedding token usage when the provider does not expose it.

    Sums rough token counts for each distinct query string passed to vector retrieval
    (main query + extra summary/subquestion strings for doc-then-chunk). Does not
    include reranker (local FlagEmbedding) or BM25-only paths (no embed API calls).
    """
    seen: set[str] = set()
    total_prompt = 0
    for raw in query_texts:
        t = (raw or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        total_prompt += _estimate_text_tokens_rough(t)

    if total_prompt <= 0:
        return None, None

    usage = {
        "prompt_tokens": total_prompt,
        "completion_tokens": 0,
        "total_tokens": total_prompt,
    }
    cost = estimate_cost_usd(embed_model, usage)
    return usage, cost
