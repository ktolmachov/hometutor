"""OpenAI-compatible LLM client (guards, cache, accounting)."""

"""Centralized construction of LLM and embedding clients from settings."""

import logging
import re
import time
from typing import Any, Sequence

import httpx
from llama_index.core.base.llms.types import ChatMessage, ChatResponse
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI as LlamaIndexOpenAI
from llama_index.llms.openai.utils import (
    ALL_AVAILABLE_MODELS,
    from_openai_message,
    from_openai_token_logprobs,
    to_openai_message_dicts,
)

from app.config import get_settings
from app.usage_cost import (
    record_accumulated_llm_usage_from_llm_response,
    record_llm_chat_message_roles,
    record_llm_generation_call_ms,
)
from app.token_utils import TokenValidator, estimate_messages_tokens
from app.request_cache import get_request_cache
from app.llm_guards import (
    BlockedModelError,
    HardLimitExceededError,
    NoRetryAfterError,
    check_model_allowed,
    check_input_tokens,
    check_no_recent_error,
    clear_error_fingerprint,
    soft_limit_warning,
    log_cost_call,
    estimate_cost_rub,
    record_error_fingerprint,
    request_fingerprint,
)

logger = logging.getLogger(__name__)
CONTEXT_CHAR_WARNING_LIMIT = 100_000

# Log each (configured_model, alias) pair only once to avoid per-call debug spam.
_logged_model_aliases: set[tuple[str, str]] = set()


_LLAMAINDEX_MODEL_ALIASES = (
    ("gpt-5-mini", "gpt-4o-mini"),
    ("gpt-5-nano", "gpt-4.1-nano"),
    ("gpt-5", "gpt-4o"),
)


def _raise_for_empty_openai_chat_choices(response: object) -> None:
    """OpenRouter/прокси иногда отдают ChatCompletion с ``choices=None`` и полем ``error`` вместо исключения."""
    choices = getattr(response, "choices", None)
    if choices:
        return
    err = getattr(response, "error", None)
    msg = "OpenAI-совместимый chat completion вернул ответ без choices"
    if isinstance(err, dict):
        detail = err.get("message") or err
        code = err.get("code")
        suffix = f" [{code}] {detail}" if code is not None else f" {detail}"
        msg = f"{msg}:{suffix}"
    raise RuntimeError(msg)


def _llamaindex_model_alias(model: str | None) -> str:
    normalized = (model or "").strip().lower()
    if not normalized:
        return ""
    if normalized in ALL_AVAILABLE_MODELS:
        return normalized
    for prefix, alias in _LLAMAINDEX_MODEL_ALIASES:
        if normalized == prefix or normalized.startswith(f"{prefix}-"):
            return alias
    # LlamaIndex validates metadata/context windows against OpenAI model ids.
    # Keep custom OpenAI-compatible provider ids in `self.model` for requests;
    # this fallback is used only by LlamaIndex's internal metadata helpers.
    return (get_settings().llamaindex_metadata_fallback_model or "gpt-4o-mini").strip()


class OpenAI(LlamaIndexOpenAI):
    """LlamaIndex OpenAI wrapper with compatibility aliases for newer model names."""

    @staticmethod
    def _extract_text_content(content: Any) -> str:
        """Best-effort text flattening for OpenAI-compatible message payloads."""
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text_value = item.get("text")
                    if isinstance(text_value, str):
                        parts.append(text_value)
                    elif item.get("type") == "input_text" and isinstance(item.get("input_text"), str):
                        parts.append(item["input_text"])
            return "\n".join(part for part in parts if part)
        if isinstance(content, dict):
            for key in ("text", "content", "input_text"):
                value = content.get(key)
                if isinstance(value, str):
                    return value
        return repr(content)

    def _build_prompt_stats(
        self,
        message_dicts_list: list[dict[str, Any]],
        input_tokens: int,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """Summarize the outbound prompt for cost/error logs and diagnostics."""
        role_counts: dict[str, int] = {}
        role_chars: dict[str, int] = {}
        max_message_chars = 0
        preview: list[dict[str, Any]] = []

        for idx, message in enumerate(message_dicts_list):
            role = str(message.get("role") or "unknown")
            text = self._extract_text_content(message.get("content"))
            chars = len(text)
            role_counts[role] = role_counts.get(role, 0) + 1
            role_chars[role] = role_chars.get(role, 0) + chars
            max_message_chars = max(max_message_chars, chars)
            if idx < 3:
                preview.append(
                    {
                        "role": role,
                        "chars": chars,
                        "preview": text[:160],
                    }
                )

        total_chars = sum(role_chars.values())
        return {
            "messages_count": len(message_dicts_list),
            "input_tokens_estimate": input_tokens,
            "total_chars": total_chars,
            "chars_per_token_estimate": round(total_chars / max(input_tokens, 1), 3),
            "max_message_chars": max_message_chars,
            "role_counts": role_counts,
            "role_chars": role_chars,
            "has_system": bool(role_counts.get("system")),
            "char_warning_limit": CONTEXT_CHAR_WARNING_LIMIT,
            "char_limit_warning": total_chars >= CONTEXT_CHAR_WARNING_LIMIT,
            "prompt_type": kwargs.get("prompt_type"),
            "package_id": kwargs.get("package_id"),
            "message_preview": preview,
        }

    @staticmethod
    def _extract_provider_error_details(exc: Exception) -> dict[str, Any]:
        """Extract provider-specific diagnostics from heterogeneous SDK exceptions."""
        details: dict[str, Any] = {}
        status_code = getattr(exc, "status_code", None)
        if status_code is not None:
            details["status_code"] = status_code

        message = str(exc)
        if message:
            details["message"] = message[:1000]

        response_body = getattr(exc, "responseBody", None)
        if response_body:
            details["response_body_preview"] = str(response_body)[:1000]

        metadata = getattr(exc, "metadata", None)
        if isinstance(metadata, dict):
            url = metadata.get("url")
            if url:
                details["url"] = str(url)

        headers = getattr(exc, "responseHeaders", None)
        if isinstance(headers, dict):
            content_length = headers.get("content-length")
            if content_length:
                details["response_content_length"] = content_length

        length_match = re.search(
            r"input more than (\d+) length, but your input is (\d+)",
            message,
            re.IGNORECASE,
        )
        if length_match:
            details["input_char_limit"] = int(length_match.group(1))
            details["input_char_actual"] = int(length_match.group(2))
            details["error_kind"] = "context_length_exceeded"

        return details

    def _guarded_message_dicts(
        self,
        messages: Sequence[ChatMessage],
        kwargs: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], int, str, dict[str, Any]]:
        """Apply local budget guards before any provider call."""
        guards_applied = ["model_check"]
        try:
            check_model_allowed(self.model)
        except BlockedModelError as exc:
            log_cost_call(
                model=self.model,
                input_tokens=0,
                output_tokens=0,
                cost_rub=0,
                prompt_type=kwargs.get("prompt_type"),
                package_id=kwargs.get("package_id"),
                status="BLOCKED",
                guards_applied=guards_applied,
                error_type=type(exc).__name__,
                error_message=str(exc),
                prompt_stats={
                    "messages_count": len(messages),
                    "input_tokens_estimate": 0,
                    "total_chars": 0,
                    "char_limit_warning": False,
                },
            )
            raise

        message_dicts_list = list(to_openai_message_dicts(messages, model=self.model))
        input_tokens = estimate_messages_tokens(message_dicts_list, model=self.model)
        prompt_stats = self._build_prompt_stats(message_dicts_list, input_tokens, kwargs)
        guards_applied.append("hard_limit_check")

        try:
            check_input_tokens(input_tokens)
        except HardLimitExceededError as exc:
            log_cost_call(
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=0,
                cost_rub=0,
                prompt_type=kwargs.get("prompt_type"),
                package_id=kwargs.get("package_id"),
                status="BLOCKED",
                guards_applied=guards_applied,
                error_type=type(exc).__name__,
                error_message=str(exc),
                prompt_stats=prompt_stats,
            )
            raise

        soft_warn = soft_limit_warning(input_tokens)
        if soft_warn:
            logger.warning(soft_warn, extra={"model": self.model, "input_tokens": input_tokens})
        if prompt_stats["char_limit_warning"]:
            logger.warning(
                "LLM prompt chars approaching provider ceiling",
                extra={
                    "model": self.model,
                    "input_tokens": input_tokens,
                    "total_chars": prompt_stats["total_chars"],
                    "messages_count": prompt_stats["messages_count"],
                },
            )

        logger.info(
            "LLM Chat Input Tokens",
            extra={
                "model": self.model,
                "input_tokens": input_tokens,
                "messages_count": len(message_dicts_list),
                "prompt_chars": prompt_stats["total_chars"],
                "max_message_chars": prompt_stats["max_message_chars"],
            },
        )

        message_dicts_list, input_tokens = TokenValidator.validate_and_trim(
            message_dicts_list,
            model=self.model,
            auto_trim=True,
        )
        fingerprint = request_fingerprint(self.model, message_dicts_list, kwargs)
        try:
            check_no_recent_error(fingerprint)
        except NoRetryAfterError as exc:
            guards_applied.append("no_retry_after_error")
            log_cost_call(
                model=self.model,
                input_tokens=input_tokens,
                output_tokens=0,
                cost_rub=0,
                prompt_type=kwargs.get("prompt_type"),
                package_id=kwargs.get("package_id"),
                status="BLOCKED",
                guards_applied=guards_applied,
                error_type=type(exc).__name__,
                error_message=str(exc),
                prompt_stats=prompt_stats,
            )
            raise

        return message_dicts_list, input_tokens, fingerprint, prompt_stats

    def _log_success_cost(
        self,
        response: object,
        input_tokens: int,
        kwargs: dict[str, Any],
        *,
        status: str = "OK",
        prompt_stats: dict[str, Any] | None = None,
    ) -> None:
        usage = getattr(response, "usage", None)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        cost_rub = (
            0
            if status == "CACHE_HIT"
            else estimate_cost_rub(self.model, input_tokens, output_tokens)
        )
        log_cost_call(
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_rub=cost_rub,
            prompt_type=kwargs.get("prompt_type"),
            package_id=kwargs.get("package_id"),
            status=status,
            guards_applied=["model_check", "hard_limit_check", "no_retry_after_error"],
            prompt_stats=prompt_stats,
        )

    def _log_provider_error(
        self,
        exc: Exception,
        input_tokens: int,
        kwargs: dict[str, Any],
        prompt_stats: dict[str, Any] | None = None,
    ) -> None:
        # Провайдер мог списать вход; полной стоимости нет — только оценка input-only.
        cost_rub = estimate_cost_rub(self.model, input_tokens, 0)
        provider_error = self._extract_provider_error_details(exc)
        log_cost_call(
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=0,
            cost_rub=cost_rub,
            prompt_type=kwargs.get("prompt_type"),
            package_id=kwargs.get("package_id"),
            status="ERR",
            guards_applied=["model_check", "hard_limit_check", "no_retry_after_error"],
            error_type=type(exc).__name__,
            error_message=str(exc),
            cost_estimated_after_error=True,
            prompt_stats=prompt_stats,
            provider_error=provider_error,
        )
        logger.error(
            "LLM provider call failed",
            extra={
                "model": self.model,
                "input_tokens": input_tokens,
                "prompt_chars": (prompt_stats or {}).get("total_chars"),
                "provider_error": provider_error,
            },
        )

    def _chat_response_from_openai_response(self, response: object) -> ChatResponse:
        openai_message = response.choices[0].message
        message = from_openai_message(
            openai_message, modalities=self.modalities or ["text"]
        )
        openai_token_logprobs = response.choices[0].logprobs
        logprobs = None
        if openai_token_logprobs and openai_token_logprobs.content:
            logprobs = from_openai_token_logprobs(openai_token_logprobs.content)

        return ChatResponse(
            message=message,
            raw=response,
            logprobs=logprobs,
            additional_kwargs=self._get_response_token_counts(response),
        )

    def _chat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> ChatResponse:
        """Sync chat with local guards, cache, and per-call accounting.

        No tenacity retries here: retrying a timeout against a local LLM queues
        more work on an already-busy server and multiplies wall time by 3x.
        The OpenAI SDK's own max_retries covers rate-limits and 5xx errors.
        """
        message_dicts_list, input_tokens, fingerprint, prompt_stats = self._guarded_message_dicts(
            messages,
            kwargs,
        )
        record_llm_chat_message_roles([str(m.get("role") or "") for m in message_dicts_list])
        cache = get_request_cache()
        cached_response = cache.get(self.model, message_dicts_list, **kwargs)
        if cached_response is not None:
            logger.info(
                "Returning cached response (deduplication)",
                extra={
                    "model": self.model,
                    "messages_count": len(message_dicts_list),
                },
            )
            self._log_success_cost(
                cached_response.raw,
                input_tokens,
                kwargs,
                status="CACHE_HIT",
                prompt_stats=prompt_stats,
            )
            return cached_response

        client = self._get_client()
        if self.reuse_client:
            try:
                response = client.chat.completions.create(
                    messages=message_dicts_list,
                    stream=False,
                    **self._get_model_kwargs(**kwargs),
                )
            except Exception as exc:  # noqa: BLE001 - provider exceptions vary by compatible backend.
                record_error_fingerprint(fingerprint)
                self._log_provider_error(exc, input_tokens, kwargs, prompt_stats=prompt_stats)
                raise
        else:
            try:
                with client:
                    response = client.chat.completions.create(
                        messages=message_dicts_list,
                        stream=False,
                        **self._get_model_kwargs(**kwargs),
                    )
            except Exception as exc:  # noqa: BLE001 - provider exceptions vary by compatible backend.
                record_error_fingerprint(fingerprint)
                self._log_provider_error(exc, input_tokens, kwargs, prompt_stats=prompt_stats)
                raise

        try:
            _raise_for_empty_openai_chat_choices(response)
        except RuntimeError as exc:
            record_error_fingerprint(fingerprint)
            self._log_provider_error(exc, input_tokens, kwargs, prompt_stats=prompt_stats)
            raise
        clear_error_fingerprint(fingerprint)
        chat_response = self._chat_response_from_openai_response(response)
        self._log_success_cost(response, input_tokens, kwargs, prompt_stats=prompt_stats)

        try:
            cache.set(self.model, message_dicts_list, chat_response, **kwargs)
        except Exception as exc:  # noqa: BLE001 - cache failures must not break LLM responses.
            logger.warning(
                "Failed to cache response",
                extra={"model": self.model, "error": str(exc)},
            )

        return chat_response

    async def _achat(
        self,
        messages: Sequence[ChatMessage],
        **kwargs: Any,
    ) -> ChatResponse:
        """Async chat with the same guards and cost logging as sync chat."""
        message_dicts_list, input_tokens, fingerprint, prompt_stats = self._guarded_message_dicts(
            messages,
            kwargs,
        )
        record_llm_chat_message_roles([str(m.get("role") or "") for m in message_dicts_list])
        cache = get_request_cache()
        cached_response = cache.get(self.model, message_dicts_list, **kwargs)
        if cached_response is not None:
            self._log_success_cost(
                cached_response.raw,
                input_tokens,
                kwargs,
                status="CACHE_HIT",
                prompt_stats=prompt_stats,
            )
            return cached_response

        aclient = self._get_aclient()
        if self.reuse_client:
            try:
                response = await aclient.chat.completions.create(
                    messages=message_dicts_list,
                    stream=False,
                    **self._get_model_kwargs(**kwargs),
                )
            except Exception as exc:  # noqa: BLE001 - provider exceptions vary by compatible backend.
                record_error_fingerprint(fingerprint)
                self._log_provider_error(exc, input_tokens, kwargs, prompt_stats=prompt_stats)
                raise
        else:
            try:
                async with aclient:
                    response = await aclient.chat.completions.create(
                        messages=message_dicts_list,
                        stream=False,
                        **self._get_model_kwargs(**kwargs),
                    )
            except Exception as exc:  # noqa: BLE001 - provider exceptions vary by compatible backend.
                record_error_fingerprint(fingerprint)
                self._log_provider_error(exc, input_tokens, kwargs, prompt_stats=prompt_stats)
                raise

        try:
            _raise_for_empty_openai_chat_choices(response)
        except RuntimeError as exc:
            record_error_fingerprint(fingerprint)
            self._log_provider_error(exc, input_tokens, kwargs, prompt_stats=prompt_stats)
            raise
        clear_error_fingerprint(fingerprint)
        chat_response = self._chat_response_from_openai_response(response)
        self._log_success_cost(response, input_tokens, kwargs, prompt_stats=prompt_stats)

        try:
            cache.set(self.model, message_dicts_list, chat_response, **kwargs)
        except Exception as exc:  # noqa: BLE001 - cache failures must not break LLM responses.
            logger.warning(
                "Failed to cache response",
                extra={"model": self.model, "error": str(exc)},
            )

        return chat_response

    def _get_model_name(self) -> str:
        model_name = super()._get_model_name()
        aliased = _llamaindex_model_alias(model_name)
        if aliased != model_name:
            pair = (model_name, aliased)
            if pair not in _logged_model_aliases:
                _logged_model_aliases.add(pair)
                logger.debug(
                    "Using LlamaIndex model metadata alias | configured_model=%s | metadata_model=%s",
                    model_name,
                    aliased,
                )
        return aliased

    def chat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        _t0 = time.perf_counter()
        try:
            r = super().chat(messages, **kwargs)
        finally:
            record_llm_generation_call_ms((time.perf_counter() - _t0) * 1000.0)
        record_accumulated_llm_usage_from_llm_response(r)
        return r

    async def achat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        _t0 = time.perf_counter()
        try:
            r = await super().achat(messages, **kwargs)
        finally:
            record_llm_generation_call_ms((time.perf_counter() - _t0) * 1000.0)
        record_accumulated_llm_usage_from_llm_response(r)
        return r

    def complete(self, prompt, **kwargs):  # type: ignore[no-untyped-def]
        _t0 = time.perf_counter()
        try:
            r = super().complete(prompt, **kwargs)
        finally:
            record_llm_generation_call_ms((time.perf_counter() - _t0) * 1000.0)
        record_accumulated_llm_usage_from_llm_response(r)
        return r

    async def acomplete(self, prompt, **kwargs):  # type: ignore[no-untyped-def]
        _t0 = time.perf_counter()
        try:
            r = await super().acomplete(prompt, **kwargs)
        finally:
            record_llm_generation_call_ms((time.perf_counter() - _t0) * 1000.0)
        record_accumulated_llm_usage_from_llm_response(r)
        return r


