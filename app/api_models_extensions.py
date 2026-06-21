from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from app.api_models_main import AskSource

class MetricsResponse(BaseModel):
    requests_total: int
    fallback_total: int
    errors_total: int
    fallback_rate: Optional[float] = None
    requests_without_sources_total: int = 0
    requests_without_sources_rate: Optional[float] = None
    empty_answers_total: int = 0
    empty_answers_rate: Optional[float] = None
    avg_sources_per_request: Optional[float] = None
    avg_coverage_ratio: Optional[float] = None
    query_types: Dict[str, int]
    latency_ms: MetricsLatency
    estimated_cost_usd: EstimatedCostMetrics
    quality_checks: QualityChecksMetrics
    last_request: Optional[LastRequestMetrics] = None


class IndexStatsResponse(BaseModel):
    status: str
    collection_name: str
    documents_count: int
    nodes_count: int
    files: List[str]
    last_indexed_at: Optional[str] = None


class CacheLatencyStats(BaseModel):
    hit_count: int
    miss_count: int
    hit_latency_avg_ms: Optional[float] = None
    miss_latency_avg_ms: Optional[float] = None
    last_hit_latency_ms: Optional[float] = None
    last_miss_latency_ms: Optional[float] = None


class CacheStatsResponse(BaseModel):
    base_services_initialized: bool
    query_engine_cache_size: int
    query_engine_cache_capacity: int
    query_engine_ttl_sec: int
    hits: int
    misses: int
    evictions: int
    expired: int
    latency: CacheLatencyStats
    keys: List[str]


class TopicDocument(BaseModel):
    doc_id: str
    relative_path: str
    file_name: Optional[str] = None
    folder_name: Optional[str] = None
    summary: Optional[str] = None
    doc_type: Optional[str] = None
    difficulty: Optional[str] = None
    key_concepts: List[str]


class TopicItem(BaseModel):
    topic_id: str
    topic_name: str
    document_count: int
    key_concepts: List[str]
    documents: List[TopicDocument]


class TopicsResponse(BaseModel):
    topics: List[TopicItem]
    total_topics: int
    total_documents: int


class KBTopConcept(BaseModel):
    name: str
    count: int


class KBFolderDistributionItem(BaseModel):
    folder: str
    count: int


class KBTopicSize(BaseModel):
    topic_name: str
    document_count: int


class KBOverviewResponse(BaseModel):
    total_topics: int
    total_documents: int
    top_concepts: List[KBTopConcept]
    folder_distribution: List[KBFolderDistributionItem]
    topic_sizes: List[KBTopicSize]


class KBSimilarQuestion(BaseModel):
    question: Optional[str] = None
    score: Optional[float] = None


class KBRelatedTopic(BaseModel):
    topic_id: str
    topic_name: str
    overlap_count: int
    total_docs: int
    unexplored_count: int


class KBSuggestionsResponse(BaseModel):
    related_topics: List[KBRelatedTopic]
    unexplored_documents: List[str]
    similar_questions: List[KBSimilarQuestion]


class KBSearchTopic(BaseModel):
    topic_id: str
    topic_name: str
    document_count: int


class KBSearchDocument(BaseModel):
    relative_path: Optional[str] = None
    file_name: Optional[str] = None
    topic_name: Optional[str] = None
    summary: Optional[str] = None


class KBSearchConcept(BaseModel):
    name: str
    topics: List[str]


class KBSearchResponse(BaseModel):
    topics: List[KBSearchTopic]
    documents: List[KBSearchDocument]
    concepts: List[KBSearchConcept]
    query: str


class SynthesisSection(BaseModel):
    relative_path: str
    summary: Optional[str] = None
    key_concepts: List[str]
    chunks: List[str]


class CoverageInfo(BaseModel):
    covered: int
    total: int
    ratio: float
    missing: List[str]
    topic_name: Optional[str] = None
    topic_id: Optional[str] = None
    label: str


class SynthesizeDocument(BaseModel):
    doc_id: str
    relative_path: str
    file_name: Optional[str] = None
    folder_name: Optional[str] = None
    summary: Optional[str] = None
    doc_type: Optional[str] = None
    difficulty: Optional[str] = None
    key_concepts: List[str]


class SynthesizeResponse(BaseModel):
    topic: str
    summary: str
    documents: List[SynthesizeDocument]
    sections: List[SynthesisSection]
    sources: List[AskSource]
    coverage: CoverageInfo


class LearningPlanRequest(BaseModel):
    topic: Optional[str] = None
    topic_id: Optional[str] = None
    documents: Optional[List[str]] = None
    goal: Optional[str] = None
    level: Optional[str] = None
    time_budget_hours: Optional[float] = None
    known_topics: List[str] = Field(default_factory=list)
    user_progress: bool = False


class LearningPlanResponse(BaseModel):
    topic: str
    goal: str
    level: str
    time_budget_hours: Optional[float] = None
    plan: str
    documents: List[SynthesizeDocument]
    sources: List[AskSource]
    coverage: CoverageInfo
    missing_topics: List[str]
    dynamic_plan: Optional[Dict[str, Any]] = None


class GraphPrerequisitesHealthResponse(BaseModel):
    """Сводка по prerequisites графа для learning-plan path и диагностики (17 Core Extension)."""

    schema_version: int = 1
    concept_count: int
    cycle_count: int
    cycles: List[List[str]]
    has_prerequisite_cycles: bool
    topological_order_ok: bool


class NextBestActionItem(BaseModel):
    concept: str
    score: float
    weak_component: float
    prerequisite_component: float
    spaced_component: float


class NextBestActionsResponse(BaseModel):
    """GET /kb/graph/next-best-actions — ранжирование концептов (NBA) с привязкой к quiz + spaced repetition."""

    schema_version: int = 1
    limit: int
    actions: List[NextBestActionItem]
    topological_order_ok: bool
    prerequisite_cycles: List[List[str]]
    topological_fallback: Optional[str] = None


class LearningPlanGraphBundleNBA(BaseModel):
    limit: int
    actions: List[NextBestActionItem]
    topological_order_ok: bool
    prerequisite_cycles: List[List[str]]
    topological_fallback: Optional[str] = None


class LearningPlanGraphBundleResponse(BaseModel):
    """GET /kb/learning-plan/graph-bundle — детерминированный graph-контекст для плана без LLM."""

    schema_version: int = 1
    prerequisites: GraphPrerequisitesHealthResponse
    next_best_actions: LearningPlanGraphBundleNBA
    topological_preview: List[str]
    topological_fallback: Optional[str] = None


class KnowledgeWorkflowEventRequest(BaseModel):
    """UI-originated knowledge workflow analytics (Streamlit → metrics_store)."""

    action: str
    knowledge_product_trace: Optional[Dict[str, Any]] = None
    payload: Optional[Dict[str, Any]] = None
    client_event_id: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# Flashcards (E12)
# ─────────────────────────────────────────────────────────────


class FlashcardCardOut(BaseModel):
    id: int
    deck_id: int
    front: str
    back: str
    tags: Optional[str] = None
    easiness: float
    interval_days: int
    repetitions: int
    next_review: Optional[str] = None
    last_review: Optional[str] = None
    created_at: str
    updated_at: str


class FlashcardDeckOut(BaseModel):
    id: int
    name: str
    source_type: str
    source_id: Optional[str] = None
    card_count: int
    due_count: int = 0
    created_at: str
    updated_at: str


class FlashcardDeckDetailOut(FlashcardDeckOut):
    cards: List[FlashcardCardOut] = []


class FlashcardGenerateResponse(BaseModel):
    success: bool
    deck_title: str
    cards: List[Dict[str, Any]]
    error: Optional[str] = None


class FlashcardReviewResponse(BaseModel):
    card_id: int
    easiness: float
    interval_days: int
    repetitions: int
    next_review: str
    last_review: str


class FlashcardDueResponse(BaseModel):
    cards: List[Dict[str, Any]]
    count: int


class FlashcardDeckProgressResponse(BaseModel):
    deck_id: int
    mastered: int
    total: int
    percent: float


class LearnerGoalContextOut(BaseModel):
    """Снимок полей ``goal_context`` (E24-A/B), совместим с ``build_learner_goal_context_dict``."""

    topic: str = "general"
    subtopic: Optional[str] = None
    target_level: Optional[str] = None
    desired_outcome: Optional[str] = None
    time_budget_min: Optional[int] = None
    preferred_style: str = "balanced"
    learning_goal: str = "understand_topic"


class LearnerGoalSnapshotOut(BaseModel):
    schema_version: Optional[int] = None
    updated_at: Optional[str] = None
    goal_context: Optional[LearnerGoalContextOut] = None
