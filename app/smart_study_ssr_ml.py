"""Optional local ML hybrid layer for Smart Study Router."""
from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Literal

from app.config import get_settings
from app.ssr_ai.fallback import (
    APPLIED,
    EMPTY_PROBABILITIES,
    INFERENCE_EXCEPTION,
    LATENCY_BUDGET,
    LOW_CONFIDENCE,
    NO_ALLOWED_PROBABILITIES,
    RULE_MATCH,
)
from app.smart_study_recommendation import (
    SmartStudyRecommendation,
    _quiz_feedback_failed,
    _ssr_recommendation_for_kind,
)

logger = logging.getLogger(__name__)


_SSR_ML_NO_RULE_OVERRIDE: frozenset[str] = frozenset({"cards_due", "sm2_due", "quiz_failed"})


_ML_PROFILE_KEYS: frozenset[str] = frozenset(
    {
        "time_since_last_review_hours",
        "quiz_score_last_3_avg",
        "concept_difficulty",
        "session_duration_avg_minutes",
        "time_of_day_hour",
        "day_of_week",
        "cards_due_count",
        "sm2_due_count",
        "quiz_failed_recent",
        "session_fatigue",
        "mastery_gap_score",
        "adaptive_plan_backlog_signals",
        "tutor_stub_active",
    }
)


def _ssr_ml_tier_allowed_hints(
    *,
    surface: Literal["home", "adaptive_plan", "tutor_chat", "flashcards_hub"],
    flashcard_due_n: int,
    sm2_due_n: int,
    quiz_feedback_status: str | None,
    has_tutor_resume: bool,
    tutor_topic: str | None,
    has_last_answer_qa: bool,
    has_reading_resume: bool,
    first_weak_concept: str | None,
    plan_primary_block: dict[str, Any] | None,
) -> frozenset[str]:
    """Допустимые hint_kind в текущем ярусе rule-cascade (для ML-маски)."""
    fc = max(0, int(flashcard_due_n))
    due = max(0, int(sm2_due_n))
    out: set[str] = {"safe_default"}
    if fc > 0:
        out.add("cards_due")
        return frozenset(out)
    if due > 0:
        out.add("sm2_due")
        return frozenset(out)
    if _quiz_feedback_failed(quiz_feedback_status):
        out.add("quiz_failed")
        return frozenset(out)
    plan_block = plan_primary_block if isinstance(plan_primary_block, dict) else None
    plan_first = plan_block is not None
    if plan_first:
        out.add("adaptive_plan")
        return frozenset(out)
    topic_t = str(tutor_topic or "").strip() or None
    if has_tutor_resume and topic_t:
        out.add("tutor_resume")
        return frozenset(out)
    if has_last_answer_qa:
        out.add("answer_ready")
        return frozenset(out)
    weak = str(first_weak_concept or "").strip() or None
    if weak or has_reading_resume:
        out.add("mastery_stale")
        return frozenset(out)
    return frozenset(out)


def _ssr_merge_ml_feature_profile(
    ml_profile: dict[str, Any] | None,
    *,
    surface: Literal["home", "adaptive_plan", "tutor_chat", "flashcards_hub"],
    flashcard_due_n: int,
    sm2_due_n: int,
    quiz_feedback_status: str | None,
    has_tutor_resume: bool,
    has_last_answer_qa: bool,
    first_weak_concept: str | None,
    plan_primary_block: dict[str, Any] | None,
) -> dict[str, Any]:
    fc = max(0, int(flashcard_due_n))
    due = max(0, int(sm2_due_n))
    qf = _quiz_feedback_failed(quiz_feedback_status)
    weak = str(first_weak_concept or "").strip() or None
    plan_block = plan_primary_block if isinstance(plan_primary_block, dict) else None
    backlog = 5.0 if plan_block is not None else 0.0
    now = datetime.now(timezone.utc)
    base: dict[str, Any] = {
        "time_since_last_review_hours": 48.0,
        "quiz_score_last_3_avg": 0.72,
        "concept_difficulty": 0.5,
        "session_duration_avg_minutes": 28.0,
        "time_of_day_hour": float(now.hour),
        "day_of_week": float(now.weekday()),
        "cards_due_count": float(fc),
        "sm2_due_count": float(due),
        "quiz_failed_recent": qf,
        "session_fatigue": 0.45,
        "mastery_gap_score": 0.74 if weak else 0.28,
        "adaptive_plan_backlog_signals": backlog,
        "tutor_stub_active": bool(has_tutor_resume),
    }
    if ml_profile:
        for key, val in ml_profile.items():
            if key in _ML_PROFILE_KEYS:
                base[key] = val
    return base


def _apply_ssr_ml_hybrid_if_enabled(
    rule_rec: SmartStudyRecommendation,
    *,
    ml_feature_profile: dict[str, Any] | None,
    surface: Literal["home", "adaptive_plan", "tutor_chat", "flashcards_hub"],
    flashcard_due_n: int,
    sm2_due_n: int,
    quiz_feedback_status: str | None,
    has_tutor_resume: bool,
    tutor_topic: str | None,
    has_last_answer_qa: bool,
    has_reading_resume: bool,
    first_weak_concept: str | None,
    plan_primary_block: dict[str, Any] | None,
) -> SmartStudyRecommendation:
    settings = get_settings()
    
    ml_eligible = getattr(settings, "ssr_ml_rerank_enabled", False)
    if not ml_eligible:
        from app import ssr_ml_monitoring as _ssr_ml_mon
        real_samples = _ssr_ml_mon.get_ssr_ml_real_sample_count()
        threshold = getattr(settings, "ssr_ml_auto_enable_threshold", 1000)
        if real_samples >= threshold:
            variant = _ssr_ml_mon.get_ssr_ml_ab_assignment()
            if variant == "treatment":
                ml_eligible = True

    if not ml_eligible:
        return rule_rec
    if rule_rec.hint_kind in _SSR_ML_NO_RULE_OVERRIDE:
        return rule_rec

    from app import ssr_ml_reranking as _ssr_ml
    from app import ssr_ml_monitoring as _ssr_ml_mon

    allowed = _ssr_ml_tier_allowed_hints(
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
    feats = _ssr_merge_ml_feature_profile(
        ml_feature_profile,
        surface=surface,
        flashcard_due_n=flashcard_due_n,
        sm2_due_n=sm2_due_n,
        quiz_feedback_status=quiz_feedback_status,
        has_tutor_resume=has_tutor_resume,
        has_last_answer_qa=has_last_answer_qa,
        first_weak_concept=first_weak_concept,
        plan_primary_block=plan_primary_block,
    )
    t0 = time.perf_counter()
    try:
        probs = _ssr_ml.predict_hint_probability_map_or_empty(
            feats,
            prior_rule_top_hint_kind=str(rule_rec.hint_kind),
        )
    except Exception:  # noqa: BLE001
        # ML reranking is optional; SSR must keep rule-only behavior on local model issues.
        _ssr_ml_mon.record_ssr_ml_inference(
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            confidence=None,
            fallback=True,
            reason=INFERENCE_EXCEPTION,
        )
        logger.info("ssr_ml_rerank_fallback", extra={"reason": INFERENCE_EXCEPTION})
        return rule_rec
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    budget = float(getattr(settings, "ssr_ml_rerank_latency_budget_ms", 50.0))
    if elapsed_ms > budget:
        _ssr_ml_mon.record_ssr_ml_inference(
            latency_ms=elapsed_ms,
            confidence=None,
            fallback=True,
            reason=LATENCY_BUDGET,
        )
        logger.info(
            "ssr_ml_rerank_fallback",
            extra={"reason": LATENCY_BUDGET, "ms": round(elapsed_ms, 3), "budget_ms": budget},
        )
        return rule_rec
    if not probs:
        _ssr_ml_mon.record_ssr_ml_inference(
            latency_ms=elapsed_ms,
            confidence=None,
            fallback=True,
            reason=EMPTY_PROBABILITIES,
        )
        return rule_rec

    conf_min = float(getattr(settings, "ssr_ml_rerank_confidence_min", 0.35))
    masked: list[tuple[str, float]] = [(h, probs[h]) for h in allowed if h in probs]
    if not masked:
        _ssr_ml_mon.record_ssr_ml_inference(
            latency_ms=elapsed_ms,
            confidence=None,
            fallback=True,
            reason=NO_ALLOWED_PROBABILITIES,
        )
        return rule_rec
    best_h, best_p = max(masked, key=lambda x: x[1])
    if best_p < conf_min:
        _ssr_ml_mon.record_ssr_ml_inference(
            latency_ms=elapsed_ms,
            confidence=best_p,
            fallback=True,
            reason=LOW_CONFIDENCE,
        )
        return rule_rec
    _ssr_ml_mon.record_ssr_ml_inference(
        latency_ms=elapsed_ms,
        confidence=best_p,
        fallback=False,
        reason=APPLIED if best_h != rule_rec.hint_kind else RULE_MATCH,
    )
    if best_h == rule_rec.hint_kind:
        audit = (
            f"SSR ML (forgetting-curve): правило «{rule_rec.hint_kind}» совпало с топом модели "
            f"(p≈{best_p:.2f}, задержка ≈{elapsed_ms:.1f} мс)."
        )
        return replace(rule_rec, ml_audit_ru=audit)
    audit = (
        f"SSR ML (forgetting-curve): гибридный сдвиг {rule_rec.hint_kind} → {best_h} "
        f"(p≈{best_p:.2f}, задержка ≈{elapsed_ms:.1f} мс; rule-baseline сохранён в prior признаках)."
    )
    alt = _ssr_recommendation_for_kind(
        best_h,
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
        ml_audit_ru=audit,
    )
    if alt is None:
        return rule_rec
    why_extra = (
        " Гибридный слой (локальная logistic regression по признакам забывания) сместил приоритет относительно "
        f"чистого rule-ядра; исходное правило было «{rule_rec.hint_kind}», см. строку аудита в леджере."
    )
    if why_extra.strip() not in alt.why_now_ru:
        alt = replace(alt, why_now_ru=alt.why_now_ru + why_extra)
    return alt
