"""
Tutor context initialization and answer contract normalization.
Extracted from query_service.py to reduce god-module size (arch-cleanup-e30).
"""
import logging
from typing import Any

from app.logging_config import log_event
from app.models import QueryContext, QueryOptions


def _normalize_string_list(values: Any) -> list[str]:
    return [str(item).strip() for item in (values or []) if str(item).strip()]


def _build_tutor_payload(
    *,
    tutor_teaching: dict[str, Any] | None,
    tutor_decision: dict[str, Any] | None,
    auto_quiz_payload: dict[str, Any] | None,
    inline_quiz: list[dict[str, Any]] | None,
    socratic_followup: dict[str, Any] | None,
    learner_profile: dict[str, Any] | None,
    tutor_cycle: dict[str, Any] | None = None,
    orchestration_state: dict[str, Any] | None = None,
    socratic: dict[str, Any] | None = None,
    tutor_orchestration_pipeline: dict[str, Any] | None = None,
    tutor_pipeline: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not any(
        [
            tutor_teaching,
            tutor_decision,
            auto_quiz_payload,
            inline_quiz,
            socratic_followup,
            learner_profile,
            tutor_cycle,
            orchestration_state,
            socratic,
            tutor_orchestration_pipeline,
            tutor_pipeline,
        ]
    ):
        return None
    out: dict[str, Any] = {
        "teaching": tutor_teaching,
        "decision": tutor_decision,
        "auto_quiz": auto_quiz_payload,
        "inline_quiz": inline_quiz or [],
        "socratic_followup": socratic_followup,
        "learner_profile": learner_profile,
    }
    if tutor_cycle:
        out["tutor_cycle"] = tutor_cycle
    if orchestration_state:
        out["orchestration_state"] = orchestration_state
        _enrich_tutor_payload_orchestration_state_scalars(out, orchestration_state)
    if socratic:
        out["socratic"] = socratic
    if tutor_orchestration_pipeline:
        out["tutor_orchestration_pipeline"] = tutor_orchestration_pipeline
        _enrich_tutor_payload_pipeline_scalars(out, tutor_orchestration_pipeline)
    if tutor_pipeline:
        out["tutor_pipeline"] = tutor_pipeline
    return out


def _enrich_tutor_payload_pipeline_scalars(
    payload: dict[str, Any], tutor_orchestration_pipeline: dict[str, Any]
) -> None:
    """Копирует ключевые поля pipeline в верхний уровень tutor payload (typed API / UI)."""
    pipe = tutor_orchestration_pipeline
    ph = str(pipe.get("phase") or "").strip()
    if ph:
        payload["orchestration_phase"] = ph
    ds = str(pipe.get("decision_source") or "").strip()
    if ds:
        payload["orchestration_decision_source"] = ds
    sa = str(pipe.get("selected_agent") or "").strip()
    if sa:
        payload["selected_agent"] = sa
    if "should_trigger_microquiz" in pipe:
        payload["should_trigger_microquiz"] = bool(pipe.get("should_trigger_microquiz"))
    if "policy_clamped" in pipe:
        payload["policy_clamped"] = bool(pipe.get("policy_clamped"))
    raw_reasons = pipe.get("policy_clamp_reasons")
    if isinstance(raw_reasons, list) and raw_reasons:
        payload["policy_clamp_reasons"] = [
            str(x).strip() for x in raw_reasons if str(x).strip()
        ]


def _enrich_tutor_payload_orchestration_state_scalars(
    payload: dict[str, Any], orchestration_state: dict[str, Any]
) -> None:
    """Фоллбек на typed orchestration_state, если pipeline snapshot не передан."""
    st = orchestration_state if isinstance(orchestration_state, dict) else {}
    ph = str(st.get("orchestration_phase") or "").strip()
    if ph:
        payload["orchestration_phase"] = ph
    ds = str(st.get("orchestration_decision_source") or "").strip()
    if ds:
        payload["orchestration_decision_source"] = ds
    sa = str(st.get("selected_agent") or "").strip()
    if sa:
        payload["selected_agent"] = sa
    if "should_trigger_microquiz" in st:
        payload["should_trigger_microquiz"] = bool(st.get("should_trigger_microquiz"))
    if "policy_clamped" in st:
        payload["policy_clamped"] = bool(st.get("policy_clamped"))
    raw_reasons = st.get("policy_clamp_reasons")
    if isinstance(raw_reasons, list) and raw_reasons:
        payload["policy_clamp_reasons"] = [
            str(x).strip() for x in raw_reasons if str(x).strip()
        ]


def _resolve_mode_aware_tutor_next_step(
    *,
    tutor_teaching: dict[str, Any] | None,
    tutor_decision: dict[str, Any] | None,
    learner_profile: dict[str, Any] | None,
    query_context: QueryContext | None,
) -> tuple[str, str, list[str]]:
    teaching = tutor_teaching if isinstance(tutor_teaching, dict) else {}
    decision = tutor_decision if isinstance(tutor_decision, dict) else {}
    profile = learner_profile if isinstance(learner_profile, dict) else {}
    decision_action = decision.get("action") if isinstance(decision.get("action"), dict) else {}

    explicit_action = str(teaching.get("next_action") or "").strip()
    explicit_reason = str(teaching.get("next_action_reason") or "").strip()
    explicit_ctas = _normalize_string_list(teaching.get("suggested_ctas"))

    fallback_action = str(decision_action.get("next_action") or "").strip()
    fallback_reason = str(decision_action.get("next_action_reason") or "").strip()
    fallback_ctas = _normalize_string_list(decision_action.get("suggested_ctas"))

    route = str(decision.get("route") or profile.get("route") or "").strip().lower() or None
    current_topic = (
        str(profile.get("focus_topic") or decision.get("focus_topic") or "").strip() or "Общая_тема"
    )
    due_review_preview = _normalize_string_list(
        profile.get("due_review_preview") or decision.get("due_review_preview")
    )
    learned_concepts: list[str] = []
    if query_context is not None:
        learned_concepts = _normalize_string_list((query_context.metadata or {}).get("learned_concepts"))

    from app.knowledge_graph import knowledge_graph

    graph_recommendation = knowledge_graph.recommend_tutor_next_step(
        current_concept=current_topic,
        learned_concepts=learned_concepts,
        route=route,
        due_review_preview=due_review_preview,
    )
    graph_action = str(graph_recommendation.get("next_action") or "").strip()
    graph_reason = str(graph_recommendation.get("next_action_reason") or "").strip()
    graph_ctas = _normalize_string_list(graph_recommendation.get("suggested_ctas"))

    next_action = explicit_action or graph_action or fallback_action
    if explicit_reason:
        next_action_reason = explicit_reason
    elif next_action and next_action == graph_action and graph_reason:
        next_action_reason = graph_reason
    else:
        next_action_reason = fallback_reason or graph_reason

    suggested_ctas = explicit_ctas or graph_ctas or fallback_ctas
    return next_action, next_action_reason, suggested_ctas


def _normalize_tutor_answer_contract(
    *,
    answer_text: str | None = None,
    tutor_teaching: dict[str, Any] | None,
    tutor_decision: dict[str, Any] | None,
    auto_quiz_payload: dict[str, Any] | None,
    inline_quiz: list[dict[str, Any]] | None,
    socratic_followup: dict[str, Any] | None,
    learner_profile: dict[str, Any] | None,
    query_context: QueryContext | None = None,
) -> dict[str, Any] | None:
    teaching = tutor_teaching if isinstance(tutor_teaching, dict) else {}
    decision = tutor_decision if isinstance(tutor_decision, dict) else {}
    if not any([teaching, decision, auto_quiz_payload, inline_quiz, socratic_followup, learner_profile]):
        return None

    check_question = str(teaching.get("socratic_check") or "").strip()
    if not check_question and isinstance(socratic_followup, dict):
        check_question = str(socratic_followup.get("question") or "").strip()

    next_action, next_action_reason, normalized_ctas = _resolve_mode_aware_tutor_next_step(
        tutor_teaching=teaching,
        tutor_decision=decision,
        learner_profile=learner_profile,
        query_context=query_context,
    )

    understanding_state = teaching.get("understanding_state")
    if not isinstance(understanding_state, dict):
        understanding_state = {
            "what_you_understood": "",
            "risk_gaps": "",
            "what_to_do_now": next_action,
        }
    elif not str(understanding_state.get("what_to_do_now") or "").strip():
        understanding_state = {
            **understanding_state,
            "what_to_do_now": next_action,
        }

    trust_signals = teaching.get("trust_signals")
    if not isinstance(trust_signals, dict):
        trust_signals = {
            "sources_used": None,
            "confidence": None,
            "coverage_warning": None,
        }

    return {
        "contract_version": 1,
        "answer_kind": "tutor_teaching_step",
        "teaching_summary": str(teaching.get("teaching_summary") or answer_text or "").strip(),
        "check_question": check_question or None,
        "next_action": next_action or None,
        "next_action_reason": next_action_reason or None,
        "suggested_ctas": normalized_ctas,
        "understanding_state": understanding_state,
        "depth_level": str(teaching.get("depth_level") or "").strip() or None,
        "trust_signals": trust_signals,
        "inline_quiz": inline_quiz or [],
        "auto_quiz": auto_quiz_payload,
        "learner_profile": learner_profile if isinstance(learner_profile, dict) else None,
        "route": str(decision.get("route") or "").strip() or None,
        "recommended_quiz_topic": str(decision.get("recommended_quiz_topic") or "").strip() or None,
    }


def _initialize_tutor_context(ctx: QueryContext, options: QueryOptions) -> None:
    """Инициализация метаданных и состояния для режима Tutor."""
    from app.quiz_adaptive import get_recommended_difficulty
    from app.tutor_orchestrator import build_tutor_session_state
    from app.tutor_prompts import select_socratic_followup_type
    from app.user_state import get_tutor_learner_profile

    concept_key = (options.topic or options.logical_folder or "").strip() or "general"
    ctx.metadata["quiz_adaptive_concept"] = concept_key
    ctx.metadata["quiz_difficulty"] = get_recommended_difficulty(concept_key)
    ctx.metadata["socratic_type"] = select_socratic_followup_type(
        ctx.query_type,
        len(ctx.conversation_history),
    )
    _lg = (getattr(options, "tutor_learning_goal", None) or "understand_topic").strip()
    if _lg not in ("understand_topic", "exam_prep", "solve_homework"):
        _lg = "understand_topic"
    ctx.metadata["learning_goal"] = _lg
    _qlm = (getattr(options, "quiz_learning_mode", None) or "").strip().lower()
    if _qlm and _qlm not in ("auto", "none"):
        ctx.metadata["quiz_learning_mode"] = _qlm
    _ad = (getattr(options, "tutor_answer_depth", None) or "examples").strip()
    if _ad not in ("short", "examples", "deep"):
        _ad = "examples"
    ctx.metadata["answer_depth"] = _ad
    _ps = (getattr(options, "tutor_preferred_style", None) or "").strip()
    if not _ps:
        from app.user_state import get_preferred_style

        _ps = get_preferred_style()
    if _ps not in ("balanced", "examples", "theory", "practice"):
        from app.user_state import get_preferred_style

        _ps = get_preferred_style()
    ctx.metadata["preferred_style"] = _ps

    from app.quiz_service import topic_from_last_user_message

    ctx.metadata["current_topic"] = (
        topic_from_last_user_message(ctx.conversation_history)
        or (options.topic or options.logical_folder or "").strip()
        or "общая"
    )
    _tm = (getattr(options, "tutor_mastery_level", None) or "intermediate").strip()
    if _tm not in ("beginner", "intermediate", "advanced"):
        _tm = "intermediate"
    ctx.metadata["mastery_level"] = _tm
    _ep = (getattr(options, "tutor_entrypoint", None) or "").strip()
    if _ep:
        ctx.metadata["tutor_entrypoint"] = _ep
    persisted_profile = get_tutor_learner_profile()
    orchestration = build_tutor_session_state(
        current_topic=str(ctx.metadata.get("current_topic") or concept_key),
        mastery_level=_tm,
        preferred_style=_ps,
        learning_goal=_lg,
        quiz_difficulty=str(ctx.metadata.get("quiz_difficulty") or "recognition"),
        persisted_profile=persisted_profile,
        tutor_goal_subtopic=getattr(options, "tutor_goal_subtopic", None),
        tutor_goal_target_level=getattr(options, "tutor_goal_target_level", None),
        tutor_goal_desired_outcome=getattr(options, "tutor_goal_desired_outcome", None),
        tutor_goal_time_budget_min=getattr(options, "tutor_goal_time_budget_min", None),
    )
    orchestration["persisted_learner_profile"] = persisted_profile
    ctx.metadata.update(orchestration)
    learner_profile = orchestration.get("learner_profile")
    if isinstance(learner_profile, dict):
        from app.learner_model_service import merge_personalized_into_learner_profile

        learner_profile = merge_personalized_into_learner_profile(
            learner_profile,
            user_id="local",
            session_id=getattr(options, "session_id", None),
        )
        try:
            from app.learning_plan_service import get_saved_adaptive_daily_plan

            _adp_saved = get_saved_adaptive_daily_plan()
            if _adp_saved:
                learner_profile = {**learner_profile, "adaptive_daily_plan": _adp_saved}
                ctx.metadata["daily_plan"] = _adp_saved
        except Exception as e:
            log_event(
                logging.getLogger(__name__),
                logging.WARNING,
                "tutor_adaptive_daily_plan_merge_failed",
                error=str(e),
            )
        ctx.metadata["learner_profile"] = learner_profile
        ctx.metadata["cognitive_load"] = learner_profile.get("cognitive_load")
        ctx.metadata["emotional_state"] = learner_profile.get("emotional_state")
        ctx.metadata["optimal_depth"] = learner_profile.get("optimal_depth")
        ctx.metadata["orchestrator_route"] = learner_profile.get("route")
        ctx.metadata["orchestrator_quiz_topic"] = learner_profile.get(
            "recommended_quiz_topic"
        )
    from app.pipeline_factory import build_tutor_pipeline
    from app.pipeline_steps import run_step_safe

    ctx.trace.setdefault("tutor_pipeline", [])
    for step in build_tutor_pipeline():
        ctx = run_step_safe(step, ctx)


def _apply_tutor_context_fallback(ctx: QueryContext, options: QueryOptions, reason: str) -> None:
    concept_key = (options.topic or options.logical_folder or "").strip() or "general"
    ctx.metadata.setdefault("quiz_adaptive_concept", concept_key)
    ctx.metadata.setdefault("quiz_difficulty", "recognition")
    ctx.metadata.setdefault("socratic_type", "probing")
    ctx.metadata.setdefault("learning_goal", "understand_topic")
    ctx.metadata.setdefault("answer_depth", "examples")
    ctx.metadata.setdefault("preferred_style", "balanced")
    ctx.metadata.setdefault("current_topic", (options.topic or options.logical_folder or "").strip() or "общая")
    ctx.metadata.setdefault("mastery_level", "intermediate")
    ctx.metadata.setdefault(
        "learner_profile",
        {
            "focus_topic": ctx.metadata["current_topic"],
            "mastery_level": ctx.metadata["mastery_level"],
            "preferred_style": ctx.metadata["preferred_style"],
            "route": "continue",
        },
    )
    ctx.trace["tutor_context"] = "fallback"
    ctx.trace["tutor_context_error"] = reason
