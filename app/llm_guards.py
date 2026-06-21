"""LLM call guards and cost tracking."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

BLOCKED_MODELS = {
    "z-ai/glm-5.1",
    "glm-5.1",
    "openai/gpt-5.3-codex",
    "gpt-5.3-codex",
}

HARD_TOKEN_LIMIT = 20_000
SOFT_TOKEN_LIMIT = 12_000
ERROR_FINGERPRINT_TTL_SECONDS = 600

_ERROR_FINGERPRINTS: dict[str, float] = {}


class BlockedModelError(Exception):
    """A blocked model was requested."""


class HardLimitExceededError(Exception):
    """Input tokens exceed the hard safety limit."""


class NoRetryAfterError(Exception):
    """The same failed LLM payload was submitted again unchanged."""


# Compatibility for the earlier misspelled name.
NoRetryAfterErrorError = NoRetryAfterError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def check_model_allowed(model: str) -> None:
    """Block models that are too expensive or unstable for routine use."""
    normalized = (model or "").lower().strip()
    if any(blocked in normalized for blocked in BLOCKED_MODELS):
        msg = f"Blocked model '{model}' not allowed. Use grok-4.1-fast-thinking instead."
        logger.error("MODEL_BLOCKED", extra={"model": model})
        raise BlockedModelError(msg)


def check_input_tokens(input_tokens: int) -> None:
    """Block requests above the hard input-token budget."""
    if input_tokens > HARD_TOKEN_LIMIT:
        msg = (
            f"Input tokens {input_tokens} exceeds hard limit {HARD_TOKEN_LIMIT}. "
            "Compress context or split request."
        )
        logger.error("HARD_LIMIT_EXCEEDED", extra={"input_tokens": input_tokens})
        raise HardLimitExceededError(msg)


def soft_limit_warning(input_tokens: int) -> str | None:
    """Return a warning message when the request is above the soft budget."""
    if input_tokens > SOFT_TOKEN_LIMIT:
        return (
            f"Input tokens {input_tokens} exceeds soft limit {SOFT_TOKEN_LIMIT}. "
            "Consider compression."
        )
    return None


def _json_default(value: Any) -> str:
    return repr(value)


def request_fingerprint(model: str, messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> str:
    """Build a stable fingerprint for retry-loop detection."""
    payload = {
        "model": (model or "").strip(),
        "messages": messages,
        "kwargs": kwargs,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _drop_expired_error_fingerprints(now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    expired = [
        fingerprint
        for fingerprint, created_at in _ERROR_FINGERPRINTS.items()
        if current - created_at > ERROR_FINGERPRINT_TTL_SECONDS
    ]
    for fingerprint in expired:
        _ERROR_FINGERPRINTS.pop(fingerprint, None)


def check_no_recent_error(fingerprint: str) -> None:
    """Reject unchanged retries after a recent failed provider call."""
    _drop_expired_error_fingerprints()
    if fingerprint in _ERROR_FINGERPRINTS:
        msg = "Identical LLM payload was retried after an error. Compress context before retry."
        logger.error("UNCHANGED_RETRY_BLOCKED", extra={"fingerprint": fingerprint})
        raise NoRetryAfterError(msg)


def record_error_fingerprint(fingerprint: str) -> None:
    """Remember a failed provider payload briefly to block unchanged retries."""
    _drop_expired_error_fingerprints()
    _ERROR_FINGERPRINTS[fingerprint] = time.monotonic()


def clear_error_fingerprint(fingerprint: str) -> None:
    """Clear a failure fingerprint after a successful provider response."""
    _ERROR_FINGERPRINTS.pop(fingerprint, None)


def reset_error_fingerprints() -> None:
    """Reset retry-loop memory for tests."""
    _ERROR_FINGERPRINTS.clear()


def log_cost_call(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_rub: float,
    package_id: str | None = None,
    prompt_type: str | None = None,
    status: str = "OK",
    guards_applied: list[str] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    *,
    cost_estimated_after_error: bool | None = None,
    prompt_stats: dict[str, Any] | None = None,
    provider_error: dict[str, Any] | None = None,
) -> None:
    """Append one LLM call accounting record to the daily JSONL file."""
    cost_log_dir = get_settings().llm_cost_log_dir
    cost_log_dir.mkdir(parents=True, exist_ok=True)
    now = _utc_now()
    log_file = cost_log_dir / f"cost_logs_{now.strftime('%Y-%m-%d')}.jsonl"

    record = {
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_rub": round(float(cost_rub), 6),
        "package_id": package_id,
        "prompt_type": prompt_type,
        "status": status,
        "guards_applied": guards_applied or [],
    }
    if error_type:
        record["error_type"] = error_type
    if error_message:
        record["error_message"] = error_message
    if cost_estimated_after_error:
        record["cost_estimated_after_error"] = True
    if prompt_stats:
        record["prompt_stats"] = prompt_stats
    if provider_error:
        record["provider_error"] = provider_error

    try:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning("Failed to log LLM cost", extra={"model": model, "error": str(exc)})


def estimate_cost_rub(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate call cost in RUB using static USD/1M-token prices."""
    pricing_per_1m = {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 5.00, "output": 15.00},
        "gpt-5-mini": {"input": 0.25, "output": 2.00},
        "grok-4.1-fast-thinking": {"input": 0.60, "output": 2.40},
        "claude-sonnet-4.6": {"input": 3.00, "output": 15.00},
        "claude-opus-4.7": {"input": 15.00, "output": 75.00},
    }

    normalized = (model or "").lower().strip()
    prices = pricing_per_1m.get(normalized, {"input": 3.0, "output": 10.0})

    cost_usd = (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000
    return cost_usd * 90
