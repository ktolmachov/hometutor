"""Learning plan generation grounded in catalog + chunk context."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.knowledge_catalog import compute_source_coverage
from app.knowledge_text import normalize_topic_name
from app.knowledge_synthesis import _fetch_chunks_for_documents, _select_documents_for_synthesis
from app.learning_plan_service import plan_service
from app.llm_resilience import complete_with_resilience
from app.prompts import LEARNING_PLAN_PROMPT
from app.retrieval_cache import get_base_services


def _dynamic_plan_prompt_block(dp: dict[str, Any] | None) -> str:
    if not dp or not dp.get("enabled"):
        return ""
    lines = [
        "Персонализированный порядок шагов (reading_status, quiz_mastery, spaced repetition):",
    ]
    for i, step in enumerate(dp.get("plan") or [], 1):
        t = step.get("topic")
        typ = step.get("type")
        reason = step.get("reason", "")
        hours = step.get("estimated_hours")
        lines.append(f"{i}. {t} [{typ}] ~{hours}h — {reason}")
    lines.append(f"Доля концептов на уровне transfer: {dp.get('mastery_percentage')}%")
    lines.append(f"Просроченных повторений (SR): {dp.get('next_review_count')}")
    return "\n".join(lines)


def _compute_missing_topics(selected_documents: list[dict[str, Any]], known_topics: list[str] | None = None) -> list[str]:
    known = {normalize_topic_name(item) or "" for item in (known_topics or [])}
    known = {item.lower() for item in known if item}

    concept_counter: dict[str, int] = defaultdict(int)
    for document in selected_documents:
        for concept in document.get("key_concepts") or []:
            normalized = normalize_topic_name(concept)
            if not normalized:
                continue
            if normalized.lower() in known:
                continue
            concept_counter[normalized] += 1

    return [
        concept
        for concept, _ in sorted(concept_counter.items(), key=lambda item: (-item[1], item[0].lower()))[:8]
    ]


def build_learning_plan(
    *,
    topic: str | None = None,
    topic_id: str | None = None,
    documents: list[str] | None = None,
    goal: str | None = None,
    level: str | None = None,
    time_budget_hours: float | None = None,
    known_topics: list[str] | None = None,
    user_progress: bool = False,
    services: dict[str, Any] | None = None,
) -> dict[str, Any]:
    services = services or get_base_services()
    resolved_topic, selected_documents = _select_documents_for_synthesis(
        topic=topic,
        topic_id=topic_id,
        documents=documents,
        services=services,
    )

    effective_goal = (goal or f"Изучить тему {resolved_topic}").strip()
    effective_level = (level or "intermediate").strip().lower()
    document_paths = [item["relative_path"] for item in selected_documents]

    sources, grouped_chunks = _fetch_chunks_for_documents(
        effective_goal,
        selected_documents,
        document_paths,
        services=services,
        max_chunks_per_doc=2,
        max_total_chunks=8,
    )
    if not grouped_chunks:
        raise ValueError("No chunks found for selected topic/documents")

    context_sections: list[str] = []
    for document in selected_documents:
        rel_path = document["relative_path"]
        chunks = grouped_chunks.get(rel_path) or []
        if not chunks:
            continue
        summary = document.get("summary") or ""
        concepts = ", ".join(document.get("key_concepts") or [])
        doc_meta = f"Document: {rel_path}\nSummary: {summary}\nConcepts: {concepts}\nDifficulty: {document.get('difficulty') or 'unknown'}"
        section_text = "\n".join(f"- {chunk}" for chunk in chunks)
        context_sections.append(f"{doc_meta}\nChunks:\n{section_text}")

    query_parts = [effective_goal, f"Topic: {resolved_topic}", f"Level: {effective_level}"]
    if time_budget_hours is not None:
        query_parts.append(f"Time budget: {time_budget_hours} hours")
    if known_topics:
        query_parts.append(f"Known topics: {', '.join(known_topics)}")

    dynamic_plan: dict[str, Any] | None = None
    if user_progress:
        dynamic_plan = plan_service.generate(
            {
                "goal": effective_goal,
                "level": effective_level,
                "time_budget_hours": float(time_budget_hours) if time_budget_hours is not None else 40.0,
                "user_progress": True,
            }
        )
        block = _dynamic_plan_prompt_block(dynamic_plan)
        if block:
            query_parts.append(block)

    llm = services["llm"]
    prompt = LEARNING_PLAN_PROMPT.format(
        context_str="\n\n".join(context_sections),
        query_str="\n".join(query_parts),
    )
    response = complete_with_resilience(llm, prompt, stage="learning_plan")

    coverage = compute_source_coverage(
        source_paths=document_paths,
        topic_id=topic_id,
        services=services,
    )
    missing_topics = _compute_missing_topics(selected_documents, known_topics=known_topics)

    result: dict[str, Any] = {
        "topic": resolved_topic,
        "goal": effective_goal,
        "level": effective_level,
        "time_budget_hours": time_budget_hours,
        "plan": response.text.strip(),
        "documents": selected_documents,
        "sources": sources,
        "coverage": coverage,
        "missing_topics": missing_topics,
    }
    if dynamic_plan is not None:
        result["dynamic_plan"] = dynamic_plan
    return result
