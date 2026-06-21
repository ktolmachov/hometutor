"""HTTP API: scoped quizzes и оценка micro-quiz (Unified Auto-Loop)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api_helpers import record_api_error
from app.config import get_settings
from app.guardrails import InputGuardrailError
from app.input_validation import build_error_detail, validate_llm_input_text
from app.knowledge_service import get_topics_catalog
from app.path_safety import validate_data_relative_path
from app.quiz_service import (
    InvalidMicroQuizQuestionError,
    generate_scoped_quiz,
    process_micro_quiz_outcome,
)

router = APIRouter(tags=["quiz"])


def _load_e2e_payload(name: str) -> dict[str, Any]:
    pkg = Path(__file__).resolve().parents[1] / "offline_payloads" / name
    if not pkg.exists():
        pkg = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "fixtures" / "offline_payloads" / name
    return json.loads(pkg.read_text(encoding="utf-8"))


class QuizGenerateRequest(BaseModel):
    scope: str = Field(..., description="document | topic")
    identifier: str | None = Field(default=None)
    relative_path: str | None = Field(default=None)
    topic_id: str | None = Field(default=None)
    topic_name: str | None = Field(default=None)
    num_questions: int = Field(default=6, ge=5, le=8)
    difficulty: str = Field(default="adaptive")
    learning_mode: str | None = Field(
        default=None,
        description="Шаблон промпта: default | understand_topic | exam_prep | solve_homework (пусто — из QUIZ_LEARNING_MODE_DEFAULT)",
    )
    documents: list[str] | None = Field(
        default=None,
        description="Restrict quiz to these relative paths (scope=topic only)",
    )


class QuizEvaluateRequest(BaseModel):
    quiz_question: dict[str, Any]
    user_answer_letter: str = Field(..., min_length=1, max_length=1)
    current_topic: str = "general"
    current_mastery: str = "intermediate"
    session_id: str | None = None


def _resolve_quiz_identifier(body: QuizGenerateRequest) -> str:
    scope = (body.scope or "").strip().lower()
    if scope == "document":
        return (body.relative_path or body.identifier or "").strip()
    if scope == "topic":
        topic_id = (body.topic_id or "").strip()
        if topic_id:
            return topic_id
        topic_name = (body.topic_name or "").strip()
        if topic_name:
            normalized = topic_name.lower()
            try:
                catalog = get_topics_catalog()
            except Exception as _exc:  # noqa: BLE001
                import logging; logging.getLogger(__name__).debug("! caught exception: %s", _exc)  # noqa: BLE001 - topic catalog lookup is best-effort; unresolved names fall back to raw topic text.
                catalog = {}
            for topic in catalog.get("topics") or []:
                if str(topic.get("topic_name") or "").strip().lower() == normalized:
                    resolved = str(topic.get("topic_id") or "").strip()
                    if resolved:
                        return resolved
            return topic_name
        return (body.identifier or "").strip()
    return (body.identifier or "").strip()


def _generate_quiz_response(body: QuizGenerateRequest, *, endpoint: str) -> dict[str, Any]:
    scope = (body.scope or "").strip().lower()
    if scope not in ("document", "topic"):
        raise HTTPException(status_code=400, detail="scope must be 'document' or 'topic'")
    ident = _resolve_quiz_identifier(body)
    if not ident:
        detail = "relative_path or identifier is required for document scope"
        if scope == "topic":
            detail = "topic_id, topic_name or identifier is required for topic scope"
        raise HTTPException(status_code=400, detail=detail)
    try:
        ident = validate_llm_input_text(
            ident,
            field_name="identifier",
            required=True,
            max_chars=512,
        ) or ""
        if scope == "document":
            ident = validate_data_relative_path(ident)
    except InputGuardrailError as exc:
        raise HTTPException(status_code=400, detail=build_error_detail(exc.code, str(exc)))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if get_settings().home_rag_e2e_offline:
        payload = _load_e2e_payload("scenario_04.json")
        payload["scope"] = scope
        payload["identifier"] = ident
        return {"quiz": payload, "success": True}
    source_paths: list[str] | None = None
    if scope == "topic" and body.documents:
        try:
            source_paths = [validate_data_relative_path(p) for p in body.documents if p]
        except (InputGuardrailError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    try:
        out = generate_scoped_quiz(
            "document" if scope == "document" else "topic",
            ident,
            num_questions=body.num_questions,
            difficulty=(body.difficulty or "adaptive").strip(),
            learning_mode=(body.learning_mode or "").strip() or None,
            source_paths=source_paths,
        )
    except Exception as e:  # noqa: BLE001 - quiz API boundary records generation failures as controlled HTTP 500.
        record_api_error(endpoint=endpoint, exc=e, status_code=500)
        raise HTTPException(status_code=500, detail="Quiz generation failed")
    if not out.get("success"):
        raise HTTPException(status_code=400, detail=out.get("error") or "Quiz generation failed")
    resp: dict[str, Any] = {"quiz": out, "success": True}
    lb = out.get("latency_budget")
    if isinstance(lb, dict):
        resp["latency_budget"] = lb
    return resp


@router.post("/quiz/generate")
def generate_quiz(body: QuizGenerateRequest):
    return _generate_quiz_response(body, endpoint="/quiz/generate")


@router.post("/quiz/generate/scoped", include_in_schema=False)
def generate_quiz_scoped_compat(body: QuizGenerateRequest):
    return _generate_quiz_response(body, endpoint="/quiz/generate/scoped")


@router.post("/quiz/evaluate")
def evaluate_quiz(body: QuizEvaluateRequest):
    letter = (body.user_answer_letter or "A").strip().upper()[:1]
    if letter not in ("A", "B", "C", "D"):
        raise HTTPException(status_code=400, detail="user_answer_letter must be A–D")
    try:
        out = process_micro_quiz_outcome(
            body.quiz_question,
            letter,
            current_topic=(body.current_topic or "general").strip() or "general",
            current_mastery=(body.current_mastery or "intermediate").strip() or "intermediate",
            session_id=body.session_id,
        )
    except InvalidMicroQuizQuestionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 - quiz API boundary records evaluation failures as controlled HTTP 500.
        record_api_error(endpoint="/quiz/evaluate", exc=e, status_code=500)
        raise HTTPException(status_code=500, detail="Quiz evaluation failed")
    return out


__all__ = ["router"]
