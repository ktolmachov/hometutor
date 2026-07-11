"""Learning plan generation grounded in catalog + chunk context.

B1: when graph with concepts is available, build a deterministic outline
from graph edges so the LLM only fills in descriptions, practice, and check
columns — not order or dependencies.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from app.knowledge_catalog import compute_source_coverage
from app.knowledge_graph import knowledge_graph
from app.knowledge_synthesis import _fetch_chunks_for_documents, _select_documents_for_synthesis
from app.knowledge_text import normalize_topic_name
from app.learning_plan_service import plan_service
from app.learning_plan_state import check_budget, parse_plan_table
from app.llm_resilience import complete_with_resilience
from app.prompts import LEARNING_PLAN_PROMPT
from app.retrieval_cache import get_base_services

logger = logging.getLogger(__name__)


def _graph_prerequisite_snippet(doc_concepts: list[str]) -> str:
    """Build a concise list of known prerequisite relationships.

    Scans the knowledge graph for edges among *doc_concepts* and returns
    a short block that the LLM can use as factual ground truth for the
    ``Зависимости`` column.
    """
    kg = knowledge_graph
    concepts = kg.get_concepts()
    doc_set = {c.strip().lower() for c in doc_concepts if c.strip()}
    if not doc_set:
        return ""

    edges: list[str] = []
    for cid in doc_set:
        node = concepts.get(cid, concepts.get(cid.capitalize()))
        if not isinstance(node, dict):
            continue
        prereqs = list(node.get("prerequisites", [])) or list(node.get("prerequisite_for", []))
        for p in prereqs:
            ps = str(p).strip()
            if ps and ps.lower() in doc_set:
                edges.append(f"- «{p}» → «{cid}»")

    if not edges:
        return ""
    return (
        "Известные связи по карте знаний (prerequisite → topic):\n"
        + "\n".join(sorted(set(edges)))
    )


def _reorder_validator(steps: list[dict[str, Any]], dp_plan: list[dict[str, Any]]) -> tuple[bool, str]:
    """Check if the generated table order contradicts graph topology.

    Returns ``(ok, warning_msg)`` where *ok* is ``True`` if order matches
    the graph, and *warning_msg* is a human-readable contradiction detail
    (or empty when no violation).
    """
    if not dp_plan:
        return True, ""
    dp_topics = [s.get("topic") or "" for s in dp_plan]
    step_titles = [s.title.lower() for s in steps]
    for i, step_a in enumerate(step_titles):
        for j, step_b in enumerate(step_titles):
            if i >= j:
                continue
            a_dp_idx = next((k for k, t in enumerate(dp_topics) if t and t.lower() == step_a), None)
            b_dp_idx = next((k for k, t in enumerate(dp_topics) if t and t.lower() == step_b), None)
            if a_dp_idx is not None and b_dp_idx is not None and a_dp_idx > b_dp_idx:
                msg = (
                    f"Порядок шагов в сгенерированной таблице нарушает карту знаний: "
                    f"«{steps[j].title}» идёт раньше «{steps[i].title}», "
                    f"хотя граф указывает обратный порядок."
                )
                logger.warning("learning_plan_order_contradiction: %s", msg)
                return False, msg
    return True, ""


def _dynamic_plan_prompt_block(dp: dict[str, Any] | None) -> str:
    if not dp or not dp.get("enabled"):
        return ""
    plan_items = dp.get("plan") or []
    lines = [
        "=== ОБЯЗАТЕЛЬНЫЙ ПОРЯДОК ШАГОВ (из карты знаний) ===",
        "Карта знаний определила следующий порядок. НЕ МЕНЯЙ ЕГО.",
        "Для колонки «Зависимости» используй известные связи prerequisite → topic.",
        "",
    ]
    for i, step in enumerate(plan_items, 1):
        t = step.get("topic")
        typ = step.get("type")
        reason = step.get("reason", "")
        hours = step.get("estimated_hours")
        lines.append(f"{i}. {t} [{typ}] ~{hours}h — {reason}")
    lines.append("")
    lines.append(f"Доля концептов на уровне transfer: {dp.get('mastery_percentage')}%")
    lines.append(f"Просроченных повторений (SR): {dp.get('next_review_count')}")
    lines.append("================================")
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

    doc_concepts = [
        c.strip()
        for doc in selected_documents
        for c in (doc.get("key_concepts") or [])
        if c.strip()
    ]

    query_parts = [effective_goal, f"Topic: {resolved_topic}", f"Level: {effective_level}"]
    if time_budget_hours is not None:
        query_parts.append(f"Time budget: {time_budget_hours} hours")
    if known_topics:
        query_parts.append(f"Known topics: {', '.join(known_topics)}")

    prereq_snippet = _graph_prerequisite_snippet(doc_concepts)
    if prereq_snippet:
        query_parts.append(prereq_snippet)

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
    plan_text = response.text.strip()

    coverage = compute_source_coverage(
        source_paths=document_paths,
        topic_id=topic_id,
        services=services,
    )
    missing_topics = _compute_missing_topics(selected_documents, known_topics=known_topics)

    plan_order_warning = None
    if dynamic_plan and dynamic_plan.get("plan"):
        parsed = parse_plan_table(plan_text)
        if parsed:
            ok, msg = _reorder_validator(parsed, dynamic_plan["plan"])
            if not ok:
                plan_order_warning = msg

    if time_budget_hours is not None and time_budget_hours > 0:
        budget = check_budget(plan_text, time_budget_hours)
        if budget and budget.over_budget:
            logger.warning(
                "learning_plan_over_budget: total=%.1fh budget=%.1fh exceeds_by=%.1fh steps=%d",
                budget.total_hours,
                budget.budget_hours,
                budget.exceeds_by_hours,
                budget.steps_count,
            )

    result: dict[str, Any] = {
        "topic": resolved_topic,
        "goal": effective_goal,
        "level": effective_level,
        "time_budget_hours": time_budget_hours,
        "plan": plan_text,
        "documents": selected_documents,
        "sources": sources,
        "coverage": coverage,
        "missing_topics": missing_topics,
    }
    if plan_order_warning:
        result["plan_order_warning"] = plan_order_warning
    if dynamic_plan is not None:
        result["dynamic_plan"] = dynamic_plan
    return result
