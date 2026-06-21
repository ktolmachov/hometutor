"""Thin facade over knowledge_* modules plus graph re-exports (stable import path)."""

from __future__ import annotations

from app.knowledge_catalog import (
    compute_source_coverage,
    get_topics_catalog,
    invalidate_catalog_cache,
)
from app.knowledge_graph import (
    JsonKnowledgeGraph,
    get_active_knowledge_graph,
    get_mastery_vector,
    get_personalized_subgraph,
    knowledge_graph,
)
from app.knowledge_insights import (
    get_kb_overview,
    get_proactive_suggestions,
    search_knowledge_base,
)
from app.knowledge_planning import build_learning_plan
from app.knowledge_synthesis import synthesize_topic


def get_active_graph_for_review() -> JsonKnowledgeGraph:
    """Router-safe wrapper for active knowledge graph access."""
    return get_active_knowledge_graph()


__all__ = [
    "JsonKnowledgeGraph",
    "build_learning_plan",
    "compute_source_coverage",
    "get_active_graph_for_review",
    "get_active_knowledge_graph",
    "get_kb_overview",
    "get_mastery_vector",
    "get_personalized_subgraph",
    "get_proactive_suggestions",
    "get_topics_catalog",
    "invalidate_catalog_cache",
    "knowledge_graph",
    "search_knowledge_base",
    "synthesize_topic",
]
