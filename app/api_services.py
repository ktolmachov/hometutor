from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError, wait as futures_wait
from typing import Any

from app import faq_memory
from app.config import DATA_DIR, get_settings
from app.compare_eval import compare_two_configs_with_eval
from app.educational_metrics_service import (
    get_educational_metrics_report,
    get_mastery_validation_report,
)
from app.explain_service import explain_file, get_file_content
from app.feedback_service import append_feedback, get_feedback_summary
from app.history_service import append_history_entry, get_history, get_pipeline_trace
from app.index_diff import get_index_diff, get_index_stats
from app.index_registry import get_index_version_public
from app.ingestion import build_index, get_ingestion_status
from app.input_validation import build_error_detail, map_request_validation_error, prepare_ask_request
from app.knowledge_graph import (
    get_graph_prerequisites_health,
    get_learning_plan_graph_bundle,
    get_next_best_actions_for_user,
)
from app.knowledge_service import (
    build_learning_plan,
    get_kb_overview,
    get_proactive_suggestions,
    get_topics_catalog,
    search_knowledge_base,
    synthesize_topic,
)
from app.learner_model_service import (
    get_learner_profile_history,
    get_learner_profile_migration_metrics,
    get_learner_state_health,
    get_personalized_learner_profile,
)
from app.metrics import (
    evaluate_slo_alerts_and_notify,
    get_cost_dashboard,
    get_knowledge_workflow_metrics,
    get_metrics,
    get_metrics_dashboard,
    get_metrics_store,
    get_quality_metrics,
    record_error,
    record_knowledge_workflow_event,
    record_request,
)
from app.pipeline_profiler import run_profiled_query
from app.provider import get_llm
from app.query_service import answer_question, get_answer_flow_stats, reset_answer_flow_stats
from app.retrieval import build_query_engine
from app.source_readiness import build_source_readiness_summary
from app.retrieval_cache import (
    EmptyIndexError,
    EmbedModelMismatchError,
    ReindexInProgressError,
    clear_retrieval_cache,
    get_cache_stats,
    get_base_services,
    is_base_services_ready,
    is_reindex_in_progress,
    reindex_end,
    try_reindex_begin,
)


def get_index_version() -> dict[str, Any]:
    return get_index_version_public()


def _probe_local_llm_for_bootstrap() -> dict[str, Any] | None:
    """Best-effort SSR LLM health probe; ``None`` on internal failure."""
    try:
        from app.llm_local_health import probe_local_llm
        from app.provider import ssr_llm_shares_main_api_base

        settings = get_settings()
        base = (settings.ssr_llm_api_base or "").strip() or settings.lmstudio_api_base
        model = (settings.ssr_llm_model or "").strip() or settings.llm_model
        return probe_local_llm(
            base,
            model,
            shares_main_base=ssr_llm_shares_main_api_base(settings),
        )
    except Exception as exc:  # noqa: BLE001 - probe must never break bootstrap.
        return {"reachable": False, "error": f"probe_failed: {type(exc).__name__}: {exc}"}


def _bootstrap_kb_and_overview() -> dict[str, Any]:
    """Return kb_overview if services are already warm; skip init to keep bootstrap fast.

    Services are pre-warmed at startup via the lifespan handler. If they aren't ready
    (e.g. warmup was skipped due to empty index), return null overview immediately rather
    than blocking the first user request for 10–15 s on embedding model init.

    Catalog is only used if already in cache — never trigger a cold Chroma scan here.
    The catalog is pre-warmed in a background thread from the startup lifespan.
    """
    if not is_base_services_ready():
        return {"overview": None}
    from app.knowledge_catalog import _catalog_cache_get
    cached_catalog = _catalog_cache_get()
    if cached_catalog is None:
        return {"overview": None}
    try:
        return {"overview": get_kb_overview(catalog=cached_catalog)}
    except Exception as exc:  # noqa: BLE001
        return {"overview": None, "error": f"{type(exc).__name__}: {exc}"}


_readiness_cache: dict[str, Any] = {}
_readiness_cache_lock = threading.Lock()
_readiness_building_lock = threading.Lock()
_READINESS_TTL = 600  # longer than Streamlit bootstrap cache (300s) to avoid cold scan on reload


def invalidate_readiness_cache() -> None:
    with _readiness_cache_lock:
        _readiness_cache.clear()


def _bootstrap_readiness() -> dict[str, Any] | None:
    with _readiness_cache_lock:
        entry = _readiness_cache.get("value")
        ts = _readiness_cache.get("ts", 0.0)
        if entry is not None and (time.monotonic() - ts) < _READINESS_TTL:
            return entry
    # Non-blocking acquire: if a scan is already running (e.g. startup warmup),
    # return None immediately so bootstrap doesn't block on a duplicate cold scan.
    acquired = _readiness_building_lock.acquire(blocking=False)
    if not acquired:
        return None
    try:
        result = build_source_readiness_summary(DATA_DIR, get_settings())
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        _readiness_building_lock.release()
    with _readiness_cache_lock:
        _readiness_cache["value"] = result
        _readiness_cache["ts"] = time.monotonic()
    return result


def get_ui_bootstrap() -> dict[str, Any]:
    """
    Один быстрый ответ для главного экрана Streamlit: stats + hero overview.
    Каталог тем намеренно не включаем: он лениво догружается через ``/topics``
    только там, где реально нужен, чтобы не тормозить первый рендер home.

    Четыре независимых задачи запускаются параллельно в ThreadPoolExecutor:
    index_stats, source_readiness, llm_local probe и kb_overview.
    На cold start это сокращает latency примерно с последовательной суммы
    до max(slowest_task).
    """
    tasks = {
        "index_stats": get_index_stats,
        "readiness": _bootstrap_readiness,
        "llm_local": _probe_local_llm_for_bootstrap,
        "kb": _bootstrap_kb_and_overview,
    }
    results: dict[str, Any] = {}
    _BOOTSTRAP_TIMEOUT = 5.0  # hard cap; slow tasks return None rather than blocking the page
    # Use explicit shutdown(wait=False) so timed-out tasks finish in the background
    # without blocking the HTTP response. The `with` form calls shutdown(wait=True)
    # on exit, which negates the futures_wait timeout entirely.
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bootstrap")
    try:
        futures: dict[Future, str] = {pool.submit(fn): name for name, fn in tasks.items()}
        done, pending = futures_wait(futures, timeout=_BOOTSTRAP_TIMEOUT)
        for future in done:
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as exc:  # noqa: BLE001
                results[name] = {"__error": f"{type(exc).__name__}: {exc}"}
        for future in pending:
            results[futures[future]] = None
    finally:
        pool.shutdown(wait=False)  # don't block — timed-out tasks complete in background

    kb = results.get("kb") or {}
    payload: dict[str, Any] = {
        "index_stats": results.get("index_stats"),
        "kb_overview": kb.get("overview"),
        "source_readiness": results.get("readiness"),
        "llm_local": results.get("llm_local"),
    }
    if "error" in kb:
        payload["error"] = kb["error"]
    return payload


def get_educational_metrics(*, limit_quiz_rows: int = 5000) -> dict[str, Any]:
    return get_educational_metrics_report(limit_quiz_rows=limit_quiz_rows)


def get_mastery_validation_metrics(*, limit_quiz_rows: int = 5000) -> dict[str, Any]:
    return get_mastery_validation_report(limit_quiz_rows=limit_quiz_rows)
