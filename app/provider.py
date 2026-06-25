"""Centralized construction of LLM and embedding clients from settings."""

import logging
import socket
import time
from urllib.parse import urlparse

import httpx
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai.utils import ALL_AVAILABLE_MODELS, to_openai_message_dicts

from app.config import get_settings, is_cloud_model
from app.llm_local_circuit import is_open
from app.llm_guards import (
    BlockedModelError,
    HardLimitExceededError,
    NoRetryAfterError,
    log_cost_call,
    record_error_fingerprint,
    request_fingerprint,
)
from app.provider_openai import OpenAI, _raise_for_empty_openai_chat_choices
from app.token_utils import TokenValidator, estimate_messages_tokens

logger = logging.getLogger(__name__)

_e2e_primary_chat_call_count = 0

_SSR_LOOPBACK_REACH_TTL_SEC = 45.0
_ssr_loopback_reach_cache: dict[str, tuple[bool, float]] = {}


def normalize_openai_compatible_api_base(api_base: str) -> str:
    """Дополняет корневой URL до ``.../v1`` для локальных OpenAI-compatible серверов (LM Studio, Ollama)."""
    raw = (api_base or "").strip().rstrip("/")
    if not raw:
        return raw
    parsed = urlparse(raw)
    path = (parsed.path or "").rstrip("/")
    if path in ("", "/"):
        return f"{parsed.scheme}://{parsed.netloc}/v1"
    return raw


def _resolve_ssr_llm_api_key(settings, api_base: str) -> str:
    explicit = (settings.ssr_llm_api_key or "").strip()
    if explicit:
        return explicit
    shared = (settings.openai_api_key or "").strip()
    if shared:
        return shared
    parsed = urlparse(api_base)
    host = (parsed.hostname or "").lower()
    if host in ("127.0.0.1", "localhost") or (host.endswith(".local") if host else False):
        return "lm-studio"
    raise ValueError(
        "Для SSR LLM укажите SSR_LLM_API_KEY или OPENAI_API_KEY "
        "(или используйте локальный SSR_LLM_API_BASE — тогда применится ключ-заглушка)."
    )


def _is_loopback_hostname(hostname: str) -> bool:
    h = (hostname or "").strip().lower()
    return h in ("127.0.0.1", "localhost", "::1") or h.endswith(".local")


def _tcp_connect_reachable(host: str, port: int, *, timeout_sec: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def _loopback_ssr_tcp_reachable(normalized_base: str, *, timeout_sec: float = 0.6) -> bool:
    parsed = urlparse(normalized_base)
    host = parsed.hostname or ""
    if not host:
        return False
    scheme = (parsed.scheme or "http").lower()
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    return _tcp_connect_reachable(host, port, timeout_sec=timeout_sec)


def ssr_loopback_server_reachable_now(normalized_base: str) -> bool:
    """С кэшем TTL: слушает ли порт на loopback для SSR (LM Studio и т.п.)."""
    now = time.monotonic()
    cached = _ssr_loopback_reach_cache.get(normalized_base)
    if cached is not None and now - cached[1] < _SSR_LOOPBACK_REACH_TTL_SEC:
        return cached[0]
    ok = _loopback_ssr_tcp_reachable(normalized_base, timeout_sec=0.6)
    _ssr_loopback_reach_cache[normalized_base] = (ok, now)
    return ok


def _ssr_should_use_main_llm_instead_of_ssr(settings, normalized_base: str) -> bool:
    """Если SSR указывает на loopback, но порт недоступен — основной ``get_llm()`` (``LLM_MODEL``)."""
    if ssr_llm_shares_main_api_base(settings):
        return False
    host = (urlparse(normalized_base).hostname or "").strip().lower()
    if not _is_loopback_hostname(host):
        return False
    if ssr_loopback_server_reachable_now(normalized_base):
        return False
    logger.info(
        "ssr_llm_loopback_unreachable_using_main",
        extra={"ssr_base": normalized_base, "llm_model": getattr(settings, "llm_model", None)},
    )
    return True


def _llm_http_timeout(settings) -> httpx.Timeout:
    read_sec = float(getattr(settings, "llm_request_timeout", 60))
    conn = float(getattr(settings, "llm_connect_timeout_sec", 10.0))
    return httpx.Timeout(connect=conn, read=read_sec, write=read_sec, pool=5.0)


def _primary_local_read_cap_sec(settings) -> float:
    """Жёсткий read-cap для локального primary chat (дополняет LLM_REQUEST_TIMEOUT)."""
    cap = float(getattr(settings, "home_rag_llm_local_hard_timeout_sec", 20))
    legacy = float(getattr(settings, "llm_request_timeout", 30))
    return max(0.5, min(legacy, cap))


def _llm_http_timeout_local_primary(settings) -> httpx.Timeout:
    read_sec = _primary_local_read_cap_sec(settings)
    conn = float(getattr(settings, "llm_connect_timeout_sec", 10.0))
    return httpx.Timeout(connect=conn, read=read_sec, write=read_sec, pool=5.0)


def _llm_client_kwargs_local_primary(settings) -> dict:
    # max_retries=0: local LLM retries amplify hang time (3 × read_timeout) without
    # adding value — the model is either available or not. Fail fast and let the UI retry.
    # async_http_client: LlamaIndex QueryEngine uses async calls internally; without this
    # the sync http_client is silently ignored and LlamaIndex falls back to the openai SDK
    # default (60 s), bypassing HOME_RAG_LLM_LOCAL_HARD_TIMEOUT_SEC configuration.
    _timeout = _llm_http_timeout_local_primary(settings)
    return {
        "max_retries": 0,
        "http_client": httpx.Client(timeout=_timeout),
        "async_http_client": httpx.AsyncClient(timeout=_timeout),
    }


def _resolve_primary_fallback_api_base(settings) -> str | None:
    explicit = str(getattr(settings, "home_rag_llm_fallback_api_base", None) or "").strip()
    raw = explicit or str(getattr(settings, "openai_api_base", "") or "").strip()
    return normalize_openai_compatible_api_base(raw) if raw else None


def _resolve_primary_fallback_model(settings) -> str | None:
    explicit = str(getattr(settings, "home_rag_llm_fallback_model", None) or "").strip()
    if explicit:
        return explicit
    if getattr(settings, "enable_llm_fallback", False):
        fb = str(getattr(settings, "llm_fallback_model", None) or "").strip()
        if fb:
            return fb
    return str(getattr(settings, "llm_model", "") or "").strip() or None


def primary_chat_cloud_allowed(settings=None) -> bool:
    """Whether primary chat may use a cloud endpoint for the current data mode."""
    s = settings or get_settings()
    data_mode = str(getattr(s, "home_rag_data_mode", "real") or "real").strip().lower()
    if data_mode == "demo":
        return True
    return bool(getattr(s, "home_rag_llm_cloud_consent", False))


def primary_chat_fallback_ready(settings=None) -> bool:
    """True если balanced может уйти в облако при CB-open (ключ + база + модель настроены)."""
    s = settings or get_settings()
    if not getattr(s, "home_rag_llm_fallback_enabled", False):
        return False
    if not primary_chat_cloud_allowed(s):
        return False
    if not (s.openai_api_key or "").strip():
        return False
    fb_base = _resolve_primary_fallback_api_base(s)
    fb_model = _resolve_primary_fallback_model(s)
    return bool(fb_base and fb_model)


def _annotate_llm_source(
    llm,
    *,
    source: str,
    model: str | None,
    api_base: str | None,
    fallback_used: bool,
    profile: str | None,
):
    # Pydantic V2 модели (llama-index OpenAI) запрещают extra fields через обычный setattr.
    # object.__setattr__ записывает атрибут напрямую в __dict__, минуя pydantic-валидацию.
    object.__setattr__(llm, "home_rag_llm_source", source)
    object.__setattr__(llm, "home_rag_llm_model", model)
    object.__setattr__(llm, "home_rag_llm_api_base", api_base)
    object.__setattr__(llm, "home_rag_llm_fallback_used", bool(fallback_used))
    object.__setattr__(llm, "home_rag_llm_profile", profile)
    return llm


def llm_source_metadata(llm) -> dict[str, object]:
    """Stable source metadata for API/debug traces."""
    return {
        "llm_source": getattr(llm, "home_rag_llm_source", None),
        "llm_model": getattr(llm, "home_rag_llm_model", None) or getattr(llm, "model", None),
        "llm_api_base": getattr(llm, "home_rag_llm_api_base", None) or getattr(llm, "api_base", None),
        "fallback_used": bool(getattr(llm, "home_rag_llm_fallback_used", False)),
        "llm_profile": getattr(llm, "home_rag_llm_profile", None),
    }


def local_primary_chat_circuit_open(settings=None) -> bool:
    """CB открыт на URL основного локального LM endpoint."""
    s = settings or get_settings()
    raw = normalize_openai_compatible_api_base(_lmstudio_api_base(s))
    if not raw:
        return False
    return is_open(raw)


def _fixed_http_timeout(timeout_sec: float) -> httpx.Timeout:
    budget = max(0.1, float(timeout_sec))
    return httpx.Timeout(connect=budget, read=budget, write=budget, pool=budget)


def _embed_http_timeout(settings) -> httpx.Timeout:
    read_sec = float(getattr(settings, "embed_request_timeout", 60))
    conn = float(getattr(settings, "embed_connect_timeout_sec", 10.0))
    return httpx.Timeout(connect=conn, read=read_sec, write=read_sec, pool=5.0)


def _embed_client_kwargs(settings) -> dict:
    """Параметры SDK для embed-клиента.

    http_client не передаём — async_http_client уже задан в вызывающем коде;
    два клиента одновременно непредсказуемы и ломают max_retries.
    """
    return {
        "max_retries": getattr(settings, "embed_max_retries", 2),
        "timeout": float(getattr(settings, "embed_request_timeout", 60)),
    }


def _embed_api_base(settings) -> str:
    """OpenAI-compatible base URL for embeddings.

    LM Studio exposes embeddings at ``/v1/embeddings``. Keep bare loopback
    values like ``http://127.0.0.1:1234`` valid by normalizing them the same way
    as chat/model endpoints.
    """
    raw = str(getattr(settings, "embed_api_base_resolved", "") or "").strip()
    return normalize_openai_compatible_api_base(raw)


def _llm_client_kwargs(settings) -> dict:
    """OpenAI-совместимый клиент: retries SDK + явные connect/read таймауты (18 Core)."""
    return {
        "max_retries": getattr(settings, "llm_max_retries", 2),
        "http_client": httpx.Client(timeout=_llm_http_timeout(settings)),
    }


def _lmstudio_api_base(settings) -> str:
    """Базовый URL OpenAI-compatible API для **основного чат-LLM** (LM Studio, локальный прокси и т.п.).

    Не путать с ``OPENAI_API_BASE`` / ``get_quiz_llm()`` — там отдельная маршрутизация.

    **Почему два источника (``lmstudio_api_base`` и ``llm_api_base``):**

    1. В :class:`app.config.Settings` каноническое поле — ``lmstudio_api_base`` (env ``LMSTUDIO_API_BASE`` /
       ``LLM_API_BASE``). На него же указывает вычисляемое свойство ``llm_api_base`` — одно и то же
       значение, удобное имя для старого кода и тестов.

    2. В юнит-тестах часто подставляют лёгкий фейк настроек с **только** ``llm_api_base``, без
       атрибута ``lmstudio_api_base``. Если здесь читать исключительно ``lmstudio_api_base``,
       получится пустая строка → ``api_base=''`` у OpenAI-клиента и падения вроде
       ``test_build_evaluators_uses_configured_api_base`` / ``test_provider`` (уже было при откате
       «упрощения» этой функции).

    **Инвариант:** сначала непустой ``lmstudio_api_base`` (прод-конфиг), иначе fallback на
    ``llm_api_base``. Не удалять вторую ветку без синхронного обновления всех фейков и контракта
    тестов.
    """
    lm = str(getattr(settings, "lmstudio_api_base", "") or "").strip()
    llm = str(getattr(settings, "llm_api_base", "") or "").strip()
    raw = lm or llm
    return normalize_openai_compatible_api_base(raw)



# is_cloud_model is imported from app.config (single source of truth)


def _role_api_base_for_model(settings, model_name: str) -> str:
    """Resolve role-specific LLM base while keeping primary local qwen-style ids local.

    Secondary roles may be configured with OpenRouter-style ids such as
    ``openai/gpt-4o-mini`` or ``google/gemma-4-31b-it``. Those must use
    OPENAI_API_BASE. Local ids, including slash-style LM Studio ids like
    ``qwen/qwen3.6-27b``, stay on LMSTUDIO_API_BASE.
    """
    if is_cloud_model(model_name):
        return normalize_openai_compatible_api_base(settings.openai_api_base)
    return _lmstudio_api_base(settings)


def _build_role_llm(settings, *, model: str, api_base: str | None = None):
    resolved_base = (
        normalize_openai_compatible_api_base(api_base)
        if api_base
        else _role_api_base_for_model(settings, model)
    )
    return OpenAI(
        model=model,
        api_key=settings.openai_api_key,
        api_base=resolved_base,
        **_llm_client_kwargs(settings),
    )


def get_llm_fallback():
    """Запасная модель при ``enable_llm_fallback`` + ``llm_fallback_model`` (один вызов — см. llm_resilience)."""
    s = get_settings()
    if not s.openai_api_key:
        raise ValueError("OPENAI_API_KEY не найден в .env")
    if not (s.llm_fallback_model or "").strip():
        raise ValueError("LLM_FALLBACK_MODEL не задан")
    return OpenAI(
        model=s.llm_fallback_model.strip(),
        api_key=s.openai_api_key,
        api_base=_lmstudio_api_base(s),
        **_llm_client_kwargs(s),
    )


def get_home_rag_primary_fallback_llm():
    """Build the HOME_RAG_LLM_FALLBACK_* LLM (e.g. OpenRouter) for connection-error fallback.

    Called by llm_resilience when the primary endpoint (LM Studio) is unreachable so that
    generation can continue via a cloud provider without any manual .env change.

    Requires in .env:
        HOME_RAG_LLM_FALLBACK_ENABLED=true   (default: true)
        HOME_RAG_LLM_FALLBACK_API_BASE=https://openrouter.ai/api/v1
        HOME_RAG_LLM_FALLBACK_MODEL=openai/gpt-4o-mini
        OPENAI_API_KEY=sk-or-v1-...
    """
    s = get_settings()
    if not primary_chat_fallback_ready(s):
        raise ValueError(
            "HOME_RAG_LLM_FALLBACK_API_BASE and HOME_RAG_LLM_FALLBACK_MODEL must both be set "
            "with HOME_RAG_LLM_FALLBACK_ENABLED=true to use cross-base fallback"
        )
    fb_base = _resolve_primary_fallback_api_base(s)
    fb_model = _resolve_primary_fallback_model(s)
    llm = OpenAI(
        model=fb_model,
        api_key=s.openai_api_key,
        api_base=fb_base,
        **_llm_client_kwargs(s),
    )
    return _annotate_llm_source(
        llm,
        source="cloud",
        model=fb_model,
        api_base=fb_base,
        fallback_used=True,
        profile=str(getattr(s, "home_rag_local_profile", "balanced") or "balanced"),
    )


def get_e2e_primary_chat_call_count() -> int:
    """Observability hook for E2E: primary chat ``get_llm()`` invocations under offline mode."""
    return _e2e_primary_chat_call_count


def reset_e2e_primary_chat_call_count() -> None:
    global _e2e_primary_chat_call_count
    _e2e_primary_chat_call_count = 0


def get_llm():
    """Primary chat LLM: ``LOCAL_STRICT`` | ``BALANCED`` | ``CLOUD_FAST`` + CB-aware fallback.

    Не LRU-кэшируется: состояние ``LLM_LOCAL_CB_*`` меняется в рантайме; при ``BALANCED`` и CB-open —
    переходим на fallback endpoint (комплемент к технике timeouts, см. localhost balance план §Phase 2).
    """
    s = get_settings()
    if getattr(s, "home_rag_e2e_offline", False):
        global _e2e_primary_chat_call_count
        _e2e_primary_chat_call_count += 1
    if not s.openai_api_key:
        raise ValueError("OPENAI_API_KEY не найден в .env")

    profile = str(getattr(s, "home_rag_local_profile", "balanced") or "balanced").strip().lower()

    if profile == "cloud_fast":
        cloud_base = normalize_openai_compatible_api_base(s.openai_api_base)
        llm = OpenAI(
            model=s.llm_model,
            api_key=s.openai_api_key,
            api_base=cloud_base,
            **_llm_client_kwargs(s),
        )
        return _annotate_llm_source(
            llm,
            source="cloud",
            model=s.llm_model,
            api_base=cloud_base,
            fallback_used=False,
            profile=profile,
        )

    local_base_norm = normalize_openai_compatible_api_base(_lmstudio_api_base(s))
    cb_now = bool(local_base_norm and is_open(local_base_norm))

    if profile == "local_strict" and cb_now:
        raise ValueError(
            "HOME_RAG_LOCAL_PROFILE=local_strict: локальный primary chat LLM временно недоступен "
            "(circuit breaker на локальном endpoint открыт). Запустите локальный inference, "
            "исправьте LMSTUDIO_API_BASE, либо переключитесь на HOME_RAG_LOCAL_PROFILE=balanced "
            "с включённым HOME_RAG_LLM_FALLBACK_ENABLED и рабочим OPENROUTER/OPENAI base."
        )

    fallback_ready = primary_chat_fallback_ready(s)
    use_fallback = profile == "balanced" and cb_now and fallback_ready

    if profile == "balanced" and cb_now and not fallback_ready:
        logger.warning(
            "balanced_primary_chat_circuit_open_no_fallback_using_local_attempt",
            extra={"primary_local_base_url": local_base_norm},
        )

    if use_fallback:
        fb_base = _resolve_primary_fallback_api_base(s)
        fb_model = _resolve_primary_fallback_model(s)
        if not fb_base or not fb_model:
            raise RuntimeError("internal: fallback flagged ready but missing base/model")
        llm = OpenAI(
            model=fb_model,
            api_key=s.openai_api_key,
            api_base=fb_base,
            **_llm_client_kwargs(s),
        )
        return _annotate_llm_source(
            llm,
            source="cloud",
            model=fb_model,
            api_base=fb_base,
            fallback_used=True,
            profile=profile,
        )

    llm = OpenAI(
        model=s.llm_model,
        api_key=s.openai_api_key,
        api_base=local_base_norm,
        **_llm_client_kwargs_local_primary(s),
    )
    return _annotate_llm_source(
        llm,
        source="local",
        model=s.llm_model,
        api_base=local_base_norm,
        fallback_used=False,
        profile=profile,
    )


def get_ssr_llm_resolved():
    """Build the SSR LLM pair ``(llm, used_main_chat_llm)``.

    Falls back to the main ``get_llm()`` when the loopback SSR endpoint is unreachable.
    Availability is checked on every call because the local loopback endpoint can recover
    or disappear while the app process stays alive.

    Trade-off: each call allocates a new ``OpenAI`` + ``httpx.Client``.  Acceptable for
    single-user load; if SSR call volume grows, cache the client by ``(base, model)`` key
    and invalidate on reachability flip.
    """
    s = get_settings()
    raw_base = (s.ssr_llm_api_base or "").strip()
    base = normalize_openai_compatible_api_base(raw_base or _lmstudio_api_base(s))
    if not base:
        raise ValueError("SSR LLM: задайте SSR_LLM_API_BASE или LMSTUDIO_API_BASE")
    if _ssr_should_use_main_llm_instead_of_ssr(s, base):
        if not getattr(s, "ssr_allow_main_llm_fallback", False):
            raise RuntimeError(
                "SSR LLM loopback is unreachable and SSR_ALLOW_MAIN_LLM_FALLBACK is not set. "
                "Start LM Studio on the configured SSR endpoint, or set "
                "SSR_ALLOW_MAIN_LLM_FALLBACK=true to allow SSR to fall back to the primary chat LLM. "
                "Warning: when primary chat uses balanced profile with cloud fallback enabled, "
                "SSR personal data may reach a cloud provider."
            )
        return get_llm(), True
    model = (s.ssr_llm_model or "").strip() or s.llm_model
    api_key = _resolve_ssr_llm_api_key(s, base)
    return (
        OpenAI(
            model=model,
            api_key=api_key,
            api_base=base,
            **_llm_client_kwargs(s),
        ),
        False,
    )


def get_ssr_llm():
    """LLM только для SSR: персонализация короткой причины шага (отдельные baseURL/model)."""
    return get_ssr_llm_resolved()[0]


def ssr_llm_shares_main_api_base(settings=None) -> bool:
    """True, если первичный SSR-endpoint совпадает с основным чатом (после нормализации ``/v1``)."""
    s = settings or get_settings()
    raw = (getattr(s, "ssr_llm_api_base", None) or "").strip()
    ssr_base = normalize_openai_compatible_api_base(raw or _lmstudio_api_base(s))
    main_base = normalize_openai_compatible_api_base(_lmstudio_api_base(s))
    return bool(ssr_base) and bool(main_base) and ssr_base.rstrip("/") == main_base.rstrip("/")


def get_healthcheck_llm(*, timeout_sec: float = 2.0):
    """Build a short-lived LLM client for health probes with a strict timeout budget."""
    s = get_settings()
    if not s.openai_api_key:
        raise ValueError("OPENAI_API_KEY не найден в .env")
    timeout = max(0.1, float(timeout_sec))
    return OpenAI(
        model=s.llm_model,
        api_key=s.openai_api_key,
        api_base=_lmstudio_api_base(s),
        max_retries=0,
        timeout=timeout,
        reuse_client=False,
        http_client=httpx.Client(timeout=_fixed_http_timeout(timeout)),
    )


def get_judge_llm():
    """Build the evaluator LLM, preferably on a dedicated judge model."""
    s = get_settings()
    if not s.openai_api_key:
        raise ValueError("OPENAI_API_KEY не найден в .env")
    model = s.eval_judge_llm or s.llm_model
    if not s.eval_judge_llm:
        logger.warning(
            "Judge LLM model is not configured separately; falling back to main model | model=%s",
            s.llm_model,
        )
    return _build_role_llm(s, model=model)


def get_rewrite_llm():
    """Build LLM for query rewriting (cheap model when configured)."""
    s = get_settings()
    if not s.openai_api_key:
        raise ValueError("OPENAI_API_KEY не найден в .env")
    model = s.rewrite_model or s.llm_model
    return _build_role_llm(s, model=model)


def get_classifier_llm():
    """Build LLM for query classification (cheap model when configured)."""
    s = get_settings()
    if not s.openai_api_key:
        raise ValueError("OPENAI_API_KEY не найден в .env")
    model = s.classifier_model or s.llm_model
    return _build_role_llm(s, model=model)


def get_quiz_llm():
    """Build LLM for quiz question generation.

    Auto-routing by model name (no manual QUIZ_LLM_API_BASE needed):
      • cloud model (gpt-4o, claude, gemini…) → OPENAI_API_BASE (OpenRouter / OpenAI)
      • local model name                       → LMSTUDIO_API_BASE
    QUIZ_LLM_API_BASE overrides auto-detection when set explicitly.
    """
    s = get_settings()
    if not s.openai_api_key:
        raise ValueError("OPENAI_API_KEY не найден в .env")
    model = s.quiz_llm_model or s.llm_model
    explicit = (s.quiz_llm_api_base or "").strip()
    if explicit:
        api_base = normalize_openai_compatible_api_base(explicit)
    elif is_cloud_model(model):
        api_base = normalize_openai_compatible_api_base(s.openai_api_base)
    else:
        api_base = _lmstudio_api_base(s)
    return _build_role_llm(s, model=model, api_base=api_base)


def get_ingestion_llm():
    """LLM для ingestion-пайплайна (metadata, fallback извлечения текста); дешёвая модель по желанию."""
    s = get_settings()
    if not s.openai_api_key:
        raise ValueError("OPENAI_API_KEY не найден в .env")
    model = ((s.ingestion_model or "").strip() or s.llm_model)
    return _build_role_llm(s, model=model)


def get_obsidian_export_llm():
    """LLM для Obsidian map/reduce/compose с увеличенным read-timeout.

    obsidian_export_model → LLM_MODEL (основная локальная). Намеренно не использует
    _llm_client_kwargs_local_primary — его hard timeout слишком мал для map/compose.
    """
    s = get_settings()
    if not s.openai_api_key:
        raise ValueError("OPENAI_API_KEY не найден в .env")
    timeout_sec = float(getattr(s, "obsidian_export_llm_timeout_sec", 300))
    t = httpx.Timeout(connect=10.0, read=timeout_sec, write=timeout_sec, pool=5.0)
    model = ((getattr(s, "obsidian_export_model", None) or "").strip() or s.llm_model)
    api_base = normalize_openai_compatible_api_base(_lmstudio_api_base(s))
    return OpenAI(
        model=model,
        api_key=s.openai_api_key,
        api_base=api_base,
        max_retries=0,
        timeout=timeout_sec,
        http_client=httpx.Client(timeout=t),
        async_http_client=httpx.AsyncClient(timeout=t),
    )


def get_evaluate_llm():
    """LLM для оценки свободных ответов inline-quiz (не MC)."""
    s = get_settings()
    if not s.openai_api_key:
        raise ValueError("OPENAI_API_KEY не найден в .env")
    model = ((s.evaluate_model or "").strip() or s.llm_model)
    return _build_role_llm(s, model=model)


def get_graph_llm():
    """LLM for local graph/concept tasks."""
    s = get_settings()
    if not s.openai_api_key:
        raise ValueError("OPENAI_API_KEY не найден в .env")
    model = ((s.graph_model or "").strip() or s.llm_model)
    explicit_base = (s.graph_llm_api_base or "").strip()
    api_base = (
        normalize_openai_compatible_api_base(explicit_base)
        if explicit_base
        else _lmstudio_api_base(s)
    )
    return OpenAI(
        model=model,
        api_key=s.openai_api_key,
        api_base=api_base,
        **_llm_client_kwargs(s),
    )


def _make_embed_model(s) -> OpenAIEmbedding:
    dimensions = int(getattr(s, "embed_dimensions", 0) or 0)
    # Keep `model` llama-index/OpenAI enum-safe; `model_name` is the real
    # provider model id sent to OpenRouter, including custom ids.
    return OpenAIEmbedding(
        model="text-embedding-3-small",
        model_name=s.embed_model,
        dimensions=dimensions or None,
        api_key=s.openai_api_key,
        api_base=_embed_api_base(s),
        embed_batch_size=s.embed_batch_size,
        num_workers=s.embed_num_workers,
        async_http_client=httpx.AsyncClient(timeout=_embed_http_timeout(s)),
        **_embed_client_kwargs(s),
    )


def get_embed_model():
    """Build the embedding model for queries/retrieval (uses EMBED_* settings)."""
    s = get_settings()
    if not s.openai_api_key:
        raise ValueError("OPENAI_API_KEY не найден в .env")
    return _make_embed_model(s)
