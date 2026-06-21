"""Public facade for home resume cards.

Implementation is split across focused modules; this file preserves the legacy
``app.ui.resume_cards`` import surface used by UI code and tests.
"""
from __future__ import annotations

import sys
from types import ModuleType

import streamlit as st

from app import user_state
from app.due_queue_display import (
    DUE_QUEUE_OVERFLOW_THRESHOLD,
    DUE_QUEUE_TOP_LIMIT,
    due_queue_overflow_caption,
    due_queue_preview_caption,
    is_soft_recovery_overflow,
)
from app.knowledge_service import get_active_knowledge_graph
from app.learner_state_scope import count_due_reviews_for_kg, filter_due_reviews_for_kg
from app.ui import resume_cards_due as _due
from app.ui import resume_cards_smart_study as _smart
from app.ui import resume_cards_tutor as _tutor
from app.ui.index_labels import index_version_label
from app.ui.resume_cards_due import (
    _concepts_with_recent_quiz_miss,
    _due_queue_overflow_text,
    _due_queue_preview_rows,
    _due_queue_preview_text,
    _due_reason,
    _sm2_due_explanation,
    render_due_flashcards_card,
    render_due_reviews_card,
    spaced_due_priority_label,
)
from app.ui.resume_cards_smart_study import (
    SmartStudyRouterSessionContext,
    _maybe_emit_ssr_quiet_styles,
    _quiz_feedback_status_from_tutor_snap,
    _render_ssr_outcome_receipt_if_needed,
    _ssr_quiet_pref_enabled,
    _ssr_quiet_stylesheet_markup,
    build_ssr_outcome_metric_dict_from_ctx,
    build_ssr_outcome_metric_dict_live,
    compute_ssr_outcome_receipt_lines,
    gather_smart_study_router_session_context,
    render_smart_study_router_for_progress_tab,
    render_smart_study_router_strip_from_session_context,
    render_smart_study_steering_controls,
    render_ssr_quiet_mode_toggle,
    resolve_tutor_resume_for_home,
    store_ssr_outcome_baseline_from_primary_rec,
    store_ssr_outcome_baseline_from_secondary,
)
from app.ui.resume_cards_tutor import (
    _enrich_resume_recommended_next_with_orchestration,
    _render_tutor_resume_secondary_only,
    persist_tutor_resume_after_tutor_answer,
    recommended_next_from_tutor_decision,
    render_continue_empty_card,
    render_home_continue_unified,
    render_reading_resume_card,
    render_resume_card,
    render_resume_cards,
    render_tutor_learning_resume_card,
    topic_id_from_resume,
)

_PATCH_TARGETS = (_due, _smart, _tutor)


class _ResumeCardsFacade(ModuleType):
    """Propagate legacy monkeypatches to split implementation modules."""

    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        for module in _PATCH_TARGETS:
            if hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _ResumeCardsFacade

__all__ = [
    "DUE_QUEUE_OVERFLOW_THRESHOLD",
    "DUE_QUEUE_TOP_LIMIT",
    "SmartStudyRouterSessionContext",
    "due_queue_overflow_caption",
    "due_queue_preview_caption",
    "is_soft_recovery_overflow",
    "build_ssr_outcome_metric_dict_from_ctx",
    "build_ssr_outcome_metric_dict_live",
    "compute_ssr_outcome_receipt_lines",
    "gather_smart_study_router_session_context",
    "persist_tutor_resume_after_tutor_answer",
    "recommended_next_from_tutor_decision",
    "render_continue_empty_card",
    "render_due_flashcards_card",
    "render_due_reviews_card",
    "render_home_continue_unified",
    "render_reading_resume_card",
    "render_resume_card",
    "render_resume_cards",
    "render_smart_study_router_for_progress_tab",
    "render_smart_study_router_strip_from_session_context",
    "render_smart_study_steering_controls",
    "render_ssr_quiet_mode_toggle",
    "render_tutor_learning_resume_card",
    "resolve_tutor_resume_for_home",
    "spaced_due_priority_label",
    "store_ssr_outcome_baseline_from_primary_rec",
    "store_ssr_outcome_baseline_from_secondary",
    "topic_id_from_resume",
]
