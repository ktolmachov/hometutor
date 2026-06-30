from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import app.api_services as services
from app.api_auth import auth_scope, require_api_key
from app.api_helpers import cors_headers_list, cors_methods_list, cors_origins_list
from app.guardrails import InputGuardrailError, OutputGuardrailError
from app.config import PROJECT_ROOT_PATH, get_settings
from app.middleware import ErrorHandlingMiddleware, LoggingMiddleware, RateLimitMiddleware
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.ssr import router as ssr_router
from app.routers.debug_session_tape import router as debug_session_tape_router
from app.routers.dashboard import router as dashboard_router
from app.routers.core import router as core_router
from app.routers.feedback import router as feedback_router
from app.routers.files import router as files_router
from app.routers.knowledge import router as knowledge_router
from app.routers.learner import router as learner_router
from app.routers.metrics import router as metrics_router
from app.routers.query import router as query_router
from app.routers.flashcards import router as flashcards_router
from app.routers.quiz import router as quiz_router
from app.routers.review import router as review_router
from app.routers.sync import router as sync_router
from app.routers.sessions import router as sessions_router
from app.retrieval_cache import EmptyIndexError, ReindexInProgressError


def _bm25_warmup_background() -> None:
    """Pre-warm BM25 cache for the default profile's top_k (fast=2, quality=10)."""
    log = logging.getLogger(PROJECT_ROOT_PATH)
    log.info("BM25 warmup thread started")
    try:
        from app.hybrid_retrieval import get_bm25_retriever, _BM25_MAX_NODES
        from app.retrieval_cache import get_base_services
        from app.config import get_retrieval_settings

        services = get_base_services()
        collection = services.get("collection")
        if collection is None:
            log.warning("BM25 warmup skipped: collection is None after base services init")
            return

        node_count = collection.count()
        if node_count > _BM25_MAX_NODES:
            log.warning(
                "BM25 warmup skipped: collection has %d nodes (limit %d). "
                "BM25 will be unavailable; consider switching to vector_only mode.",
                node_count, _BM25_MAX_NODES,
            )
            return

        r_settings = get_retrieval_settings()
        profile = (r_settings.rag_profile or "fast").strip().lower() or "fast"
        if profile == "fast":
            top_k = min(r_settings.similarity_top_k, 2)
        else:
            top_k = r_settings.similarity_top_k

        get_bm25_retriever(collection, similarity_top_k=top_k, filters=None)
        log.info("BM25 cache warmed up at startup | profile=%s | top_k=%s", profile, top_k)
    except Exception as e:  # noqa: BLE001 - background warmup failure is non-fatal for startup
        log.warning("BM25 background warm-up failed: %s", e, exc_info=True)


def _catalog_warmup_background() -> None:
    """Pre-warm topics catalog cache so /ui/bootstrap never blocks on a cold Chroma scan."""
    log = logging.getLogger(PROJECT_ROOT_PATH)
    try:
        from app.knowledge_catalog import get_topics_catalog
        get_topics_catalog()
        log.info("Topics catalog warmed up at startup.")
    except Exception as e:  # noqa: BLE001 - background warmup failure is non-fatal for startup
        log.warning("Catalog warmup skipped: %s", e)


def _readiness_warmup_background() -> None:
    """Pre-warm source readiness cache (filesystem scan) so /ui/bootstrap is fast."""
    log = logging.getLogger(PROJECT_ROOT_PATH)
    try:
        from app.api_services import _bootstrap_readiness
        _bootstrap_readiness()
        log.info("Source readiness warmed up at startup.")
    except Exception as e:  # noqa: BLE001 - background warmup failure is non-fatal for startup
        log.warning("Readiness warmup skipped: %s", e)


def _index_stats_warmup_background() -> None:
    """Pre-warm index stats cache (full Chroma metadata scan) so /ui/bootstrap is fast."""
    log = logging.getLogger(PROJECT_ROOT_PATH)
    try:
        from app.index_diff import get_index_stats
        get_index_stats()
        log.info("Index stats warmed up at startup.")
    except Exception as e:  # noqa: BLE001 - background warmup failure is non-fatal for startup
        log.warning("Index stats warmup skipped: %s", e)


def _ssr_semantic_cache_warmup_background() -> None:
    """Pre-load sentence-transformers model so first SSR request doesn't pay ~2s model init."""
    log = logging.getLogger(PROJECT_ROOT_PATH)
    try:
        from app.ssr_semantic_cache import _load_embeddings_model
        model = _load_embeddings_model()
        if model is not None:
            log.info("SSR semantic cache model warmed up at startup.")
        else:
            log.debug("SSR semantic cache model unavailable at startup (sentence_transformers not installed).")
    except Exception as e:  # noqa: BLE001 - background warmup failure is non-fatal for startup
        log.warning("SSR semantic cache warmup skipped: %s", e)


def _llm_local_warmup_background() -> None:
    """Probe the local SSR LLM endpoint at startup.

    Runs in a daemon thread so it never delays the API coming online.
    Logs a clear warning if the model is missing or the endpoint is unreachable,
    and seeds the circuit-breaker state so the first SSR card renders instantly
    instead of waiting for a connection timeout.
    """
    log = logging.getLogger(__name__)
    try:
        from app.llm_local_health import probe_local_llm
        from app.llm_local_circuit import record_failure, record_success
        from app.provider import ssr_llm_shares_main_api_base
        from app.logging_config import log_event

        settings = get_settings()
        base = (settings.ssr_llm_api_base or "").strip() or settings.lmstudio_api_base
        model = (settings.ssr_llm_model or "").strip() or settings.llm_model
        result = probe_local_llm(
            base,
            model,
            shares_main_base=ssr_llm_shares_main_api_base(settings),
        )
        if result.get("skipped"):
            return
        if result.get("reachable"):
            if result.get("model_loaded") is False:
                log_event(
                    log,
                    logging.WARNING,
                    "llm_local_warmup_model_missing",
                    base_url=base,
                    model=model,
                    models_count=result.get("models_count", 0),
                )
            else:
                record_success(base)
                log_event(
                    log,
                    logging.INFO,
                    "llm_local_warmup_ok",
                    base_url=base,
                    model=model,
                    latency_ms=result.get("latency_ms"),
                )
        else:
            record_failure(base, error_type="startup_probe_failed")
            log_event(
                log,
                logging.WARNING,
                "llm_local_warmup_unreachable",
                base_url=base,
                model=model,
                error=result.get("error"),
            )
    except Exception as e:  # noqa: BLE001 - background LLM probe failure is non-fatal for startup
        logging.getLogger(__name__).warning("LLM local warmup probe failed: %s", e)


@asynccontextmanager
async def _app_lifespan(_: FastAPI):
    from app.otel_tracing import init_otel_if_enabled, shutdown_otel_if_needed

    init_otel_if_enabled()
    log = logging.getLogger(PROJECT_ROOT_PATH)
    # Index-independent warmups start immediately (no Chroma needed).
    threading.Thread(
        target=_readiness_warmup_background,
        name="readiness-warmup",
        daemon=True,
    ).start()
    threading.Thread(
        target=_ssr_semantic_cache_warmup_background,
        name="ssr-semantic-cache-warmup",
        daemon=True,
    ).start()
    try:
        from app.retrieval_cache import get_base_services

        # 30-second timeout prevents a locked/corrupt ChromaDB from blocking the
        # entire uvicorn startup. If it times out the server starts without
        # retrieval (queries degrade gracefully) rather than hanging forever.
        try:
            await asyncio.wait_for(asyncio.to_thread(get_base_services), timeout=30.0)
        except asyncio.TimeoutError:
            log.warning(
                "Retrieval base services warmup timed out after 30 s. "
                "ChromaDB may be locked by a previous crashed process. "
                "Server starting without pre-warmed retrieval cache."
            )
            raise  # re-raise so the outer except skips the dependent warmup threads
        log.info("Retrieval base services warmed up at startup.")
        from app.request_cache import get_request_cache as _get_request_cache

        _get_request_cache()  # pre-init singleton so first /ask doesn't show "Initialized" mid-request
        # Start index-dependent warmups AFTER get_base_services so they reuse
        # the cached Chroma client and don't race each other for memory.
        threading.Thread(
            target=_index_stats_warmup_background,
            name="index-stats-warmup",
            daemon=True,
        ).start()
        # BM25 warmup is intentionally NOT started here.
        # bm25s raises MemoryError from C-level allocations that cannot be caught
        # reliably by a Python except-block, causing the server process to crash on
        # machines where the collection + embed model + SSR model leave little
        # headroom. BM25 is built lazily on the first hybrid/bm25_only query;
        # the _BM25_MAX_NODES guard in _nodes_from_chroma prevents OOM at that point.
        threading.Thread(
            target=_catalog_warmup_background,
            name="catalog-warmup",
            daemon=True,
        ).start()
    except Exception as e:  # noqa: BLE001 - background warmup startup failure is non-fatal
        log.warning("Retrieval warmup skipped (empty index or config): %s", e)
    if get_settings().llm_local_warmup:
        threading.Thread(
            target=_llm_local_warmup_background,
            name="llm-local-warmup",
            daemon=True,
        ).start()
    try:
        yield
    finally:
        shutdown_otel_if_needed()
        try:
            from app.retrieval_cache import clear_retrieval_cache

            clear_retrieval_cache()
            log.info("Retrieval cache cleared on shutdown.")
        except Exception as e:  # noqa: BLE001 - shutdown cache cleanup failure is non-fatal
            log.warning("Retrieval cache clear on shutdown failed: %s", e)


app = FastAPI(title="Home RAG API", lifespan=_app_lifespan)

_rl = int(get_settings().api_rate_limit_per_minute or 0)
if _rl > 0:
    app.add_middleware(RateLimitMiddleware, requests_per_minute=_rl)

app.add_middleware(LoggingMiddleware)
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_list(),
    allow_credentials=True,
    allow_methods=cors_methods_list(),
    allow_headers=cors_headers_list(),
)

app.include_router(core_router)
app.include_router(ssr_router)
app.include_router(auth_router)
# auth_scope — no-op при AUTH_ENABLED=false (default); require_api_key — no-op без HOME_RAG_API_KEY.
# Оба условия сохраняют поведение single-user режима без изменений (см. docs/compliance_upgrade_plan.md §A8).
_protected_dependencies = [Depends(require_api_key), Depends(auth_scope)]
app.include_router(dashboard_router, dependencies=_protected_dependencies)
app.include_router(sync_router, dependencies=_protected_dependencies)
app.include_router(sessions_router, dependencies=_protected_dependencies)
app.include_router(review_router, dependencies=_protected_dependencies)
app.include_router(query_router, dependencies=_protected_dependencies)
app.include_router(quiz_router, dependencies=_protected_dependencies)
app.include_router(flashcards_router, dependencies=_protected_dependencies)
app.include_router(metrics_router, dependencies=_protected_dependencies)
app.include_router(knowledge_router, dependencies=_protected_dependencies)
app.include_router(learner_router, dependencies=_protected_dependencies)
app.include_router(feedback_router, dependencies=_protected_dependencies)
app.include_router(files_router, dependencies=_protected_dependencies)
app.include_router(admin_router, dependencies=_protected_dependencies)
app.include_router(debug_session_tape_router, dependencies=_protected_dependencies)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_: Request, exc: RequestValidationError):
    status_code, detail = services.map_request_validation_error(exc)
    return JSONResponse(status_code=status_code, content={"detail": detail})


__all__ = [
    "app",
    "services",
    "EmptyIndexError",
    "ReindexInProgressError",
    "InputGuardrailError",
    "OutputGuardrailError",
]
