"""State-changing learner facts require source/tool event provenance (wave A4 package 2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import get_settings

FactSourceType = Literal["quiz_result", "user_action", "tool", "system_bypass"]


class FactSourceBindingError(ValueError):
    """Raised when a learner_state write lacks required provenance."""


class FactSourceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: FactSourceType
    event_id: str | None = None
    tool_name: str | None = None
    concept: str | None = None
    level: str | None = None


_LAST_MASTERY_PROVENANCE: FactSourceProvenance | None = None


def is_fact_source_binding_enabled() -> bool:
    return bool(get_settings().fact_source_binding_enabled)


def set_last_mastery_provenance(provenance: FactSourceProvenance | None) -> None:
    global _LAST_MASTERY_PROVENANCE  # noqa: PLW0603
    _LAST_MASTERY_PROVENANCE = provenance


def get_last_mastery_provenance() -> FactSourceProvenance | None:
    return _LAST_MASTERY_PROVENANCE


def _validate_provenance_shape(provenance: FactSourceProvenance) -> None:
    if provenance.source_type == "quiz_result" and not str(provenance.event_id or "").strip():
        raise FactSourceBindingError("quiz_result provenance requires event_id")
    if provenance.source_type == "tool" and not str(provenance.tool_name or "").strip():
        raise FactSourceBindingError("tool provenance requires tool_name")


def require_fact_provenance(
    provenance: FactSourceProvenance | None,
    *,
    operation: str,
) -> FactSourceProvenance:
    if not is_fact_source_binding_enabled():
        bypass = FactSourceProvenance(source_type="system_bypass", event_id="legacy")
        return provenance or bypass
    if provenance is None:
        raise FactSourceBindingError(f"{operation}: missing provenance")
    try:
        validated = FactSourceProvenance.model_validate(provenance.model_dump())
    except ValidationError as exc:
        raise FactSourceBindingError(f"{operation}: invalid provenance") from exc
    _validate_provenance_shape(validated)
    return validated


def build_quiz_event_provenance(
    *,
    quiz_result_id: int,
    concept: str,
    level: str,
) -> FactSourceProvenance:
    return FactSourceProvenance(
        source_type="quiz_result",
        event_id=str(int(quiz_result_id)),
        concept=(concept or "").strip() or None,
        level=(level or "").strip() or None,
    )


def provenance_to_evidence_line(provenance: FactSourceProvenance | None) -> str | None:
    if provenance is None:
        return None
    if provenance.source_type == "quiz_result":
        event_id = str(provenance.event_id or "").strip() or "?"
        concept = str(provenance.concept or "—").strip()
        level = str(provenance.level or "—").strip()
        return f"Mastery event (локально): quiz_result #{event_id}, концепт «{concept}», уровень {level}"
    if provenance.source_type == "tool":
        tool = str(provenance.tool_name or "—").strip()
        return f"Mastery event (tool): {tool}"
    if provenance.source_type == "user_action":
        return "Mastery event (user_action): явное действие пользователя"
    return None


def is_influencing_provenance_line(line: str) -> bool:
    text = (line or "").strip()
    return text.startswith("Mastery event")


def provenance_to_dict(provenance: FactSourceProvenance | None) -> dict[str, Any] | None:
    if provenance is None:
        return None
    return provenance.model_dump()


def apply_quiz_outcome_to_learner_state(
    *,
    concept: str,
    score: float,
    level: str,
    quiz_result_id: int,
) -> dict[str, Any]:
    """Single entry: provenance gate + SM-2 + quiz_mastery after a persisted quiz result."""
    from app.quiz_adaptive import update_mastery_after_score
    from app.spaced_repetition import record_quiz_score_for_spaced_repetition

    provenance = require_fact_provenance(
        build_quiz_event_provenance(
            quiz_result_id=quiz_result_id,
            concept=concept,
            level=level,
        ),
        operation="apply_quiz_outcome_to_learner_state",
    )
    sr = record_quiz_score_for_spaced_repetition(concept, score, provenance=provenance)
    mastery = update_mastery_after_score(concept, score, provenance=provenance)
    set_last_mastery_provenance(provenance)
    return {
        "spaced_repetition": sr,
        "quiz_adaptive": mastery,
        "provenance": provenance_to_dict(provenance),
    }


__all__ = [
    "FactSourceBindingError",
    "FactSourceProvenance",
    "apply_quiz_outcome_to_learner_state",
    "build_quiz_event_provenance",
    "get_last_mastery_provenance",
    "is_fact_source_binding_enabled",
    "is_influencing_provenance_line",
    "provenance_to_dict",
    "provenance_to_evidence_line",
    "require_fact_provenance",
    "set_last_mastery_provenance",
]
