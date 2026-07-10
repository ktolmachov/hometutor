"""Quiz tool: ``quiz.generate`` (read-only, no result recording)."""
from __future__ import annotations

import logging
from typing import Any

from app.agent.contracts import ToolArgModel, ToolContext, ToolResult, ToolSpec

logger = logging.getLogger(__name__)

_MAX_QUIZ_CHARS = 4000


class QuizGenerateArgs(ToolArgModel):
    topic: str
    learning_mode: str | None = None


def _quiz_generate_handler(ctx: ToolContext, args: ToolArgModel) -> ToolResult:
    """Generate a scoped topic quiz without recording results."""
    assert isinstance(args, QuizGenerateArgs)
    topic = (args.topic or "").strip()
    if not topic:
        return ToolResult.failure("topic is required")
    try:
        from app.quiz_service import generate_topic_quiz

        questions, error = generate_topic_quiz(
            topic,
            learning_mode=args.learning_mode,
        )
        if error:
            return ToolResult.failure(error, topic=topic)
        import json

        data = {"topic": topic, "questions": questions or []}
        blob = json.dumps(data, ensure_ascii=False, default=str)
        if len(blob) > _MAX_QUIZ_CHARS:
            data["questions"] = data["questions"][:3]
        return ToolResult.success(data=data, question_count=len(questions or []))
    except Exception as exc:  # noqa: BLE001
        logger.debug("agent.quiz_generate_failed: %s", exc)
        return ToolResult.failure(f"quiz.generate failed: {exc}")


QUIZ_GENERATE_SPEC = ToolSpec(
    name="quiz.generate",
    description="Generate a scoped quiz (multiple-choice questions) for a topic from the knowledge base, without recording results.",
    when_to_use="Use to create a practice quiz for a topic the learner is studying, or to check understanding after an explanation.",
    args_schema=QuizGenerateArgs,
    limits={"max_result_chars": _MAX_QUIZ_CHARS},
)


def get_quiz_tool_specs() -> list[tuple[ToolSpec, Any]]:
    return [(QUIZ_GENERATE_SPEC, _quiz_generate_handler)]


__all__ = [
    "QUIZ_GENERATE_SPEC",
    "QuizGenerateArgs",
    "get_quiz_tool_specs",
]
