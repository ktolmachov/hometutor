"""Decision layer for the agent loop (Wave 1: JSON-decision backend).

Follows the proven pattern from
``app.tutor_orchestrator.invoke_pedagogical_orchestrator_llm``:
``response_format=json_object``, ``temperature=0``, robust JSON extraction,
normalization, and rule-fallback on failure.

Native tools backend (``mode=native|auto``) is NOT implemented in Wave 1 —
it raises :class:`NotImplementedError` as an explicit future path.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from llama_index.core.base.llms.types import MessageRole
from llama_index.core.llms import ChatMessage

from app.prompts._impl import AGENT_SYSTEM_PROMPT, build_agent_decision_messages

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset({"tool_call", "final_answer"})
_RULE_FALLBACK_ANSWER = (
    "Не удалось сформировать агентный ответ из-за сбоя принятия решения. "
    "Попробуйте переформулировать вопрос."
)


@dataclass(frozen=True)
class DecisionResult:
    """Normalized outcome of one decision call.

    ``action`` is either ``"tool_call"`` or ``"final_answer"``.
    ``fallback=True`` means the LLM/JSON failed and a safe default was used.
    """

    action: str
    thought: str = ""
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    final_answer: str | None = None
    raw: Any = None
    fallback: bool = False


def normalize_decision(raw: dict[str, Any] | None) -> DecisionResult:
    """Bring a parsed LLM JSON dict to canonical form (soft validation).

    Unknown actions / missing tool names degrade to a safe final-answer
    fallback so the loop never proceeds with an undefined action.
    """
    data = raw if isinstance(raw, dict) else {}
    action = str(data.get("action") or "").strip().lower()
    thought = str(data.get("thought") or "").strip()

    if action not in _VALID_ACTIONS:
        return DecisionResult(
            action="final_answer",
            thought=thought or "invalid action",
            final_answer=_RULE_FALLBACK_ANSWER,
            raw=raw,
            fallback=True,
        )

    if action == "final_answer":
        answer = str(data.get("answer") or "").strip()
        if not answer:
            answer = _RULE_FALLBACK_ANSWER
            return DecisionResult(
                action="final_answer",
                thought=thought,
                final_answer=answer,
                raw=raw,
                fallback=True,
            )
        return DecisionResult(
            action="final_answer",
            thought=thought,
            final_answer=answer,
            raw=raw,
        )

    # action == "tool_call"
    tool_name = str(data.get("tool") or "").strip()
    raw_args = data.get("args")
    args = raw_args if isinstance(raw_args, dict) else {}
    return DecisionResult(
        action="tool_call",
        thought=thought,
        tool_name=tool_name or None,
        tool_args=args,
        raw=raw,
    )


def _make_fallback_decision(reason: str) -> DecisionResult:
    return DecisionResult(
        action="final_answer",
        thought=f"fallback: {reason}",
        final_answer=_RULE_FALLBACK_ANSWER,
        fallback=True,
    )


def decide_action(
    llm: Any,
    messages: list[Any],
    *,
    stage: str = "agent.decide",
) -> tuple[DecisionResult, dict[str, int] | None]:
    """One LLM chat completion in JSON-decision mode.

    Returns ``(decision, token_usage)``. On any failure (LLM exception, JSON
    parse error), a safe fallback decision is returned with ``fallback=True``.
    """
    from app.llm_resilience import chat_with_resilience
    from app.quiz_parse import _extract_first_json_object
    from app.usage_cost import extract_token_usage

    try:
        response = chat_with_resilience(
            llm,
            messages,
            stage=stage,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        usage = extract_token_usage(response)
        text = (response.message.content or "").strip()
        parsed = _extract_first_json_object(text)
        if not parsed:
            logger.warning("agent_decision_json_parse_failed | preview=%s", text[:200])
            return _make_fallback_decision("json_parse"), usage
        decision = normalize_decision(parsed)
        return decision, usage
    except Exception as exc:  # noqa: BLE001 - decision layer must not crash the loop
        logger.debug("agent.decide_action_failed: %s", exc)
        return _make_fallback_decision("exception"), None


def decide_native(
    llm: Any,
    messages: list[Any],
    *,
    openai_tools: list[dict[str, Any]],
    stage: str = "agent.decide_native",
) -> tuple[DecisionResult, dict[str, int] | None]:
    """Native tools backend — NOT implemented in Wave 1 (future path).

    Raises :class:`NotImplementedError` so callers handle it explicitly rather
    than silently falling back. Wave 3 implements this behind
    ``agent_tool_call_mode=native|auto``.
    """
    raise NotImplementedError(
        "Native tools backend is not implemented in Wave 1. "
        "Use agent_tool_call_mode=json (default). Native/auto support is Wave 3."
    )


def build_messages(
    *,
    question: str,
    tools_description: str,
    history: str,
    system_prompt: str | None = None,
) -> list[ChatMessage]:
    """Build [system, user] messages for the JSON-decision call.

    ``system_prompt`` overrides ``AGENT_SYSTEM_PROMPT`` for scenario-specific
    prompts (Wave 1A: study session). ``None`` preserves Wave 1 behavior.
    """
    return build_agent_decision_messages(
        question=question,
        tools_description=tools_description,
        history=history,
        system_prompt=system_prompt,
    )


def build_repair_messages(
    *,
    question: str,
    tools_description: str,
    history: str,
    tool_name: str,
    error: str,
    system_prompt: str | None = None,
) -> list[ChatMessage]:
    """Build messages with a repair instruction appended for invalid args."""
    from app.prompts._impl import AGENT_REPAIR_MESSAGE

    base = build_messages(
        question=question,
        tools_description=tools_description,
        history=history,
        system_prompt=system_prompt,
    )
    base.append(
        ChatMessage(
            role=MessageRole.USER,
            content=AGENT_REPAIR_MESSAGE.format(tool_name=tool_name, error=error),
        )
    )
    return base


__all__ = [
    "DecisionResult",
    "build_messages",
    "build_repair_messages",
    "decide_action",
    "decide_native",
    "normalize_decision",
]
