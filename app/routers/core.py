from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException
from httpx import TimeoutException
from openai import APITimeoutError

from app.api_models import HealthResponse, RootResponse
from app.api_helpers import record_api_error
from app.api_services import get_index_stats, get_learner_state_health, get_ui_bootstrap
from app.logging_config import setup_logging
from app.provider import get_healthcheck_llm, llm_source_metadata

router = APIRouter(tags=["core"])
logger = setup_logging()


@router.get("/", response_model=RootResponse)
def root():
    return {
        "message": "Home RAG API is running",
        "docs": "/docs",
        "health": "/health",
    }


@router.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok"}


@router.get("/learner/state/health", response_model=dict)
def learner_state_health(user_id: str = "local", session_id: str | None = None, limit_history: int = 200):
    try:
        return get_learner_state_health(user_id, session_id=session_id, limit_history=limit_history)
    except Exception as e:  # noqa: BLE001 - core API boundary records learner-state failures as controlled HTTP 500.
        record_api_error(endpoint="/learner/state/health", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Learner state health failed: {type(e).__name__}: {e}",
        )


@router.get("/ui/bootstrap")
def ui_bootstrap():
    """Пакет данных для главной Streamlit: один round-trip вместо /index/stats + /kb/overview + /topics."""
    try:
        return get_ui_bootstrap()
    except Exception as e:  # noqa: BLE001 - core API boundary records bootstrap failures as controlled HTTP 500.
        record_api_error(endpoint="/ui/bootstrap", exc=e, status_code=500)
        raise HTTPException(status_code=500, detail=f"ui/bootstrap failed: {type(e).__name__}: {e}") from e


@router.get("/tutor/example")
def tutor_example():
    """Пример тела запроса для режима tutor (см. ``AskRequest.query_mode``)."""
    return {
        "example": {
            "question": "Что такое RAG?",
            "query_mode": "tutor",
            "session_id": "demo-session-id",
            "quiz_learning_mode": "auto",
        },
        "example_homework_in_tutor_session": {
            "question": "Дай план для задачи про chunking",
            "query_mode": "tutor",
            "session_id": "demo-session-id",
            "homework_level": "plan",
        },
    }


@router.get("/health/deep")
def health_deep():
    components: dict[str, dict] = {}
    overall_status = "ok"

    try:
        index_stats = get_index_stats()
        index_status = "ok"
        if index_stats.get("status") != "ok":
            index_status = "missing"
        elif index_stats.get("documents_count", 0) == 0:
            index_status = "empty"

        components["index"] = {
            "status": index_status,
            "collection_name": index_stats.get("collection_name"),
            "documents_count": index_stats.get("documents_count", 0),
            "nodes_count": index_stats.get("nodes_count", 0),
        }
        if index_status != "ok":
            overall_status = "degraded"
    except Exception as e:  # noqa: BLE001 - deep health must degrade instead of failing the whole endpoint.
        record_api_error(endpoint="/health/deep", exc=e, status_code=500)
        components["index"] = {"status": "error", "error": str(e)}
        overall_status = "degraded"

    health_deep_llm_timeout_sec = 2.0
    llm_meta: dict = {}
    try:
        llm = get_healthcheck_llm(timeout_sec=health_deep_llm_timeout_sec)
        llm_meta = llm_source_metadata(llm)
        t1 = time.perf_counter()
        _ = llm.complete("health check", max_tokens=1)
        latency_ms = (time.perf_counter() - t1) * 1000
        components["llm"] = {
            "status": "ok",
            "latency_ms": round(latency_ms, 3),
            **llm_meta,
        }
    except (TimeoutError, TimeoutException, APITimeoutError):
        record_api_error(endpoint="/health/deep", exc=TimeoutError("health_deep_llm_timeout"), status_code=503)
        components["llm"] = {
            "status": "timeout",
            "timeout_sec": health_deep_llm_timeout_sec,
            **llm_meta,
        }
        overall_status = "degraded"
    except Exception as e:  # noqa: BLE001 - deep health must degrade instead of failing the whole endpoint.
        record_api_error(endpoint="/health/deep", exc=e, status_code=500)
        components["llm"] = {"status": "error", "error": str(e), **llm_meta}
        overall_status = "degraded"

    components["api"] = {"status": "ok"}

    return {
        "status": overall_status,
        "components": components,
    }
