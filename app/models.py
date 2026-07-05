from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

GraphRelationDirection = Literal["forward", "reverse", "undirected"]


@dataclass
class Message:
    """Одно сообщение в истории разговора (multi-turn, tutor)."""

    role: str  # "user" | "assistant" | ...
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QueryOptions:
    folder: Optional[str] = None
    folder_rel: Optional[str] = None
    file_name: Optional[str] = None
    relative_path: Optional[str] = None
    # Новые семантические фильтры (Итерация 11)
    topic: Optional[str] = None
    logical_folder: Optional[str] = None  # мапится на metadata["folder"]
    file: Optional[str] = None  # мапится на metadata["file"]
    homework_mode: bool = False
    assistance_level: Optional[str] = None
    study_mode: bool = False
    followup_context: Optional[str] = None
    # Итерация 19: сессии и нейтральный transport для режимов
    session_id: Optional[str] = None
    query_mode: Optional[str] = None
    # Tutor: сценарий входа и желаемая глубина ответа (UI → промпт)
    tutor_learning_goal: Optional[str] = None  # understand_topic | exam_prep | solve_homework
    tutor_answer_depth: Optional[str] = None  # short | examples | deep
    tutor_preferred_style: Optional[str] = None  # balanced | examples | theory | practice
    tutor_mastery_level: Optional[str] = None  # beginner | intermediate | advanced — для micro-quiz
    # Шаблон промпта квиза: None | auto — как learning_goal; иначе default | understand_topic | exam_prep | solve_homework
    quiz_learning_mode: Optional[str] = None
    # E24-A: явный goal context для короткого tutor loop (request-scoped)
    tutor_goal_subtopic: Optional[str] = None
    tutor_goal_target_level: Optional[str] = None
    tutor_goal_desired_outcome: Optional[str] = None
    tutor_goal_time_budget_min: Optional[int] = None
    rag_profile: Optional[str] = None
    # Flashcard gap handoff: fast tutor path without changing default tutor chat
    tutor_entrypoint: Optional[str] = None

    def cache_key(self) -> tuple:
        return (
            self.folder,
            self.folder_rel,
            self.file_name,
            self.relative_path,
            self.topic,
            self.logical_folder,
            self.file,
            self.homework_mode,
            self.assistance_level,
            self.study_mode,
            self.followup_context,
            self.tutor_learning_goal,
            self.tutor_answer_depth,
            self.tutor_preferred_style,
            self.tutor_mastery_level,
            self.quiz_learning_mode,
            self.tutor_goal_subtopic,
            self.tutor_goal_target_level,
            self.tutor_goal_desired_outcome,
            self.tutor_goal_time_budget_min,
            self.rag_profile,
            self.tutor_entrypoint,
        )


@dataclass(frozen=True)
class PipelineOverrides:
    rag_profile: Optional[str] = None
    similarity_top_k: Optional[int] = None
    enable_reranker: Optional[bool] = None
    rerank_top_n: Optional[int] = None
    rerank_model: Optional[str] = None
    split_strategy: Optional[str] = None
    window_size: Optional[int] = None
    retrieval_mode: Optional[str] = None
    doc_top_k: Optional[int] = None


RetrievalSource = Literal["vector", "bm25", "rrf", "reranker", "graph_expansion", "doc_then_chunk"]


class GraphEvidence(BaseModel):
    """ADR-021 §7.2: typed provenance для рёбер графа, попавших в graph expansion."""

    source_entity: str
    target_entity: str
    relation_id: str
    relation_type: str
    direction: GraphRelationDirection = "forward"
    evidence_doc_id: str
    evidence_chunk_id: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    generation_id: Optional[str] = None
    extraction_method: Optional[str] = None
    weak_evidence: bool = False
    inferred_relation: bool = Field(
        default=False,
        description="True когда confidence ниже порога weak evidence (модель должна трактовать как inferred).",
    )


class GraphQualityGateResult(BaseModel):
    name: str
    required: str
    actual: str
    passed: bool


class GraphQualityReport(BaseModel):
    generation_id: str
    scope_hash: str
    gate_passed: bool
    published: bool = False
    metrics: Dict[str, Any] = Field(default_factory=dict)
    gates: List[GraphQualityGateResult] = Field(default_factory=list)
    fail_reasons: List[str] = Field(default_factory=list)
    concept_id_map: Dict[str, str] = Field(default_factory=dict)
    truncated: bool = False


class CourseGraphBinding(BaseModel):
    generation_id: str
    scope_hash: str
    source_content_hashes: List[str] = Field(default_factory=list)
    graph_quality_summary: Dict[str, Any] = Field(default_factory=dict)


class RagProfile(BaseModel):
    name: str
    retrieval_mode: str
    graph_augmented: bool = False
    description: Optional[str] = None


class RetrievalRoutingDecision(BaseModel):
    selected_profile: str
    effective_profile: str
    selected_retrieval_mode: str
    effective_retrieval_mode: str
    graph_augmented_requested: bool = False
    effective_graph_augmented: bool = False
    fallback_reason: Optional[str] = None
    profile_resolved_from: str
    manual_override: bool = False
    classify_query_type: str
    classify_confidence: Optional[float] = None
    classify_method: Optional[str] = None
    signals: Dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class QueryExecutionPlan:
    query_type: str
    prompt_key: str
    retrieval_mode: str
    enable_reranker: bool
    similarity_top_k: int
    rerank_top_n: int
    rerank_model: str
    split_strategy: str
    window_size: int
    profile: str
    homework_mode: bool
    assistance_level: Optional[str]
    query_engine_cache_policy: str
    faq_cache_eligible: bool
    faq_cache_skip_reason: Optional[str]
    doc_top_k: Optional[int] = None

    def to_pipeline_params(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "query_type": self.query_type,
            "prompt_key": self.prompt_key,
            "retrieval_mode": self.retrieval_mode,
            "enable_reranker": self.enable_reranker,
            "similarity_top_k": self.similarity_top_k,
            "rerank_top_n": self.rerank_top_n,
            "rerank_model": self.rerank_model,
            "split_strategy": self.split_strategy,
            "window_size": self.window_size,
            "doc_top_k": self.doc_top_k,
            "homework_mode": self.homework_mode,
            "assistance_level": self.assistance_level,
            "query_engine_cache_policy": self.query_engine_cache_policy,
            "faq_cache_eligible": self.faq_cache_eligible,
            "faq_cache_skip_reason": self.faq_cache_skip_reason,
        }


@dataclass
class QueryContext:
    """Carries state through the composable pipeline (ADR-010).

    Each step reads and enriches this object. ``effective_query`` provides
    the query string that downstream retrieval should use.
    """

    original_question: str
    query_options: QueryOptions = field(default_factory=QueryOptions)

    # --- Session / multi-turn (итерация 19) ---
    session_id: Optional[str] = None
    conversation_history: list[Message] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # --- Classify step ---
    query_type: str = "qa"
    classify_confidence: float = 1.0
    classify_method: str = "default"  # default | heuristic | llm

    # --- Condense step (multi-turn): dialog → one line; separate from rewrite ---
    condensed_question: Optional[str] = None

    # --- Rewrite step ---
    rewritten_query: Optional[str] = None
    subquestions: list[str] = field(default_factory=list)

    # --- Pipeline config resolved by router ---
    retrieval_strategy: str = "default"  # default → use config; hybrid | bm25_only | doc_then_chunk | vector_only
    prompt_key: str = "qa"

    # --- Debug / tracing ---
    trace: dict = field(default_factory=dict)
    pipeline_steps: List[str] = field(default_factory=list)

    @property
    def effective_query_source(self) -> str:
        if self.condensed_question:
            return "condensed"
        if self.rewritten_query:
            return "rewritten"
        return "original"

    @property
    def effective_query(self) -> str:
        return (
            self.condensed_question
            or self.rewritten_query
            or self.original_question
        )


class QueryClientParams(BaseModel):
    """Транспортные опции из API/CLI/UI: сессия, режим, лимиты генерации.

    Не заменяет ``QueryOptions`` (фильтры retrieval / ingest metadata).
    """

    session_id: Optional[str] = None
    query_mode: Optional[str] = None
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=4.0)
    max_sources: int = Field(default=8, ge=1, le=128)


__all__ = [
    "Message",
    "QueryExecutionPlan",
    "PipelineOverrides",
    "QueryClientParams",
    "QueryContext",
    "QueryOptions",
    "RagProfile",
    "RetrievalRoutingDecision",
    "RetrievalSource",
    "GraphEvidence",
    "GraphRelationDirection",
    "GraphQualityGateResult",
    "GraphQualityReport",
    "CourseGraphBinding",
]
