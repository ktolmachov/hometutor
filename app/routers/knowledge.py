from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

import app.api_services as services
from app.api_helpers import record_api_error
from app.source_readiness import build_source_readiness_summary
from app.config import DATA_DIR, get_settings
from app.api_models import (
    GraphPrerequisitesHealthResponse,
    LearningPlanGraphBundleResponse,
    LearningPlanResponse,
    NextBestActionsResponse,
)
from app.api_requests import LearningPlanRequest, SynthesizeRequest
from app.guardrails import InputGuardrailError
from app.input_validation import build_error_detail, validate_llm_input_list, validate_llm_input_text

router = APIRouter(tags=["knowledge"])


def _load_e2e_payload(name: str) -> dict:
    pkg = Path(__file__).resolve().parents[1] / "offline_payloads" / name
    if not pkg.exists():
        pkg = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "fixtures" / "offline_payloads" / name
    return json.loads(pkg.read_text(encoding="utf-8"))


@router.get("/topics", response_model=dict)
def topics():
    if get_settings().home_rag_e2e_offline:
        doc_rel = "e2e/offline_stub.md"
        documents = [
            {
                "doc_id": "e2e-offline-stub",
                "relative_path": doc_rel,
                "file_name": "offline_stub.md",
                "folder_name": "e2e",
                "summary": "Offline e2e stub document for topics / RAG demos.",
                "doc_type": "markdown",
                "difficulty": "easy",
                "key_concepts": ["retrieval"],
            }
        ]
        return {
            "topics": [
                {
                    "topic_id": "retrieval-augmented-generation",
                    "topic_name": "Retrieval Augmented Generation",
                    "document_count": len(documents),
                    "key_concepts": ["retrieval", "source-grounding", "confidence"],
                    "documents": documents,
                }
            ],
            "total_topics": 1,
            "total_documents": len(documents),
        }
    try:
        return services.get_topics_catalog()
    except (services.EmptyIndexError, services.EmbedModelMismatchError) as e:
        record_api_error(endpoint="/topics", exc=e, status_code=503)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001 - knowledge API boundary records service failures and returns controlled HTTP 500.
        record_api_error(endpoint="/topics", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Topics catalog failed: {type(e).__name__}: {e}",
        )


@router.post("/synthesize", response_model=dict)
def synthesize(request: SynthesizeRequest):
    try:
        topic = validate_llm_input_text(request.topic, field_name="topic", max_chars=512)
        topic_id = validate_llm_input_text(request.topic_id, field_name="topic_id", max_chars=512)
        documents = validate_llm_input_list(request.documents, field_name="documents", max_items=100, max_chars=512)
        return services.synthesize_topic(
            topic=topic,
            topic_id=topic_id,
            documents=documents,
        )
    except InputGuardrailError as e:
        raise HTTPException(status_code=400, detail=build_error_detail(e.code, str(e)))
    except ValueError as e:
        record_api_error(endpoint="/synthesize", exc=e, status_code=400)
        raise HTTPException(status_code=400, detail=str(e))
    except services.EmptyIndexError as e:
        record_api_error(endpoint="/synthesize", exc=e, status_code=503)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001 - knowledge API boundary records service failures and returns controlled HTTP 500.
        record_api_error(endpoint="/synthesize", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Synthesis failed: {type(e).__name__}: {e}",
        )


@router.post("/learning-plan", response_model=LearningPlanResponse)
def learning_plan(request: LearningPlanRequest):
    try:
        if get_settings().home_rag_e2e_offline:
            payload = _load_e2e_payload("scenario_09.json")
            return {
                "topic": request.topic or "Retrieval Augmented Generation",
                "goal": request.goal or payload.get("summary"),
                "level": request.level or "intermediate",
                "time_budget_hours": request.time_budget_hours,
                "plan": "\n".join(
                    f"- {block['title']}: {block['action']}"
                    for block in payload.get("blocks", [])
                ),
                "documents": [
                    {
                        "doc_id": "e2e-plan",
                        "relative_path": "e2e/offline_plan.md",
                        "file_name": "offline_plan.md",
                        "folder_name": "e2e",
                        "summary": payload.get("summary"),
                        "doc_type": "markdown",
                        "difficulty": "medium",
                        "key_concepts": ["source-grounding", "retrieval-filters"],
                    }
                ],
                "sources": [],
                "coverage": {
                    "covered": 2,
                    "total": 3,
                    "ratio": 0.67,
                    "missing": ["confidence-calibration"],
                    "label": "partial",
                },
                "missing_topics": ["confidence-calibration"],
                "dynamic_plan": payload,
            }
        topic = validate_llm_input_text(request.topic, field_name="topic", max_chars=512)
        topic_id = validate_llm_input_text(request.topic_id, field_name="topic_id", max_chars=512)
        documents = validate_llm_input_list(request.documents, field_name="documents", max_items=100, max_chars=512)
        goal = validate_llm_input_text(request.goal, field_name="goal", max_chars=2000)
        level = validate_llm_input_text(request.level, field_name="level", max_chars=128)
        known_topics = validate_llm_input_list(
            request.known_topics,
            field_name="known_topics",
            max_items=100,
            max_chars=512,
        )
        return services.build_learning_plan(
            topic=topic,
            topic_id=topic_id,
            documents=documents,
            goal=goal,
            level=level,
            time_budget_hours=request.time_budget_hours,
            known_topics=known_topics,
            user_progress=request.user_progress,
        )
    except InputGuardrailError as e:
        raise HTTPException(status_code=400, detail=build_error_detail(e.code, str(e)))
    except ValueError as e:
        record_api_error(endpoint="/learning-plan", exc=e, status_code=400)
        raise HTTPException(status_code=400, detail=str(e))
    except services.EmptyIndexError as e:
        record_api_error(endpoint="/learning-plan", exc=e, status_code=503)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001 - knowledge API boundary records service failures and returns controlled HTTP 500.
        record_api_error(endpoint="/learning-plan", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Learning plan failed: {type(e).__name__}: {e}",
        )


@router.get("/kb/graph/prerequisites-health", response_model=GraphPrerequisitesHealthResponse)
def graph_prerequisites_health():
    """Циклы prerequisites и успех топосортировки без LLM (baseline для graph + learning-plan)."""
    try:
        return services.get_graph_prerequisites_health()
    except Exception as e:  # noqa: BLE001 - knowledge API boundary records service failures and returns controlled HTTP 500.
        record_api_error(endpoint="/kb/graph/prerequisites-health", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Graph prerequisites health failed: {type(e).__name__}: {e}",
        )


@router.get("/kb/graph/next-best-actions", response_model=NextBestActionsResponse)
def graph_next_best_actions(
    limit: int = Query(default=8, ge=1, le=20),
    due_limit: int = Query(default=200, ge=1, le=500),
):
    """NBA: слабые места + prerequisites + due review; тот же сигнал, что personalized learning plan."""
    try:
        return services.get_next_best_actions_for_user(limit=limit, due_limit=due_limit)
    except Exception as e:  # noqa: BLE001 - knowledge API boundary records service failures and returns controlled HTTP 500.
        record_api_error(endpoint="/kb/graph/next-best-actions", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Next-best-actions failed: {type(e).__name__}: {e}",
        )


@router.get("/kb/learner/profile-history", response_model=dict)
def learner_profile_history(
    limit: int = Query(default=20, ge=1, le=200),
    user_id: str = Query(default="local"),
    session_id: str | None = Query(default=None),
):
    """
    E5 diagnostics: versioned learner profile snapshots + текущий state_migration.
    """
    try:
        current = services.get_personalized_learner_profile(user_id, session_id=session_id).model_dump(mode="json")
        history = services.get_learner_profile_history(limit=limit)
        return {
            "schema_version": 1,
            "user_id": (user_id or "").strip() or "local",
            "history_limit": limit,
            "history_count": len(history),
            "current_index_context": current.get("index_context") or {},
            "current_state_migration": current.get("state_migration") or {},
            "history": history,
        }
    except Exception as e:  # noqa: BLE001 - knowledge API boundary records service failures and returns controlled HTTP 500.
        record_api_error(endpoint="/kb/learner/profile-history", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Learner profile history failed: {type(e).__name__}: {e}",
        )


@router.get("/kb/learning-plan/graph-bundle", response_model=LearningPlanGraphBundleResponse)
def learning_plan_graph_bundle(
    nba_limit: int = Query(default=8, ge=1, le=20),
    due_limit: int = Query(default=200, ge=1, le=500),
    topo_preview_limit: int = Query(default=12, ge=0, le=50),
):
    """Health + NBA + топопорядок для согласования с POST /learning-plan без дополнительного LLM."""
    try:
        return services.get_learning_plan_graph_bundle(
            nba_limit=nba_limit,
            due_limit=due_limit,
            topo_preview_limit=topo_preview_limit,
        )
    except Exception as e:  # noqa: BLE001 - knowledge API boundary records service failures and returns controlled HTTP 500.
        record_api_error(endpoint="/kb/learning-plan/graph-bundle", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Learning plan graph bundle failed: {type(e).__name__}: {e}",
        )


@router.get("/kb/source-readiness", response_model=dict)
def kb_source_readiness():
    """US-2.5: стабильный контракт готовности источников без UI bootstrap."""
    try:
        return build_source_readiness_summary(DATA_DIR, get_settings())
    except Exception as e:  # noqa: BLE001 - knowledge API boundary records service failures and returns controlled HTTP 500.
        record_api_error(endpoint="/kb/source-readiness", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"Source readiness failed: {type(e).__name__}: {e}",
        )


@router.get("/kb/overview", response_model=dict)
def kb_overview():
    if get_settings().home_rag_e2e_offline:
        return {
            "documents": 3,
            "chunks": 12,
            "topics": 1,
            "top_sources": ["rag_overview.md", "confidence_notes.md"],
            "status": "e2e-offline",
        }
    try:
        return services.get_kb_overview()
    except (services.EmptyIndexError, services.EmbedModelMismatchError) as e:
        record_api_error(endpoint="/kb/overview", exc=e, status_code=503)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001 - knowledge API boundary records service failures and returns controlled HTTP 500.
        record_api_error(endpoint="/kb/overview", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"KB overview failed: {type(e).__name__}: {e}",
        )


@router.get("/kb/search", response_model=dict)
def kb_search(q: str):
    try:
        return services.search_knowledge_base(q)
    except services.EmptyIndexError as e:
        record_api_error(endpoint="/kb/search", exc=e, status_code=503)
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001 - knowledge API boundary records service failures and returns controlled HTTP 500.
        record_api_error(endpoint="/kb/search", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"KB search failed: {type(e).__name__}: {e}",
        )


@router.get("/kb/suggestions", response_model=dict)
def kb_suggestions(question: str, sources: str = ""):
    if get_settings().home_rag_e2e_offline:
        return {
            "suggestions": [
                "Open the source trust panel",
                "Start a five-minute tutor loop",
                "Create flashcards from the weakest concept",
            ]
        }
    try:
        source_list = [s.strip() for s in sources.split(",") if s.strip()] if sources else []
        return services.get_proactive_suggestions(source_list, question)
    except Exception as e:  # noqa: BLE001 - knowledge API boundary records service failures and returns controlled HTTP 500.
        record_api_error(endpoint="/kb/suggestions", exc=e, status_code=500)
        raise HTTPException(
            status_code=500,
            detail=f"KB suggestions failed: {type(e).__name__}: {e}",
        )
