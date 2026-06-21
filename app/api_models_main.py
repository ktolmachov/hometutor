from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_serializer


class RootResponse(BaseModel):
    message: str
    docs: str
    health: str


class HealthResponse(BaseModel):
    status: str


class AskSource(BaseModel):
    cite_index: Optional[int] = None
    route: Optional[str] = None
    rank_reason: Optional[str] = None
    file_name: Optional[str] = None
    folder_name: Optional[str] = None
    folder_rel: Optional[str] = None
    relative_path: Optional[str] = None
    page: Optional[str] = None
    score: Optional[float] = None
    text: str
    graph_evidence: Optional[List[Dict[str, Any]]] = None
    retrieval_source: Optional[str] = None


class RetrievalConfidence(BaseModel):
    """Сводный сигнал про покрытие источниками и силу retrieval, не вероятность истинности ответа."""

    level: str
    label: str
    source_count: int
    avg_source_score: Optional[float] = None
    unique_source_files: int
    reasons: List[str]


# Прежнее имя схемы в интроспекции клиентов; то же содержание, что и RetrievalConfidence.
AnswerConfidence = RetrievalConfidence


class GuardrailsDebug(BaseModel):
    input_validated: bool
    output_validated: bool
    fallback_applied: bool
    code: Optional[str] = None
    message: Optional[str] = None


class GroundedDebug(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_validated: Optional[bool] = None
    abstain_reason_code: Optional[str] = None
    facts_count: Optional[int] = None
    citation_coverage: Optional[float] = None
    provenance_ledger: Optional[Union[List[Dict[str, Any]], Dict[str, Any]]] = None
    validation_errors: Optional[List[str]] = None


class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class StageTokenUsage(BaseModel):
    classify: Optional[TokenUsage] = None
    rewrite: Optional[TokenUsage] = None
    retrieval: Optional[TokenUsage] = None
    generation: Optional[TokenUsage] = None
    judge: Optional[TokenUsage] = None


class TokenUsageDebug(BaseModel):
    stages: StageTokenUsage
    total: Optional[TokenUsage] = None


class StageEstimatedCost(BaseModel):
    classify: Optional[float] = None
    rewrite: Optional[float] = None
    retrieval: Optional[float] = None
    generation: Optional[float] = None
    judge: Optional[float] = None


class EstimatedCostDebug(BaseModel):
    stages: StageEstimatedCost
    total: Optional[float] = None


class AskDebug(BaseModel):
    model_config = ConfigDict(extra="allow")

    cache_hit: Optional[bool] = None
    pipeline_ms: Optional[float] = None
    engine_acquire_ms: Optional[float] = None
    query_execute_ms: Optional[float] = None
    total_answer_ms: Optional[float] = None
    # Имя RAG-профиля ("fast" / "quality") или объект таймингов из /profile/query
    profile: Optional[Union[str, Dict[str, Any]]] = None
    query_type: Optional[str] = None
    classify_method: Optional[str] = None
    classify_confidence: Optional[float] = None
    retrieval_mode: Optional[str] = None
    retrieval_routing: Optional[Dict[str, Any]] = None
    similarity_top_k: Optional[int] = None
    rerank_enabled: Optional[bool] = None
    rerank_top_n: Optional[int] = None
    rerank_model: Optional[str] = None
    rewrite: Optional[bool] = None
    rewritten_question: Optional[str] = None
    rewrite_model: Optional[str] = None
    llm_source: Optional[str] = None
    llm_model: Optional[str] = None
    llm_api_base: Optional[str] = None
    fallback_used: Optional[bool] = None
    llm_profile: Optional[str] = None
    llm_latency_ms: Optional[float] = None
    subquestions: Optional[List[str]] = None
    token_usage: Optional[TokenUsageDebug] = None
    estimated_cost_usd: Optional[EstimatedCostDebug] = None
    homework_mode: Optional[bool] = None
    assistance_level: Optional[str] = None
    # Уровень ДЗ (echo из запроса / tutor): hint | plan | error_review | full_solution
    homework_level: Optional[str] = None
    study_mode: Optional[bool] = None
    followup_context_used: Optional[bool] = None
    pipeline_trace: Optional[Dict[str, Any]] = None
    guardrails: Optional[GuardrailsDebug] = None
    grounded: Optional[GroundedDebug] = None
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    query_mode: Optional[str] = None


class TutorCycleState(BaseModel):
    """Состояние tutor retention cycle (итерация 19.3): ответ → quiz → feedback → next step."""

    model_config = ConfigDict(extra="allow")

    contract_version: Optional[int] = 1
    session_id: Optional[str] = None
    phase: Optional[str] = None
    quiz_state: Optional[Dict[str, Any]] = None
    review_state: Optional[Dict[str, Any]] = None
    recommended_next_action: Optional[str] = None
    next_action_reason: Optional[str] = None
    default_next_step: Optional[str] = None


class TutorPipelineStep(BaseModel):
    model_config = ConfigDict(extra="allow")

    step: Optional[str] = None
    status: Optional[str] = None
    detail: Optional[str] = None


class TutorOrchestrationPipeline(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: Optional[int] = None
    phase: Optional[str] = None
    decision_source: Optional[str] = None
    selected_agent: Optional[str] = None
    should_trigger_microquiz: Optional[bool] = None
    policy_clamped: Optional[bool] = None
    policy_clamp_reasons: Optional[List[str]] = None


class TutorOrchestrationState(BaseModel):
    model_config = ConfigDict(extra="allow")

    contract_version: Optional[int] = 1
    current_concept: Optional[str] = None
    mastery_estimate: Optional[str] = None
    last_error_type: Optional[str] = None
    needs_review: Optional[bool] = None
    prerequisite_gap: Optional[str] = None
    recommended_action: Optional[str] = None
    orchestration_phase: Optional[str] = None
    orchestration_decision_source: Optional[str] = None
    selected_agent: Optional[str] = None
    should_trigger_microquiz: Optional[bool] = None
    policy_clamped: Optional[bool] = None
    policy_clamp_reasons: Optional[List[str]] = None
    tutor_orchestration_pipeline: Optional[TutorOrchestrationPipeline] = None


class TutorAnswer(BaseModel):
    model_config = ConfigDict(extra="allow")

    contract_version: Optional[int] = 1
    answer_kind: Optional[str] = None
    teaching_summary: Optional[str] = None
    check_question: Optional[str] = None
    next_action: Optional[str] = None
    next_action_reason: Optional[str] = None
    suggested_ctas: Optional[List[str]] = None
    understanding_state: Optional[Dict[str, Any]] = None
    depth_level: Optional[str] = None
    trust_signals: Optional[Dict[str, Any]] = None
    inline_quiz: Optional[List[Dict[str, Any]]] = None
    auto_quiz: Optional[Dict[str, Any]] = None
    learner_profile: Optional[Dict[str, Any]] = None
    route: Optional[str] = None
    recommended_quiz_topic: Optional[str] = None


class TutorPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    teaching: Optional[Dict[str, Any]] = None
    decision: Optional[Dict[str, Any]] = None
    auto_quiz: Optional[Dict[str, Any]] = None
    inline_quiz: Optional[List[Dict[str, Any]]] = None
    socratic_followup: Optional[Dict[str, Any]] = None
    learner_profile: Optional[Dict[str, Any]] = None
    tutor_cycle: Optional[TutorCycleState] = None
    orchestration_state: Optional[TutorOrchestrationState] = None
    socratic: Optional[Dict[str, Any]] = None
    tutor_orchestration_pipeline: Optional[TutorOrchestrationPipeline] = None
    tutor_pipeline: Optional[List[TutorPipelineStep]] = None
    # E6.5: денормализация стабильных полей контракта для typed read-path / OpenAPI (дублируют tutor_orchestration_pipeline)
    orchestration_phase: Optional[str] = None
    orchestration_decision_source: Optional[str] = None
    selected_agent: Optional[str] = None
    should_trigger_microquiz: Optional[bool] = None
    policy_clamped: Optional[bool] = None
    policy_clamp_reasons: Optional[List[str]] = None


class AskResponse(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    answer: str
    sources: List[AskSource]
    answer_status: Optional[Literal["grounded", "abstain", "guardrails_fallback"]] = None
    retrieval_confidence: Optional[RetrievalConfidence] = Field(
        default=None,
        validation_alias=AliasChoices("retrieval_confidence", "confidence"),
        description=(
            "Explainability-сигнал по покрытию источников и качеству retrieval; "
            "не калиброванная вероятность того, что текст ответа фактологически верен."
        ),
    )
    tutor: Optional[TutorPayload] = None
    tutor_answer: Optional[TutorAnswer] = None
    debug: AskDebug

    @model_serializer(mode="wrap")
    def _serialize_confidence_aliases(self, handler):
        data = handler(self)
        bucket = data.get("retrieval_confidence")
        if bucket is not None:
            data["confidence"] = bucket
        return data


class HistoryItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str
    timestamp: str
    index_version: Optional[str] = None
    question: str
    answer: str
    sources: List[AskSource]
    answer_status: Optional[Literal["grounded", "abstain", "guardrails_fallback"]] = None
    retrieval_confidence: Optional[RetrievalConfidence] = Field(
        default=None,
        validation_alias=AliasChoices("retrieval_confidence", "confidence"),
        description=(
            "Как в /ask: сигнал про retrieval/источники, не гарантия истинности формулировки."
        ),
    )
    debug: AskDebug

    @model_serializer(mode="wrap")
    def _serialize_confidence_aliases(self, handler):
        data = handler(self)
        bucket = data.get("retrieval_confidence")
        if bucket is not None:
            data["confidence"] = bucket
        return data


class HistoryResponse(BaseModel):
    items: List[HistoryItem]
    total: int


class PipelineTraceItem(BaseModel):
    request_id: str
    timestamp: str
    index_version: Optional[str] = None
    query_type: Optional[str] = None
    classify_confidence: Optional[float] = None
    pipeline_trace: Dict[str, Any]


class PipelineTraceResponse(BaseModel):
    items: List[PipelineTraceItem]
    total: int


class MetricsStoreItem(BaseModel):
    event_type: str
    timestamp: str
    request_id: Optional[str] = None
    run_type: Optional[str] = None
    endpoint: Optional[str] = None
    error_kind: Optional[str] = None
    error_type: Optional[str] = None
    status_code: Optional[int] = None
    message: Optional[str] = None
    query_type: Optional[str] = None
    question_preview: Optional[str] = None
    source_count: Optional[int] = None
    fallback_applied: Optional[bool] = None
    answer_empty: Optional[bool] = None
    total_files: Optional[int] = None
    processed_files: Optional[int] = None
    unique_doc_ids: Optional[int] = None
    nodes_count: Optional[int] = None
    summary_documents: Optional[int] = None
    duration_sec: Optional[float] = None
    latency_ms: Optional[Dict[str, Optional[float]]] = None
    coverage_ratio: Optional[float] = None
    estimated_cost_usd: Optional[Any] = None
    token_usage: Optional[Dict[str, Any]] = None
    enrichment_stats: Optional[Dict[str, Any]] = None
    quality_checks: Optional[Dict[str, Any]] = None
    pipeline_trace: Optional[Dict[str, Any]] = None
    retrieval_trace: Optional[Dict[str, Any]] = None


class MetricsStoreResponse(BaseModel):
    schema_version: int
    items: List[MetricsStoreItem]
    total: int


class FeedbackRequest(BaseModel):
    helpful: bool
    request_id: Optional[str] = None
    comment: Optional[str] = None
    question_preview: Optional[str] = None
    source: str = "ui"


class FeedbackSummaryResponse(BaseModel):
    schema_version: int
    total_events: int
    helpful_yes: int
    helpful_no: int
    helpful_rate: Optional[float] = None
    error: Optional[str] = None


class MetricsLatency(BaseModel):
    avg_pipeline_ms: Optional[float] = None
    avg_engine_acquire_ms: Optional[float] = None
    avg_query_execute_ms: Optional[float] = None
    avg_total_answer_ms: Optional[float] = None
    p50_pipeline_ms: Optional[float] = None
    p95_pipeline_ms: Optional[float] = None
    p99_pipeline_ms: Optional[float] = None
    p50_total_answer_ms: Optional[float] = None
    p95_total_answer_ms: Optional[float] = None
    p99_total_answer_ms: Optional[float] = None


class LastRequestMetrics(BaseModel):
    request_id: str
    question_preview: str
    query_type: str
    source_count: int
    fallback_applied: bool
    total_answer_ms: float
    estimated_cost_usd: Optional[float] = None


class EstimatedCostMetrics(BaseModel):
    avg_per_request: Optional[float] = None
    total: float


class CostDashboardTotals(BaseModel):
    total: float
    avg_per_request: Optional[float] = None
    p95_per_request: Optional[float] = None
    max_per_request: Optional[float] = None


class CostByQueryType(BaseModel):
    count: int
    total_usd: float
    avg_usd: Optional[float] = None


class CostDashboardRequestItem(BaseModel):
    request_id: Optional[str] = None
    query_type: Optional[str] = None
    question_preview: Optional[str] = None
    estimated_cost_usd: float
    timestamp: Optional[str] = None


class CostDashboardProjections(BaseModel):
    per_100_requests_usd: Optional[float] = None
    per_1000_requests_usd: Optional[float] = None
    daily_100_requests_usd: Optional[float] = None


class CostDashboardWindow(BaseModel):
    requests: int
    ingestion_runs: int
    reindex_runs: int


class IngestionCostTotals(BaseModel):
    total: float
    avg_per_run: Optional[float] = None
    full_reindex_total: float
    last_run: Optional[Dict[str, Any]] = None


class CostDashboardResponse(BaseModel):
    schema_version: int
    window_size: CostDashboardWindow
    query_estimated_cost_usd: CostDashboardTotals
    by_query_type: Dict[str, CostByQueryType]
    top_expensive_requests: List[CostDashboardRequestItem]
    ingestion_estimated_cost_usd: IngestionCostTotals
    projections: CostDashboardProjections
    # Rollup of per-stage LLM/embed costs when present on request events
    estimated_cost_by_stage_usd: Optional[Dict[str, Any]] = None


class QualityMetricsResponse(BaseModel):
    schema_version: int
    window_size: Dict[str, int]
    deterministic: Dict[str, Any]
    judge: Dict[str, Any]


class QualityChecksMetrics(BaseModel):
    requests_evaluated: int
    failure_counts: Dict[str, int]
    failure_rates: Dict[str, float]


