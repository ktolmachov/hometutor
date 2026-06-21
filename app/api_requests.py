from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.config import KNOWN_PROFILES


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    question: str
    folder: Optional[str] = None
    folder_rel: Optional[str] = None
    file_name: Optional[str] = None
    relative_path: Optional[str] = None
    topic: Optional[str] = None
    homework_mode: bool = False
    assistance_level: Optional[str] = None
    # Уровень ДЗ внутри tutor-сессии или обычного Q&A: hint | plan | error_review | full_solution
    homework_level: Optional[str] = None
    study_mode: bool = False
    followup_context: Optional[str] = None
    # Multi-turn / tutor (итерация 19)
    session_id: Optional[str] = None
    query_mode: Optional[str] = None
    # Режим шаблона квиза (micro-quiz в tutor): auto | default | understand_topic | exam_prep | solve_homework
    quiz_learning_mode: Optional[str] = None
    # E24-A: optional learner goal context for tutor (session/request-scoped)
    tutor_goal_subtopic: Optional[str] = None
    tutor_goal_target_level: Optional[str] = None
    tutor_goal_desired_outcome: Optional[str] = None
    tutor_goal_time_budget_min: Optional[int] = None
    profile: Optional[str] = None

    @field_validator("profile", mode="before")
    @classmethod
    def normalize_profile(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        profile = str(value).strip().lower()
        if not profile:
            return None
        if profile not in KNOWN_PROFILES:
            valid = ", ".join(sorted(KNOWN_PROFILES))
            raise ValueError(f"Unknown RAG profile '{profile}'. Valid profiles: {valid}")
        return profile

    @property
    def rag_profile(self) -> Optional[str]:
        return self.profile


class LearnerGoalSnapshotPutRequest(BaseModel):
    """Тело PUT для сохранённого снимка цели (E24-B), поля как у ``goal_context`` / ``tutor_goal_*``."""

    model_config = ConfigDict(extra="forbid", strict=True)

    topic: Optional[str] = None
    subtopic: Optional[str] = None
    target_level: Optional[str] = None
    desired_outcome: Optional[str] = None
    time_budget_min: Optional[int] = None
    preferred_style: Optional[str] = None
    learning_goal: Optional[str] = None


class SsrRecommendationFeedbackPostRequest(BaseModel):
    """Локальная запись accept/reject/defer по SSR (без политики, без PII)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["accept", "reject", "defer"]
    hint_kind: str
    primary_nav: str
    weak_concept_sha256: Optional[str] = None
    why_now_len: int = 0
    explanation_outcome: Optional[str] = None
    latency_ms: Optional[float] = None
    session_key_prefix: Optional[str] = None


class SynthesizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    topic: Optional[str] = None
    topic_id: Optional[str] = None
    documents: Optional[list[str]] = None


class LearningPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    topic: Optional[str] = None
    topic_id: Optional[str] = None
    documents: Optional[list[str]] = None
    goal: Optional[str] = None
    level: Optional[str] = None
    time_budget_hours: Optional[float] = None
    known_topics: Optional[list[str]] = None
    user_progress: bool = False
