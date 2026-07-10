"""Flashcard tools: ``cards.get_due`` (read) and ``cards.propose`` (read/draft).

``cards.propose`` returns **draft** candidates without saving — write tools
(``cards.save_deck``, ``sr.update_card``) are deferred to Wave 5 (HITL).
"""
from __future__ import annotations

import logging
from typing import Any

from app.agent.contracts import ToolArgModel, ToolContext, ToolResult, ToolSpec

logger = logging.getLogger(__name__)

_MAX_DUE_CARDS = 10
_MAX_PROPOSE_HINTS = 8


class CardsGetDueArgs(ToolArgModel):
    limit: int = 5
    deck_id: int | None = None
    tags: str | None = None


class CardsProposeArgs(ToolArgModel):
    topic: str | None = None
    context: str | None = None


def _cards_get_due_handler(ctx: ToolContext, args: ToolArgModel) -> ToolResult:
    """Return due flashcards for spaced-repetition review (read-only)."""
    assert isinstance(args, CardsGetDueArgs)
    try:
        from app.user_state_flashcards import get_due_flashcards

        limit = max(1, min(int(args.limit or 5), _MAX_DUE_CARDS))
        cards = get_due_flashcards(
            limit=limit,
            deck_id=args.deck_id,
            tags=args.tags,
        )
        compact = []
        for card in cards:
            compact.append({
                "id": card.get("id"),
                "front": card.get("front") or card.get("question"),
                "deck_name": card.get("deck_name"),
                "tags": card.get("tags"),
            })
        return ToolResult.success(
            data={"due_count": len(cards), "cards": compact},
            due_count=len(cards),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("agent.cards_get_due_failed: %s", exc)
        return ToolResult.failure(f"cards.get_due failed: {exc}")


def _cards_propose_handler(ctx: ToolContext, args: ToolArgModel) -> ToolResult:
    """Propose draft flashcard candidates without saving (read/draft, Wave 5 = save)."""
    assert isinstance(args, CardsProposeArgs)
    topic = (args.topic or "").strip()
    context = (args.context or "").strip()
    hints: list[dict[str, Any]] = []
    if topic:
        hints.append({"front": f"Определение: {topic}", "kind": "definition"})
    if context:
        words = [w.strip(".,;:!?()«»\"'") for w in context.split() if len(w.strip(".,;:!?()«»\"'")) > 4]
        for w in words[: _MAX_PROPOSE_HINTS - len(hints)]:
            hints.append({"front": f"Что такое {w}?", "kind": "concept"})
    data = {
        "note": "Draft candidates only — no cards are saved until Wave 5 (HITL approval).",
        "topic": topic or None,
        "candidates": hints[:_MAX_PROPOSE_HINTS],
    }
    return ToolResult.success(data=data, candidate_count=len(hints))


CARDS_GET_DUE_SPEC = ToolSpec(
    name="cards.get_due",
    description="Return flashcards due for spaced-repetition review right now, optionally filtered by deck or tags.",
    when_to_use="Use when the learner should review due cards, or to understand what material needs reinforcement.",
    args_schema=CardsGetDueArgs,
    limits={"max_result_chars": 200 * _MAX_DUE_CARDS},
)

CARDS_PROPOSE_SPEC = ToolSpec(
    name="cards.propose",
    description="Propose draft flashcard candidates from a topic or context. Candidates are NOT saved — they are returned for review only.",
    when_to_use="Use after explaining a topic to suggest cards the learner might create. No persistence happens.",
    args_schema=CardsProposeArgs,
    limits={"max_result_chars": 200 * _MAX_PROPOSE_HINTS},
)


def get_flashcards_tool_specs() -> list[tuple[ToolSpec, Any]]:
    return [
        (CARDS_GET_DUE_SPEC, _cards_get_due_handler),
        (CARDS_PROPOSE_SPEC, _cards_propose_handler),
    ]


__all__ = [
    "CARDS_GET_DUE_SPEC",
    "CARDS_PROPOSE_SPEC",
    "CardsGetDueArgs",
    "CardsProposeArgs",
    "get_flashcards_tool_specs",
]
