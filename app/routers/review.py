"""Spaced repetition: просроченные повторения (SM-2, user_state.db)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.knowledge_service import get_active_graph_for_review
from app.learner_state_scope import filter_due_reviews_for_kg

router = APIRouter(tags=["review"])


def get_active_knowledge_graph():
    """Back-compat alias for tests and monkeypatch targets."""
    return get_active_graph_for_review()


@router.get("/review/due")
def review_due(limit: int = Query(200, ge=1, le=500)):
    """Список концептов с ``next_review`` не позже текущего момента (UTC)."""
    due = filter_due_reviews_for_kg(get_active_knowledge_graph(), limit=limit)
    return {"due_reviews": due, "count": len(due)}


__all__ = ["router"]
