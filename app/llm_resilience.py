"""
18 Core: единая точка для LLM complete с логированием, metrics и опциональным fallback-моделью.

Полный пайплайн RAG через QueryEngine по-прежнему использует настройки клиента из provider.
"""

from __future__ import annotations

import concurrent.futures
import logging
from functools import partial
from typing import Any
from urllib.parse import urlparse

from app.config import get_settings
from app.logging_config import log_event
from app.metrics import record_error

logger = logging.getLogger(__name__)

# Thread pool for soft-timeout enforcement on local LLM calls.
# Orphaned threads are bounded by the httpx hard timeout on the underlying client.
_LLM_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="llm_resilience_",
)

# Error class names (lowercased) that indicate the endpoint is unreachable rather
# than a model/generation error. On these errors we try the cross-base fallback
# (HOME_RAG_LLM_FALLBACK_*) instead of giving up immediately.
_TRANSIENT_ERROR_NAMES = frozenset({
    "apiconnectionerror",
    "connectionerror",
    "connecttimeout",
    "connectiontimeout",
    "connecterror",
    "networkerror",
    "remotedisconnected",
    "incompleteread",
    "timeouterror",
    "readtimeouterror",
    "writetimeouterror",
    "pooltimeouterror",
    "httpxconnecterror",
    "httpxreaderror",
    "httpxwritetimeouterror",
    "httpxpooltimeouterror",
    "httptimeouterror",
})


def _llm_base_url(llm: Any) -> str:
    return str(
        getattr(llm, "home_rag_llm_api_base", None)
        or getattr(llm, "api_base", None)
        or getattr(llm, "api_base_url", None)
        or ""
    ).strip()


def _is_local_llm_base(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").strip().lower()
    return host in {"127.0.0.1", "localhost", "::1"} or host.endswith(".local")


def _circuit_open(base_url: str) -> bool:
    if not base_url or not _is_local_llm_base(base_url):
        return False
    try:
        from app.llm_local_circuit import is_open

        return is_open(base_url)
    except Exception:  # noqa: BLE001 - circuit observability must not break LLM calls.
        logger.debug("llm_local_circuit_is_open_failed", exc_info=True)
        return False


def _record_circuit_success(base_url: str) -> None:
    if not base_url or not _is_local_llm_base(base_url):
        return
    try:
        from app.llm_local_circuit import record_success

        record_success(base_url)
    except Exception:  # noqa: BLE001 - circuit observability must not break LLM calls.
        logger.debug("llm_local_circuit_record_success_failed", exc_info=True)


def _record_circuit_failure(base_url: str, exc: Exception) -> None:
    if not base_url or not _is_local_llm_base(base_url):
        return
    try:
        from app.llm_local_circuit import record_failure

        record_failure(base_url, error_type=type(exc).__name__)
    except Exception:  # noqa: BLE001 - circuit observability must not break LLM calls.
        logger.debug("llm_local_circuit_record_failure_failed", exc_info=True)


def _fallback_or_raise_on_open_circuit(
    *,
    stage: str,
    method_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> Any:
    settings = get_settings()
    if method_name not in {"complete", "chat"}:
        raise RuntimeError(f"Unsupported resilient LLM method: {method_name}")
    from app.provider import get_home_rag_primary_fallback_llm, primary_chat_fallback_ready

    if primary_chat_fallback_ready(settings):
        fb = get_home_rag_primary_fallback_llm()
        log_event(
            logger,
            logging.INFO,
            "llm_local_circuit_open_fallback_invoked",
            stage=stage,
            method=method_name,
            fallback_base=str(getattr(settings, "home_rag_llm_fallback_api_base", "")),
            fallback_model=str(getattr(settings, "home_rag_llm_fallback_model", "")),
        )
        return getattr(fb, method_name)(*args, **kwargs)
    raise RuntimeError(
        f"LLM endpoint circuit is open for stage={stage}; local model is temporarily unavailable "
        "and HOME_RAG_LLM_FALLBACK_* is not ready."
    )


def _is_transient_error(exc: Exception) -> bool:
    """True when the error signals an unreachable or temporarily failing endpoint.

    Includes connection errors, timeouts and 5xx responses (expanded per plan #8
    so that circuit and cross-base fallback trigger on more transient failures).
    """
    name = type(exc).__name__.lower()
    if name in _TRANSIENT_ERROR_NAMES:
        return True

    # Additional timeout detection
    if "timeout" in name:
        return True

    # httpx / requests style 5xx
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            status = int(getattr(resp, "status_code", 0))
            if 500 <= status < 600:
                return True
        except (TypeError, ValueError):
            pass

    return False


def _local_soft_timeout_sec(settings) -> float | None:
    val = getattr(settings, "home_rag_llm_local_soft_timeout_sec", None)
    try:
        return max(0.0, float(val)) if val is not None else None
    except (TypeError, ValueError):
        return None


def _run_with_timeout(fn, timeout_sec: float, stage: str, base_url: str = "") -> Any:
    future = _LLM_POOL.submit(fn)
    try:
        return future.result(timeout=timeout_sec)
    except concurrent.futures.TimeoutError:
        logger.warning("llm_call_soft_timeout stage=%s timeout=%.1fs", stage, timeout_sec)
        if base_url:
            _record_circuit_failure(base_url, TimeoutError("soft_timeout"))
        raise TimeoutError(
            f"LLM call soft timeout after {timeout_sec}s (stage={stage})"
        )


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
    base_url = _llm_base_url(llm)
    if _circuit_open(base_url):
        if allow_provider_fallback is False:
            raise RuntimeError(f"LLM endpoint circuit is open for stage={stage}; fallback disabled.")
        return _fallback_or_raise_on_open_circuit(
            stage=stage,
            method_name="complete",
            args=(prompt,),
            kwargs=dict(kwargs),
        )
    try:
        if _is_local_llm_base(base_url):
            soft = _local_soft_timeout_sec(settings)
            if _circuit_open(base_url):
                soft = min(soft or 5.0, 1.5)  # A2 (plan #5): short timeout for known-unhealthy branch
            if soft and soft > 0:
                result = _run_with_timeout(
                    partial(llm.complete, prompt, **kwargs),
                    soft,
                    stage,
                    base_url=base_url,
                )
            else:
                result = llm.complete(prompt, **kwargs)
        else:
            result = llm.complete(prompt, **kwargs)
        _record_circuit_success(base_url)
        return result
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
        if _is_transient_error(e):
            _record_circuit_failure(base_url, e)
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
        if allow_provider_fallback is not False and _is_transient_error(e):
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
    base_url = _llm_base_url(llm)
    if _circuit_open(base_url):
        if allow_provider_fallback is False:
            raise RuntimeError(f"LLM endpoint circuit is open for stage={stage}; fallback disabled.")
        return _fallback_or_raise_on_open_circuit(
            stage=stage,
            method_name="chat",
            args=(messages,),
            kwargs=dict(kwargs),
        )
    try:
        if _is_local_llm_base(base_url):
            soft = _local_soft_timeout_sec(settings)
            if _circuit_open(base_url):
                soft = min(soft or 5.0, 1.5)  # A2 (plan #5): short timeout for known-unhealthy branch
            if soft and soft > 0:
                result = _run_with_timeout(
                    partial(llm.chat, messages, **kwargs),
                    soft,
                    stage,
                    base_url=base_url,
                )
            else:
                result = llm.chat(messages, **kwargs)
        else:
            result = llm.chat(messages, **kwargs)
        _record_circuit_success(base_url)
        return result
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
        if _is_transient_error(e):
            _record_circuit_failure(base_url, e)
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
        if allow_provider_fallback is not False and _is_transient_error(e):
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
