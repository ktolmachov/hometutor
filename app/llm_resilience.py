"""
18 Core: единая точка для LLM complete с логированием, metrics и опциональным fallback-моделью.

Полный пайплайн RAG через QueryEngine по-прежнему использует настройки клиента из provider.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
from app.logging_config import log_event
from app.metrics import record_error

logger = logging.getLogger(__name__)

# Error class names (lowercased) that indicate the endpoint is unreachable rather
# than a model/generation error. On these errors we try the cross-base fallback
# (HOME_RAG_LLM_FALLBACK_*) instead of giving up immediately.
_CONNECTION_ERROR_NAMES = frozenset({
    "apiconnectionerror",
    "connectionerror",
    "connecttimeout",
    "connectiontimeout",
    "connecterror",
    "networkerror",
    "remotedisconnected",
    "incompleteread",
})


def _is_connection_error(exc: Exception) -> bool:
    """True when the error signals an unreachable endpoint (not a model/content error)."""
    return type(exc).__name__.lower() in _CONNECTION_ERROR_NAMES


def complete_with_resilience(
    llm: Any,
    prompt: str,
    *,
    stage: str,
    allow_provider_fallback: bool | None = None,
    **kwargs: Any,
) -> Any:
    """
    Обертка над ``llm.complete``: structured log + ``record_error`` при ошибке.

    Два уровня fallback при ошибке первичного вызова:
    1. Тот же endpoint, другая модель (``enable_llm_fallback`` + ``llm_fallback_model``).
    2. Другой endpoint (HOME_RAG_LLM_FALLBACK_*) — только при ошибках соединения,
       когда первичный endpoint недоступен (LM Studio офлайн).

    ``allow_provider_fallback=False`` отключает оба уровня (например, SSR).
    """
    settings = get_settings()
    try:
        return llm.complete(prompt, **kwargs)
    except Exception as e:  # noqa: BLE001 - provider failures are recorded before deterministic fallback.
        log_event(
            logger,
            logging.WARNING,
            "llm_complete_failed",
            stage=stage,
            error_type=type(e).__name__,
            message=str(e)[:500],
        )
        record_error(
            endpoint=f"llm:{stage}",
            error_kind="provider",
            error_type=type(e).__name__,
            message=str(e),
        )
        # Path 1 — same-base fallback (different model, same endpoint).
        use_fb = bool(settings.enable_llm_fallback and (settings.llm_fallback_model or "").strip())
        if allow_provider_fallback is False:
            use_fb = False
        if use_fb:
            from app.provider import get_llm_fallback

            fb = get_llm_fallback()
            log_event(
                logger,
                logging.INFO,
                "llm_fallback_invoked",
                stage=stage,
                model=settings.llm_fallback_model,
            )
            return fb.complete(prompt, **kwargs)

        # Path 2 — cross-base fallback (HOME_RAG_LLM_FALLBACK_*).
        # Only for connection errors (endpoint unreachable, e.g. LM Studio offline).
        if allow_provider_fallback is not False and _is_connection_error(e):
            from app.provider import get_home_rag_primary_fallback_llm, primary_chat_fallback_ready
            if primary_chat_fallback_ready(settings):
                try:
                    fb2 = get_home_rag_primary_fallback_llm()
                    log_event(
                        logger,
                        logging.INFO,
                        "llm_home_rag_fallback_invoked",
                        stage=stage,
                        fallback_base=str(getattr(settings, "home_rag_llm_fallback_api_base", "")),
                        fallback_model=str(getattr(settings, "home_rag_llm_fallback_model", "")),
                    )
                    return fb2.complete(prompt, **kwargs)
                except Exception as fb2_exc:  # noqa: BLE001
                    log_event(
                        logger,
                        logging.WARNING,
                        "llm_home_rag_fallback_failed",
                        stage=stage,
                        error_type=type(fb2_exc).__name__,
                        message=str(fb2_exc)[:300],
                    )
        raise


def chat_with_resilience(
    llm: Any,
    messages: list[Any],
    *,
    stage: str,
    allow_provider_fallback: bool | None = None,
    **kwargs: Any,
) -> Any:
    """
    Обертка над ``llm.chat``: structured log + ``record_error`` при ошибке.

    Два уровня fallback (аналогично complete_with_resilience):
    1. Тот же endpoint, другая модель (``enable_llm_fallback`` + ``llm_fallback_model``).
    2. Другой endpoint (HOME_RAG_LLM_FALLBACK_*) при ошибках соединения.
    """
    settings = get_settings()
    try:
        return llm.chat(messages, **kwargs)
    except Exception as e:  # noqa: BLE001 - provider failures are recorded before re-raise/fallback.
        log_event(
            logger,
            logging.WARNING,
            "llm_chat_failed",
            stage=stage,
            error_type=type(e).__name__,
            message=str(e)[:500],
        )
        record_error(
            endpoint=f"llm:{stage}",
            error_kind="provider",
            error_type=type(e).__name__,
            message=str(e),
        )
        # Path 1 — same-base fallback.
        use_fb = bool(settings.enable_llm_fallback and (settings.llm_fallback_model or "").strip())
        if allow_provider_fallback is False:
            use_fb = False
        if use_fb:
            from app.provider import get_llm_fallback

            fb = get_llm_fallback()
            log_event(
                logger,
                logging.INFO,
                "llm_fallback_invoked",
                stage=stage,
                model=settings.llm_fallback_model,
            )
            return fb.chat(messages, **kwargs)

        # Path 2 — cross-base fallback (HOME_RAG_LLM_FALLBACK_*).
        if allow_provider_fallback is not False and _is_connection_error(e):
            from app.provider import get_home_rag_primary_fallback_llm, primary_chat_fallback_ready
            if primary_chat_fallback_ready(settings):
                try:
                    fb2 = get_home_rag_primary_fallback_llm()
                    log_event(
                        logger,
                        logging.INFO,
                        "llm_home_rag_fallback_invoked",
                        stage=stage,
                        fallback_base=str(getattr(settings, "home_rag_llm_fallback_api_base", "")),
                        fallback_model=str(getattr(settings, "home_rag_llm_fallback_model", "")),
                    )
                    return fb2.chat(messages, **kwargs)
                except Exception as fb2_exc:  # noqa: BLE001
                    log_event(
                        logger,
                        logging.WARNING,
                        "llm_home_rag_fallback_failed",
                        stage=stage,
                        error_type=type(fb2_exc).__name__,
                        message=str(fb2_exc)[:300],
                    )
        raise
