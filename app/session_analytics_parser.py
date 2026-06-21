from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class GradesDistribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    again: int = Field(default=0, ge=0)
    hard: int = Field(default=0, ge=0)
    good: int = Field(default=0, ge=0)
    easy: int = Field(default=0, ge=0)

    def total_reviewed(self) -> int:
        return self.again + self.hard + self.good + self.easy

    def percentages(self) -> dict[str, float]:
        total = self.total_reviewed()
        if total == 0:
            return {"again": 0.0, "hard": 0.0, "good": 0.0, "easy": 0.0}
        return {
            "again": 100.0 * self.again / total,
            "hard": 100.0 * self.hard / total,
            "good": 100.0 * self.good / total,
            "easy": 100.0 * self.easy / total,
        }


class RetentionPrediction(BaseModel):
    """Один день 7-дневной шкалы (day_index 0..6)."""

    model_config = ConfigDict(extra="forbid")

    day_index: int = Field(ge=0, le=6)
    due_cards: int = Field(ge=0)


class SessionStatsObject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    deck_id: int | None = None
    grades_distribution: GradesDistribution
    start_time: datetime
    end_time: datetime
    retention_predictions: list[RetentionPrediction] = Field(default_factory=list)
    insufficient_data: bool = False

    @computed_field
    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.end_time - self.start_time).total_seconds())

    @computed_field
    @property
    def velocity(self) -> float:
        """Карточек в минуту; при нулевой длительности — 0."""
        n = self.grades_distribution.total_reviewed()
        if self.duration_seconds <= 0:
            return 0.0
        return n / (self.duration_seconds / 60.0)

    @model_validator(mode="after")
    def _sync_insufficient_and_predictions_order(self) -> SessionStatsObject:
        n = self.grades_distribution.total_reviewed()
        ordered = sorted(self.retention_predictions, key=lambda p: p.day_index)
        self.insufficient_data = n < 5
        self.retention_predictions = list(ordered)
        return self


def _dump_session_for_storage(obj: SessionStatsObject) -> dict[str, Any]:
    """Без computed-полей — симметричный JSON round-trip при загрузке."""
    return obj.model_dump(mode="json", exclude={"duration_seconds", "velocity"})


def export_session_stats_json(obj: SessionStatsObject) -> str:
    """JSON-строка для персистенции (только JSON-serializable значения)."""
    data = _dump_session_for_storage(obj)
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def import_session_stats_json(raw: str) -> SessionStatsObject:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("session stats JSON must decode to an object")
    return SessionStatsObject.model_validate(data)


def session_stats_to_plain_dict(obj: SessionStatsObject) -> dict[str, Any]:
    """Плоский dict для user_state / UI без ORM-специфики."""
    base = _dump_session_for_storage(obj)
    base["duration_seconds"] = obj.duration_seconds
    base["velocity"] = obj.velocity
    return base


def seven_day_schedule_counts(predictions: list[RetentionPrediction]) -> list[int]:
    """Детерминированно: 7 слотов по количеству due_cards (отсутствующие дни = 0)."""
    by_day = {p.day_index: p.due_cards for p in sorted(predictions, key=lambda x: x.day_index)}
    return [int(by_day.get(i, 0)) for i in range(7)]


def assert_fully_json_serializable(obj: Any) -> None:
    json.dumps(obj)
