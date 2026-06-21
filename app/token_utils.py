"""Token counting and validation utilities for LLM API calls."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Sequence

try:
    import tiktoken
except ImportError:
    tiktoken = None

logger = logging.getLogger(__name__)

LARGE_TEXT_EXACT_TOKEN_LIMIT = 100_000
CHARS_PER_TOKEN_ESTIMATE = 4


@lru_cache(maxsize=32)
def _encoding_for_model(model: str):
    if tiktoken is None:
        return None

    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        # Model not found, use cl100k_base encoding (for GPT-4, GPT-4o)
        logger.debug("Model %s not in tiktoken, using cl100k_base encoding", model)
        return tiktoken.get_encoding("cl100k_base")


def _estimate_tokens_by_chars(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN_ESTIMATE


def estimate_tokens(text: str, model: str = "gpt-4o") -> int:
    """
    Estimate the number of tokens in a text string for a given model.

    Args:
        text: The text to count tokens for
        model: The model name (default: gpt-4o)

    Returns:
        Estimated number of tokens
    """
    if not text:
        return 0

    if len(text) > LARGE_TEXT_EXACT_TOKEN_LIMIT:
        return _estimate_tokens_by_chars(text)

    if tiktoken is None:
        # Fallback: approximate 1 token per 4 characters
        logger.warning("tiktoken not installed, using approximate token counting (1 token ≈ 4 chars)")
        return _estimate_tokens_by_chars(text)

    encoding = _encoding_for_model(model)

    return len(encoding.encode(text))


def estimate_messages_tokens(messages: Sequence[dict[str, Any]], model: str = "gpt-4o") -> int:
    """
    Estimate the total tokens for a messages array (OpenAI format).

    Args:
        messages: List of messages in OpenAI format
        model: The model name

    Returns:
        Total estimated tokens
    """
    if not messages:
        return 0

    total = 0

    for msg in messages:
        # ~4 tokens overhead per message
        total += 4

        # Count content tokens
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content, model)
        elif isinstance(content, list):
            # For multimodal messages
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        total += estimate_tokens(item.get("text", ""), model)
                    elif item.get("type") == "image_url":
                        # Rough estimate: image = 85 tokens + 170 per tile (1 tile per 512x512)
                        total += 85 + 170

    # 2-3 tokens overhead for the entire request
    total += 3

    return total


class TokenValidator:
    """Validator for input token limits."""

    # Token limits (configurable)
    HARD_LIMIT_INPUT = 50_000  # Absolute maximum, will block
    SOFT_LIMIT_INPUT = 30_000  # Warning + auto-trim
    TRIM_THRESHOLD = 25_000    # Auto-trim history

    @staticmethod
    def validate_and_trim(
        messages: list[dict[str, Any]],
        model: str = "gpt-4o",
        auto_trim: bool = True,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Validate messages array and optionally trim if over threshold.

        Args:
            messages: Messages array
            model: Model name
            auto_trim: Whether to auto-trim history when over TRIM_THRESHOLD

        Returns:
            Tuple of (validated_messages, total_input_tokens)

        Raises:
            ValueError: If input tokens exceed HARD_LIMIT_INPUT
        """
        input_tokens = estimate_messages_tokens(messages, model)

        # Check hard limit
        if input_tokens > TokenValidator.HARD_LIMIT_INPUT:
            logger.error(
                f"Input tokens exceed hard limit: {input_tokens} > {TokenValidator.HARD_LIMIT_INPUT}",
                extra={
                    "input_tokens": input_tokens,
                    "hard_limit": TokenValidator.HARD_LIMIT_INPUT,
                    "messages_count": len(messages),
                }
            )
            raise ValueError(
                f"Input size too large ({input_tokens} tokens). "
                f"Max allowed: {TokenValidator.HARD_LIMIT_INPUT}. "
                f"Please reduce context or history."
            )

        # Auto-trim if over threshold
        if auto_trim and input_tokens > TokenValidator.TRIM_THRESHOLD:
            logger.warning(
                f"Input tokens above trim threshold: {input_tokens} > {TokenValidator.TRIM_THRESHOLD}",
                extra={
                    "will_trim": True,
                    "input_tokens": input_tokens,
                }
            )
            messages = TokenValidator._trim_messages(messages, model)
            input_tokens = estimate_messages_tokens(messages, model)
            logger.info(
                f"Messages trimmed",
                extra={
                    "input_tokens_after": input_tokens,
                }
            )

        # Warn if over soft limit
        if input_tokens > TokenValidator.SOFT_LIMIT_INPUT:
            logger.warning(
                f"Input tokens above soft limit: {input_tokens} > {TokenValidator.SOFT_LIMIT_INPUT}",
                extra={
                    "input_tokens": input_tokens,
                    "soft_limit": TokenValidator.SOFT_LIMIT_INPUT,
                }
            )

        return messages, input_tokens

    @staticmethod
    def _trim_messages(messages: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
        """
        Trim messages array to fit within trim threshold.
        Keeps system message + last N user messages.
        """
        if not messages:
            return messages

        result = []
        target_tokens = TokenValidator.TRIM_THRESHOLD - 1000  # 1000 token buffer
        current_tokens = 0

        # Keep system message
        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]

        for msg in system_msgs:
            result.append(msg)
            current_tokens += estimate_tokens(msg.get("content", ""), model) + 4

        # Add other messages in reverse order (newest first)
        for msg in reversed(other_msgs):
            msg_tokens = estimate_tokens(msg.get("content", ""), model) + 4

            if current_tokens + msg_tokens > target_tokens:
                logger.debug(
                    f"Stopped trimming at message count: {len(result)}",
                    extra={"current_tokens": current_tokens}
                )
                break

            result.insert(len(system_msgs), msg)  # Insert after system messages
            current_tokens += msg_tokens

        logger.info(
            f"Trimmed messages from {len(messages)} to {len(result)}",
            extra={
                "original_tokens": estimate_messages_tokens(messages, model),
                "trimmed_tokens": current_tokens,
                "messages_removed": len(messages) - len(result),
            }
        )

        return result
