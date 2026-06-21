from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ContextObject(BaseModel):
    """Контракт handoff «ответ → tutor»."""

    model_config = ConfigDict(extra="ignore")

    question: str
    topic: str
    sources: list[dict[str, str]] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=100.0)
    learner_state: dict[str, Any] = Field(default_factory=dict)


def serialize_context(obj: ContextObject) -> str:
    data = obj.model_dump(mode="json")
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def deserialize_context(raw: str) -> ContextObject:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("context payload must be a non-empty string")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"context payload is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("context JSON must decode to an object")
    return ContextObject.model_validate(data)


def validate_context(data: Mapping[str, Any]) -> tuple[ContextObject | None, list[str]]:
    """
    Проверяет полноту handoff-payload. Пустые строки для question/topic считаются отсутствующими.
    """
    missing: list[str] = []
    q = data.get("question")
    if q is None or (isinstance(q, str) and not q.strip()):
        missing.append("question")
    t = data.get("topic")
    if t is None or (isinstance(t, str) and not t.strip()):
        missing.append("topic")
    if missing:
        return None, missing
    try:
        return ContextObject.model_validate(dict(data)), []
    except ValidationError as e:
        extra = [f"{err.get('loc')}: {err.get('msg')}" for err in e.errors()]
        return None, missing + extra
