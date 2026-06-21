from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class AnswerParseError(ValueError):
    """Malformed или семантически неверный UX-ответ."""


class AnswerObject(BaseModel):
    """Typed контракт для отображения ответа в UI без stringly glue."""

    model_config = ConfigDict(extra="forbid")

    text: str
    sources: list[dict[str, str]] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=100.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


def format_answer(obj: AnswerObject) -> str:
    """Стабильная сериализация (ключи отсортированы на всех уровнях)."""
    data = obj.model_dump(mode="json")
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def parse_answer(raw: str | dict[str, Any]) -> AnswerObject:
    """Разбор JSON-строки или dict в AnswerObject."""
    if isinstance(raw, dict):
        try:
            return AnswerObject.model_validate(raw)
        except ValidationError as e:
            raise AnswerParseError(f"answer validation failed: {e}") from e

    if not isinstance(raw, str) or not raw.strip():
        raise AnswerParseError("answer payload must be a non-empty string or dict")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise AnswerParseError(f"answer payload is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise AnswerParseError("answer JSON must decode to an object")

    try:
        return AnswerObject.model_validate(data)
    except ValidationError as e:
        raise AnswerParseError(f"answer validation failed: {e}") from e
