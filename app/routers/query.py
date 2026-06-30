from __future__ import annotations

import logging
import uuid
import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from app.session_store import session_store
from app.models import Message
from app.config import get_settings

import app.api_services as services
from app.api_helpers import record_api_error
from app.ask_goal_snapshot_merge import merge_learner_goal_snapshot_into_ask
from app.api_models import AskResponse
from app.api_requests import AskRequest
from app.async_quality_judge import schedule_async_quality_judge_if_sampled
from app.guardrails import InputGuardrailError, OutputGuardrailError, redact_sensitive_text
from app.logging_config import get_request_id, log_event, setup_logging

router = APIRouter(tags=["query"])
logger = setup_logging()


def _save_faq_interaction_background(question: str, answer: str, sources: list[dict]) -> None:
    try:
        services.faq_memory.save_interaction(
            question=question,
            answer=answer,
            sources=sources,
        )
    except Exception as save_error:  # noqa: BLE001 - FAQ cache persistence is best-effort enrichment.
        logger.warning("Failed to save FAQ interaction: %s", save_error)


def _load_e2e_payload(name: str) -> dict:
    pkg = Path(__file__).resolve().parents[1] / "offline_payloads" / name
    if not pkg.exists():
        pkg = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "fixtures" / "offline_payloads" / name
    return json.loads(pkg.read_text(encoding="utf-8"))


@router.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    response: Response,
    http_request: Request,
    background_tasks: BackgroundTasks,
):
    request_id = getattr(http_request.state, "request_id", None) or get_request_id() or str(uuid.uuid4())
    try:
        validated_request = services.prepare_ask_request(
            merge_learner_goal_snapshot_into_ask(request)
        )
        validated_question = validated_request.question
        query_options = validated_request.options

        log_event(
            logger,
            logging.INFO,
            "ask_request_started",
            question=redact_sensitive_text(validated_question),
            folder=query_options.folder,
            folder_rel=query_options.folder_rel,
            file_name=query_options.file_name,
            relative_path=query_options.relative_path,
        )

        offline_mode = get_settings().home_rag_e2e_offline
        if offline_mode:
            source_payload = _load_e2e_payload("scenario_08.json")
            sources = source_payload.get("sources") or []
            result = {
                "answer": "E2E offline stub response.",
                "sources": sources,
                "confidence": {
                    "level": "high",
                    "label": "high",
                    "source_count": len(sources),
                    "avg_source_score": 0.81,
                    "unique_source_files": len({s.get("file_name") for s in sources if s.get("file_name")}),
                    "reasons": [],
                },
                "debug": {
                    "query_type": "qa",
                    "total_answer_ms": 10,
                    "pipeline_ms": 5,
                    "engine_acquire_ms": 0,
                    "query_execute_ms": 5,
                    "estimated_cost_usd": {"stages": {}, "total": 0.0},
                    "token_usage": {"stages": {}},
                    "quality_checks": {},
                    "pipeline_trace": {},
                    "retrieval_trace": {},
                },
            }

            session_id = str(getattr(query_options, "session_id", "") or "").strip() or None
            if session_id:
                messages = [
                    Message(role="user", content=validated_question),
                    Message(role="assistant", content=result["answer"]),
                ]
                session_store.save(session_id, messages)
        else:
            result = services.answer_question(validated_question, query_options)
        result.setdefault("debug", {})
        result["debug"]["request_id"] = request_id

        guardrails = result["debug"].get("guardrails") or {}
        fallback_applied = bool(guardrails.get("fallback_applied"))
        sources = result.get("sources") or []

        try:
            services.append_history_entry(
                request_id=request_id,
                question=validated_question,
                result=result,
            )
        except Exception as history_error:  # noqa: BLE001 - history persistence is best-effort; /ask must still return the answer.
            logger.warning("Failed to save history entry: %s", history_error)

        cost_dbg = result["debug"].get("estimated_cost_usd") or {}
        services.record_request(
            request_id=request_id,
            question=validated_question,
            query_type=result["debug"].get("query_type"),
            total_answer_ms=result["debug"].get("total_answer_ms"),
            pipeline_ms=result["debug"].get("pipeline_ms"),
            engine_acquire_ms=result["debug"].get("engine_acquire_ms"),
            query_execute_ms=result["debug"].get("query_execute_ms"),
            source_count=len(sources),
            fallback_applied=fallback_applied,
            estimated_cost_usd=cost_dbg.get("total"),
            estimated_cost_stages_usd=cost_dbg.get("stages"),
            answer_empty=not bool((result.get("answer") or "").strip()),
            quality_checks=result["debug"].get("quality_checks"),
            pipeline_trace=result["debug"].get("pipeline_trace"),
            token_usage=result["debug"].get("token_usage"),
            retrieval_trace=result["debug"].get("retrieval_trace"),
        )

        if (not offline_mode) and not (query_options.session_id or "").strip():
            background_tasks.add_task(
                _save_faq_interaction_background,
                validated_question,
                result.get("answer", ""),
                result.get("sources") or [],
            )

        schedule_async_quality_judge_if_sampled(
            background_tasks=background_tasks,
            request_id=request_id,
            question=validated_question,
            answer=result.get("answer", "") or "",
            sources=result.get("sources") or [],
            query_type=result["debug"].get("query_type"),
        )

        response.headers["X-Request-ID"] = request_id
        return result

    except HTTPException as e:
        record_api_error(endpoint="/ask", exc=e, request=http_request, status_code=e.status_code)
        raise
    except InputGuardrailError as e:
        record_api_error(endpoint="/ask", exc=e, request=http_request, status_code=400)
        raise HTTPException(status_code=400, detail=services.build_error_detail(e.code, str(e)))
    except OutputGuardrailError as e:
        record_api_error(endpoint="/ask", exc=e, request=http_request, status_code=422)
        raise HTTPException(status_code=422, detail=services.build_error_detail(e.code, str(e)))
    except services.ReindexInProgressError as e:
        record_api_error(endpoint="/ask", exc=e, request=http_request, status_code=503)
        raise HTTPException(
            status_code=503,
            detail=str(e),
            headers={"Retry-After": "5"},
        )
    except services.EmptyIndexError as e:
        record_api_error(endpoint="/ask", exc=e, request=http_request, status_code=503)
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        record_api_error(endpoint="/ask", exc=e, request=http_request, status_code=500)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:  # noqa: BLE001 - final API boundary maps unexpected RAG failures to HTTP 500.
        record_api_error(endpoint="/ask", exc=e, request=http_request, status_code=500)
        log_event(
            logger,
            logging.ERROR,
            "ask_request_failed",
            error_type=type(e).__name__,
            error=str(e),
        )
        raise HTTPException(
            status_code=500,
            detail=f"RAG query failed: {type(e).__name__}: {e}",
        )
