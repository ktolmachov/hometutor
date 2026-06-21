"""Smart Study Router public facade.

Pure routing contract for the next learning step. Rule construction, local
evidence ledger, and optional SSR ML hybrid live in focused modules; imports
from this module remain stable for UI/tests.

Concept Recovery Ladder (US-20.1 adjunct): когда сигнал ``quiz_failed`` ведёт
в ``quiz_recovery_tutor``, локальный режим первого шага — мягкая «подсказка»
(``qa_continue``) с лестничными secondary; шаг задаёт вызывающий код
(например, ``st.session_state`` / blob из ``pipeline_steps``).
"""
from __future__ import annotations

from typing import Any, Literal

from app.smart_study_evidence import (
    EvidenceItem,
    build_smart_study_evidence_items,
    build_smart_study_evidence_ledger_lines,
    finalize_smart_study_confidence_ledger_lines,
)
from app.smart_study_recommendation import (
    SmartStudyPrimaryNav,
    SmartStudyRecommendation,
    SmartStudyRouterHintKind,
    SmartStudySecondaryAction,
    _build_smart_study_recommendation_rules,
    apply_smart_study_steering_preference,
    apply_source_coverage_route_guard,
    smart_study_contrastive_explanation,
    smart_study_why_not_others_ru,
)
from app.smart_study_recovery_ladder import (
    apply_concept_recovery_ladder_overlay as _apply_concept_recovery_ladder_overlay,
    concept_recovery_resume_v1,
    ladder_step_from_resume_v1,
    normalize_concept_recovery_ladder_step,
)
from app.smart_study_ssr_ml import _apply_ssr_ml_hybrid_if_enabled
from app.ssr_feedback_collection import weak_concept_sha256
from app.ssr_misroute_policy import apply_ssr_misroute_policy_if_enabled


def build_smart_study_recommendation(
    *,
    surface: Literal["home", "adaptive_plan", "tutor_chat", "flashcards_hub"],
    flashcard_due_n: int = 0,
    sm2_due_n: int = 0,
    quiz_feedback_status: str | None = None,
    has_tutor_resume: bool = False,
    tutor_topic: str | None = None,
    has_last_answer_qa: bool = False,
    has_reading_resume: bool = False,
    first_weak_concept: str | None = None,
    plan_primary_block: dict[str, Any] | None = None,
    ml_feature_profile: dict[str, Any] | None = None,
    retrieval_confidence: str | float | None = None,
    source_evidence_count: int | None = None,
    concept_recovery_ladder_step: int | None = None,
    concept_recovery_ladder_enabled: bool = True,
) -> SmartStudyRecommendation:
    """Rule-baseline SSR plus optional misroute policy tie-break and ML rerank.

Misroute policy runs after rule cascade and before ML hybrid; UI steering preference
(``apply_smart_study_steering_preference``) still applies later in the card layer.
"""
    rule = _build_smart_study_recommendation_rules(
        surface=surface,
        flashcard_due_n=flashcard_due_n,
        sm2_due_n=sm2_due_n,
        quiz_feedback_status=quiz_feedback_status,
        has_tutor_resume=has_tutor_resume,
        tutor_topic=tutor_topic,
        has_last_answer_qa=has_last_answer_qa,
        has_reading_resume=has_reading_resume,
        first_weak_concept=first_weak_concept,
        plan_primary_block=plan_primary_block,
    )
    rule = apply_ssr_misroute_policy_if_enabled(
        rule,
        weak_concept_sha256=weak_concept_sha256(first_weak_concept),
        first_weak_concept=first_weak_concept,
    )
    hybrid = _apply_ssr_ml_hybrid_if_enabled(
        rule,
        ml_feature_profile=ml_feature_profile,
        surface=surface,
        flashcard_due_n=flashcard_due_n,
        sm2_due_n=sm2_due_n,
        quiz_feedback_status=quiz_feedback_status,
        has_tutor_resume=has_tutor_resume,
        tutor_topic=tutor_topic,
        has_last_answer_qa=has_last_answer_qa,
        has_reading_resume=has_reading_resume,
        first_weak_concept=first_weak_concept,
        plan_primary_block=plan_primary_block,
    )
    guarded = apply_source_coverage_route_guard(
        hybrid,
        retrieval_confidence=retrieval_confidence,
        source_evidence_count=source_evidence_count,
    )
    return _apply_concept_recovery_ladder_overlay(
        guarded,
        quiz_feedback_status=quiz_feedback_status,
        concept_recovery_ladder_step=concept_recovery_ladder_step,
        concept_recovery_ladder_enabled=concept_recovery_ladder_enabled,
        tutor_topic=tutor_topic,
    )


__all__ = [
    "EvidenceItem",
    "SmartStudyPrimaryNav",
    "SmartStudyRecommendation",
    "SmartStudyRouterHintKind",
    "SmartStudySecondaryAction",
    "_build_smart_study_recommendation_rules",
    "apply_smart_study_steering_preference",
    "normalize_concept_recovery_ladder_step",
    "concept_recovery_resume_v1",
    "ladder_step_from_resume_v1",
    "build_smart_study_evidence_items",
    "build_smart_study_evidence_ledger_lines",
    "finalize_smart_study_confidence_ledger_lines",
    "build_smart_study_recommendation",
    "smart_study_contrastive_explanation",
    "smart_study_why_not_others_ru",
    "apply_source_coverage_route_guard",
]
