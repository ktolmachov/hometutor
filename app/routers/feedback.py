"""HTTP API для локальной записи SSR misroute feedback (accept/reject/defer)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.api_requests import SsrRecommendationFeedbackPostRequest
from app.ssr_feedback_collection import record_ssr_misroute_feedback_api

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ssr-feedback"])


@router.post("/ssr/recommendation-feedback")
def post_ssr_recommendation_feedback(body: SsrRecommendationFeedbackPostRequest) -> dict[str, object]:
    try:
        row_id = record_ssr_misroute_feedback_api(
            action=body.action,
            hint_kind=body.hint_kind,
            primary_nav=body.primary_nav,
            weak_concept_sha256_val=body.weak_concept_sha256,
            why_now_len=body.why_now_len,
            explanation_outcome=body.explanation_outcome,
            latency_ms=body.latency_ms,
            session_key_prefix=body.session_key_prefix,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("ssr_feedback_api_failed")
        raise HTTPException(status_code=500, detail="feedback_storage_failed") from exc
    return {"status": "ok", "id": row_id}
