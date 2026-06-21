from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

import app.api_services as services
from app.api_helpers import record_api_error
from app.api_models import (
    CostDashboardResponse,
    FeedbackRequest,
    FeedbackSummaryResponse,
    KnowledgeWorkflowEventRequest,
    MetricsStoreResponse,
    PipelineTraceResponse,
    QualityMetricsResponse,
)

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_model=dict[str, Any])
def metrics():
    return services.get_metrics()


@router.get("/metrics/quality", response_model=QualityMetricsResponse)
def metrics_quality(limit: int = 200, http_request: Request = None):
    try:
        return services.get_quality_metrics(limit=limit)
    except Exception as e:  # noqa: BLE001 - metrics API boundary records store/service failures as controlled HTTP 500.
        record_api_error(endpoint="/metrics/quality", exc=e, request=http_request, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Metrics quality query failed: {type(e).__name__}: {e}",
        )


@router.get("/metrics/cost", response_model=CostDashboardResponse)
def metrics_cost(limit: int = 200, top_n: int = 5, http_request: Request = None):
    try:
        return services.get_cost_dashboard(limit=limit, top_n=top_n)
    except Exception as e:  # noqa: BLE001 - metrics API boundary records store/service failures as controlled HTTP 500.
        record_api_error(endpoint="/metrics/cost", exc=e, request=http_request, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Metrics cost query failed: {type(e).__name__}: {e}",
        )


@router.get("/metrics/dashboard", response_model=dict[str, Any])
def metrics_dashboard(limit_events: int = 20000, http_request: Request = None):
    try:
        return services.get_metrics_dashboard(limit_events=limit_events)
    except Exception as e:  # noqa: BLE001 - metrics API boundary records store/service failures as controlled HTTP 500.
        record_api_error(endpoint="/metrics/dashboard", exc=e, request=http_request, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Metrics dashboard query failed: {type(e).__name__}: {e}",
        )


@router.get("/metrics/learner", response_model=dict[str, Any])
def metrics_learner(limit_history: int = 200, http_request: Request = None):
    try:
        return {
            "schema_version": 1,
            "learner_profile_history": services.get_learner_profile_migration_metrics(limit=limit_history),
        }
    except Exception as e:  # noqa: BLE001 - metrics API boundary records store/service failures as controlled HTTP 500.
        record_api_error(endpoint="/metrics/learner", exc=e, request=http_request, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Metrics learner query failed: {type(e).__name__}: {e}",
        )


@router.get("/metrics/educational", response_model=dict[str, Any])
def metrics_educational(limit_quiz_rows: int = 5000, http_request: Request = None):
    """Aggregated quiz correctness, retention (7d+), transfer, SRS stability, micro-quiz parse."""
    lim = max(1, min(int(limit_quiz_rows), 50_000))
    try:
        return services.get_educational_metrics(limit_quiz_rows=lim)
    except Exception as e:  # noqa: BLE001 - metrics API boundary records store/service failures as controlled HTTP 500.
        record_api_error(endpoint="/metrics/educational", exc=e, request=http_request, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Educational metrics query failed: {type(e).__name__}: {e}",
        )


@router.get("/metrics/mastery-validation", response_model=dict[str, Any])
def metrics_mastery_validation(limit_quiz_rows: int = 5000, http_request: Request = None):
    """Mastery/quiz correlation, transfer state, false-positive graduation signals."""
    lim = max(1, min(int(limit_quiz_rows), 50_000))
    try:
        return services.get_mastery_validation_metrics(limit_quiz_rows=lim)
    except Exception as e:  # noqa: BLE001 - metrics API boundary records store/service failures as controlled HTTP 500.
        record_api_error(endpoint="/metrics/mastery-validation", exc=e, request=http_request, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Mastery validation metrics query failed: {type(e).__name__}: {e}",
        )


@router.get("/metrics/alerts", response_model=dict[str, Any])
def metrics_alerts(
    limit_events: int = 20000,
    notify: bool = False,
    http_request: Request = None,
):
    """SLO / anomaly alerts по metrics_store; notify=1 — опциональный webhook (см. ALERT_WEBHOOK_URL)."""
    try:
        return services.evaluate_slo_alerts_and_notify(limit_events=limit_events, send_webhook=notify)
    except Exception as e:  # noqa: BLE001 - metrics API boundary records store/service failures as controlled HTTP 500.
        record_api_error(endpoint="/metrics/alerts", exc=e, request=http_request, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Metrics alerts failed: {type(e).__name__}: {e}",
        )


@router.post("/metrics/knowledge-workflow")
def post_knowledge_workflow(body: KnowledgeWorkflowEventRequest, http_request: Request = None):
    try:
        services.record_knowledge_workflow_event(
            action=body.action,
            knowledge_product_trace=body.knowledge_product_trace,
            payload=body.payload,
            client_event_id=body.client_event_id,
        )
        return {"status": "ok"}
    except Exception as e:  # noqa: BLE001 - metrics API boundary records store/service failures as controlled HTTP 500.
        record_api_error(endpoint="/metrics/knowledge-workflow", exc=e, request=http_request, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Knowledge workflow metric failed: {type(e).__name__}: {e}",
        )


@router.get("/metrics/knowledge-workflow", response_model=dict[str, Any])
def knowledge_workflow_metrics(limit_events: int = 20000, http_request: Request = None):
    try:
        return services.get_knowledge_workflow_metrics(limit_events=limit_events)
    except Exception as e:  # noqa: BLE001 - metrics API boundary records store/service failures as controlled HTTP 500.
        record_api_error(endpoint="/metrics/knowledge-workflow", exc=e, request=http_request, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Knowledge workflow metrics query failed: {type(e).__name__}: {e}",
        )


@router.post("/feedback")
def post_feedback(body: FeedbackRequest, http_request: Request = None):
    try:
        services.append_feedback(
            helpful=body.helpful,
            request_id=body.request_id,
            comment=body.comment,
            question_preview=body.question_preview,
            source=body.source,
        )
        return {"status": "ok"}
    except Exception as e:  # noqa: BLE001 - metrics API boundary records store/service failures as controlled HTTP 500.
        record_api_error(endpoint="/feedback", exc=e, request=http_request, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Feedback save failed: {type(e).__name__}: {e}",
        )


@router.get("/metrics/feedback", response_model=FeedbackSummaryResponse)
def metrics_feedback(limit_lines: int = 5000, http_request: Request = None):
    try:
        return services.get_feedback_summary(limit_lines=limit_lines)
    except Exception as e:  # noqa: BLE001 - metrics API boundary records store/service failures as controlled HTTP 500.
        record_api_error(endpoint="/metrics/feedback", exc=e, request=http_request, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Feedback summary failed: {type(e).__name__}: {e}",
        )


@router.get("/metrics/store", response_model=MetricsStoreResponse)
def metrics_store(request_id: Optional[str] = None, limit: int = 20, http_request: Request = None):
    try:
        return services.get_metrics_store(request_id=request_id, limit=limit)
    except Exception as e:  # noqa: BLE001 - metrics API boundary records store/service failures as controlled HTTP 500.
        record_api_error(endpoint="/metrics/store", exc=e, request=http_request, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Metrics store query failed: {type(e).__name__}: {e}",
        )


@router.get("/history", response_model=dict[str, Any])
def history(
    q: Optional[str] = None,
    limit: int = 20,
    since: Optional[str] = None,
    until: Optional[str] = None,
    topic: Optional[str] = None,
    http_request: Request = None,
):
    try:
        return services.get_history(q=q, limit=limit, since=since, until=until, topic=topic)
    except Exception as e:  # noqa: BLE001 - metrics API boundary records store/service failures as controlled HTTP 500.
        record_api_error(endpoint="/history", exc=e, request=http_request, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"History query failed: {type(e).__name__}: {e}",
        )


@router.get("/pipeline/trace", response_model=PipelineTraceResponse)
def pipeline_trace(request_id: Optional[str] = None, limit: int = 20, http_request: Request = None):
    try:
        return services.get_pipeline_trace(request_id=request_id, limit=limit)
    except Exception as e:  # noqa: BLE001 - metrics API boundary records store/service failures as controlled HTTP 500.
        record_api_error(endpoint="/pipeline/trace", exc=e, request=http_request, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Pipeline trace query failed: {type(e).__name__}: {e}",
        )
