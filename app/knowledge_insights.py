"""KB overview, proactive suggestions, and unified search — all catalog-driven."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.knowledge_catalog import get_topics_catalog
from app.logging_config import setup_logging
from app.retrieval_cache import get_base_services

logger = setup_logging()


def get_kb_overview(
    services: dict[str, Any] | None = None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Knowledge base overview for the dashboard hero block."""
    if catalog is None:
        catalog = get_topics_catalog(services=services)
    topics = catalog.get("topics", [])

    concept_counter: dict[str, int] = defaultdict(int)
    folder_counter: dict[str, int] = defaultdict(int)

    for topic in topics:
        for concept in topic.get("key_concepts", []):
            concept_counter[concept] += 1
        for doc in topic.get("documents", []):
            folder = doc.get("folder_name") or "root"
            folder_counter[folder] += 1

    top_concepts = [
        {"name": name, "count": count}
        for name, count in sorted(concept_counter.items(), key=lambda x: -x[1])[:12]
    ]
    folder_distribution = [
        {"folder": folder, "count": count}
        for folder, count in sorted(folder_counter.items(), key=lambda x: -x[1])[:10]
    ]
    topic_sizes = [
        {"topic_name": t["topic_name"], "document_count": t["document_count"]}
        for t in sorted(topics, key=lambda x: -x["document_count"])[:8]
    ]

    return {
        "total_topics": catalog.get("total_topics", 0),
        "total_documents": catalog.get("total_documents", 0),
        "top_concepts": top_concepts,
        "folder_distribution": folder_distribution,
        "topic_sizes": topic_sizes,
    }


def get_proactive_suggestions(
    source_paths: list[str],
    question: str | None = None,
    services: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """After an answer: suggest related topics and unexplored documents."""
    catalog = get_topics_catalog(services=services)
    source_set = set(source_paths)

    related_topics = []
    unexplored_docs = []

    for topic in catalog.get("topics", []):
        topic_docs = {
            doc.get("relative_path") or doc.get("file_name")
            for doc in topic.get("documents", [])
        }
        overlap = source_set & topic_docs
        if overlap:
            not_used = sorted(topic_docs - source_set)
            related_topics.append({
                "topic_id": topic["topic_id"],
                "topic_name": topic["topic_name"],
                "overlap_count": len(overlap),
                "total_docs": len(topic_docs),
                "unexplored_count": len(not_used),
            })
            unexplored_docs.extend(not_used[:3])

    related_topics.sort(key=lambda x: (-x["overlap_count"], -x["unexplored_count"]))
    seen = set()
    unique_unexplored = []
    for doc in unexplored_docs:
        if doc not in seen:
            seen.add(doc)
            unique_unexplored.append(doc)

    similar_questions: list[dict[str, Any]] = []
    if question:
        try:
            from app import faq_memory
            similar_questions = faq_memory.find_similar_questions(
                question=question, top_k=3, min_score=0.65,
            )
        except Exception as _exc:  # noqa: BLE001 - optional FAQ enrichment must not break response
            logger.warning(
                "faq_memory.find_similar_questions failed; returning empty similar_questions: %s",
                _exc,
            )

    return {
        "related_topics": related_topics[:5],
        "unexplored_documents": unique_unexplored[:8],
        "similar_questions": [
            {"question": sq.get("question"), "score": sq.get("score")}
            for sq in similar_questions
        ],
    }


def search_knowledge_base(
    query: str,
    services: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Unified search across topics, documents and concepts."""
    query_lower = query.strip().lower()
    if not query_lower:
        return {"topics": [], "documents": [], "concepts": []}

    catalog = get_topics_catalog(services=services)
    matched_topics = []
    matched_documents = []
    matched_concepts: dict[str, list[str]] = defaultdict(list)

    for topic in catalog.get("topics", []):
        topic_name = topic.get("topic_name", "")
        if query_lower in topic_name.lower():
            matched_topics.append({
                "topic_id": topic["topic_id"],
                "topic_name": topic_name,
                "document_count": topic["document_count"],
            })

        for concept in topic.get("key_concepts", []):
            if query_lower in concept.lower():
                matched_concepts[concept].append(topic_name)

        for doc in topic.get("documents", []):
            haystack = " ".join([
                doc.get("relative_path") or "",
                doc.get("file_name") or "",
                doc.get("summary") or "",
                " ".join(doc.get("key_concepts") or []),
            ]).lower()
            if query_lower in haystack:
                matched_documents.append({
                    "relative_path": doc.get("relative_path"),
                    "file_name": doc.get("file_name"),
                    "topic_name": topic_name,
                    "summary": (doc.get("summary") or "")[:200],
                })

    seen_docs: set[str] = set()
    unique_docs = []
    for doc in matched_documents:
        key = doc.get("relative_path") or doc.get("file_name") or ""
        if key not in seen_docs:
            seen_docs.add(key)
            unique_docs.append(doc)

    concepts_list = [
        {"name": name, "topics": topics[:3]}
        for name, topics in sorted(matched_concepts.items(), key=lambda x: -len(x[1]))[:10]
    ]

    return {
        "topics": matched_topics[:10],
        "documents": unique_docs[:15],
        "concepts": concepts_list,
        "query": query,
    }
