"""Learner / progress / graph / konspekt inspection tools (all read-only).

These wrap existing read-only service helpers. No user_state writes.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agent.contracts import ToolArgModel, ToolContext, ToolResult, ToolSpec

logger = logging.getLogger(__name__)

_MAX_PROFILE_CHARS = 3000
_MAX_MASTERY_CONCEPTS = 30
_MAX_GRAPH_CONCEPTS = 20
_MAX_KONSPEKT_ROWS = 20


class LearnerGetProfileArgs(ToolArgModel):
    pass


class ProgressGetMasteryArgs(ToolArgModel):
    topic: str | None = None


class GraphInspectArgs(ToolArgModel):
    concept: str | None = None


class KonspektInspectArgs(ToolArgModel):
    pass


def _truncate(text: str, limit: int) -> str:
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _learner_get_profile_handler(ctx: ToolContext, args: ToolArgModel) -> ToolResult:
    assert isinstance(args, LearnerGetProfileArgs)
    try:
        from app.learner_model_service import get_personalized_learner_profile

        model = get_personalized_learner_profile(user_id=ctx.user_id)
        data = model.model_dump(mode="json") if hasattr(model, "model_dump") else dict(model)
        return ToolResult.success(data=_truncate_dict(data, _MAX_PROFILE_CHARS))
    except Exception as exc:  # noqa: BLE001
        logger.debug("agent.learner_get_profile_failed: %s", exc)
        return ToolResult.failure(f"learner.get_profile failed: {exc}")


def _truncate_dict(data: Any, char_budget: int) -> dict[str, Any]:
    """Drop verbose list/dict leaves to stay within a char budget."""
    import json

    blob = json.dumps(data, ensure_ascii=False, default=str)
    if len(blob) <= char_budget:
        return data if isinstance(data, dict) else {"value": data}
    compact = {k: v for k, v in (data.items() if isinstance(data, dict) else [])}
    overflow = blob
    for key in list(compact.keys()):
        val = compact[key]
        if isinstance(val, (list, dict)) and len(str(val)) > 400:
            compact[key] = _truncate(str(val), 400)
        overflow = json.dumps(compact, ensure_ascii=False, default=str)
        if len(overflow) <= char_budget:
            break
    return compact


def _progress_get_mastery_handler(ctx: ToolContext, args: ToolArgModel) -> ToolResult:
    assert isinstance(args, ProgressGetMasteryArgs)
    try:
        from app.quiz_adaptive import (
            get_all_mastery_levels,
            get_weak_concepts,
            list_quiz_mastery_state,
        )

        levels = get_all_mastery_levels()
        weak = get_weak_concepts(limit=_MAX_MASTERY_CONCEPTS)
        rows = list_quiz_mastery_state()
        if args.topic:
            topic = args.topic.strip()
            levels = {k: v for k, v in levels.items() if topic.lower() in k.lower()}
        data = {
            "mastery_levels": dict(list(levels.items())[:_MAX_MASTERY_CONCEPTS]),
            "weak_concepts": weak[:_MAX_MASTERY_CONCEPTS],
            "row_count": len(rows),
        }
        return ToolResult.success(data=data, concept_count=len(levels))
    except Exception as exc:  # noqa: BLE001
        logger.debug("agent.progress_get_mastery_failed: %s", exc)
        return ToolResult.failure(f"progress.get_mastery failed: {exc}")


def _graph_inspect_handler(ctx: ToolContext, args: ToolArgModel) -> ToolResult:
    assert isinstance(args, GraphInspectArgs)
    try:
        from app.knowledge_graph import get_active_knowledge_graph

        kg = get_active_knowledge_graph()
        concepts = kg.get_concepts()
        if args.concept:
            concept = args.concept.strip()
            node = kg.get_concept(concept) or {}
            prereqs = kg.get_prerequisites(concept)
            data = {
                "concept": concept,
                "node": node,
                "prerequisites": prereqs,
                "found": bool(node),
            }
            return ToolResult.success(data=data)
        concept_items = list(concepts.items())[:_MAX_GRAPH_CONCEPTS]
        data = {
            "total_concepts": len(concepts),
            "sample_concepts": [
                {"id": cid, "prerequisites": kg.get_prerequisites(cid)[:5]}
                for cid, _ in concept_items
            ],
        }
        return ToolResult.success(data=data, concept_count=len(concepts))
    except Exception as exc:  # noqa: BLE001
        logger.debug("agent.graph_inspect_failed: %s", exc)
        return ToolResult.failure(f"graph.inspect failed: {exc}")


def _konspekt_inspect_handler(ctx: ToolContext, args: ToolArgModel) -> ToolResult:
    assert isinstance(args, KonspektInspectArgs)
    try:
        from app.workbench_service import (
            UserStateWorkbenchStorage,
            normalize_runtime_rows,
            runtime_rows_from_persisted,
        )

        # Strict read-only: use load_json() directly (load_rows can write back).
        raw_rows = UserStateWorkbenchStorage().load_json()
        rows = normalize_runtime_rows(runtime_rows_from_persisted(raw_rows))
        compact = []
        for row in rows[:_MAX_KONSPEKT_ROWS]:
            compact.append({
                "id": row.get("id"),
                "title": row.get("title") or row.get("section") or "",
                "status": row.get("status"),
                "source_count": len(row.get("sources") or []),
            })
        return ToolResult.success(
            data={"total_rows": len(rows), "rows": compact},
            row_count=len(rows),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("agent.konspekt_inspect_failed: %s", exc)
        return ToolResult.failure(f"konspekt.inspect failed: {exc}")


LEARNER_GET_PROFILE_SPEC = ToolSpec(
    name="learner.get_profile",
    description="Return the personalized learner model: mastery level, learning goal, preferred style, cognitive load, emotional state, and mastery vector.",
    when_to_use="Use at the start of a study session or when personalization affects the answer depth, style, or next step.",
    args_schema=LearnerGetProfileArgs,
    limits={"max_result_chars": _MAX_PROFILE_CHARS},
)

PROGRESS_GET_MASTERY_SPEC = ToolSpec(
    name="progress.get_mastery",
    description="Return quiz mastery levels across concepts, weak concepts, and mastery row count. Optionally filter by topic.",
    when_to_use="Use to identify gaps, weak spots, or what the learner has already mastered before explaining or generating a quiz.",
    args_schema=ProgressGetMasteryArgs,
    limits={"max_result_chars": _MAX_PROFILE_CHARS},
)

GRAPH_INSPECT_SPEC = ToolSpec(
    name="graph.inspect",
    description="Inspect the active knowledge graph: list concepts and prerequisites, or get a single concept node with its prerequisite chain.",
    when_to_use="Use to understand concept relationships, find prerequisites, or navigate the learning graph structure.",
    args_schema=GraphInspectArgs,
    limits={"max_result_chars": _MAX_PROFILE_CHARS},
)

KONSPEKT_INSPECT_SPEC = ToolSpec(
    name="konspekt.inspect",
    description="Inspect the Living Konspekt workbench: list selected rows, their titles, statuses, and source counts without modifying the basket.",
    when_to_use="Use to understand what the learner has collected in their konspekt and what sections are selected.",
    args_schema=KonspektInspectArgs,
    limits={"max_result_chars": _MAX_PROFILE_CHARS},
)


def get_learner_tool_specs() -> list[tuple[ToolSpec, Any]]:
    """Return (spec, handler) pairs for learner/progress/graph/konspekt tools."""
    return [
        (LEARNER_GET_PROFILE_SPEC, _learner_get_profile_handler),
        (PROGRESS_GET_MASTERY_SPEC, _progress_get_mastery_handler),
        (GRAPH_INSPECT_SPEC, _graph_inspect_handler),
        (KONSPEKT_INSPECT_SPEC, _konspekt_inspect_handler),
    ]


__all__ = [
    "GRAPH_INSPECT_SPEC",
    "KONSPEKT_INSPECT_SPEC",
    "LEARNER_GET_PROFILE_SPEC",
    "PROGRESS_GET_MASTERY_SPEC",
    "GraphInspectArgs",
    "KonspektInspectArgs",
    "LearnerGetProfileArgs",
    "ProgressGetMasteryArgs",
    "get_learner_tool_specs",
]
