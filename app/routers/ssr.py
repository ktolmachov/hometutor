"""SSR explanation endpoint — streams 'why now' tokens via Server-Sent Events."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.logging_config import log_event
from app.ssr_explain_service import stream_explanation_tokens

router = APIRouter(tags=["ssr"])
logger = logging.getLogger(__name__)


class SsrExplainRequest(BaseModel):
    ctx: dict[str, Any]
    hint_kind: str
    primary_label_ru: str
    why_now_ru: str
    primary_nav: str
    route_pedagogy_ru: str = ""
    ml_audit_ru: str = ""
    has_secondaries: bool = False
    evidence_ledger: list[str] | None = None


@router.post("/ssr/explain")
def ssr_explain(req: SsrExplainRequest) -> StreamingResponse:
    """Stream SSR explanation tokens as Server-Sent Events.

    Each token is sent as ``data: <json-encoded-string>\\n\\n``.
    The stream closes with ``data: [DONE]\\n\\n``.
    On error the template text is yielded as a single token.
    """

    def _event_stream():
        started = time.perf_counter()
        token_count = 0
        try:
            for token in stream_explanation_tokens(
                req.ctx,
                hint_kind=req.hint_kind,
                primary_label_ru=req.primary_label_ru,
                why_now_ru=req.why_now_ru,
                primary_nav=req.primary_nav,
                route_pedagogy_ru=req.route_pedagogy_ru,
                ml_audit_ru=req.ml_audit_ru,
                has_secondaries=req.has_secondaries,
                evidence_ledger=req.evidence_ledger,
            ):
                token_count += 1
                yield f"data: {json.dumps(token)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            log_event(
                logger,
                logging.INFO,
                "ssr_explain_stream_completed",
                stream_ms=round((time.perf_counter() - started) * 1000, 3),
                token_count=token_count,
                hint_kind=req.hint_kind,
                primary_nav=req.primary_nav,
            )

    return StreamingResponse(_event_stream(), media_type="text/event-stream")
