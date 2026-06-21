"""
Composable pipeline step modules (ADR-010, Iteration 12).

Each step: process(ctx: QueryContext) -> QueryContext.
Unified run_step_safe wrapper handles try/fallback/trace/metrics.

Порядок стадий до retrieval: classify → condense → rewrite — см.
``app.pipeline_runner.run_pipeline`` (константа ``_PRE_RETRIEVAL``).
Отдельных модулей ``classify_step.py`` / ``retrieval_step.py`` в репозитории нет:
retrieve/rerank/generate вызываются из ``query_service`` / ``retrieval``, не из этого файла.
RAG-профиль и запись ``retrieval_routing`` в trace — см. ``app.retrieval_router`` (ADR‑021a A1), не здесь.

Tutor 19.4 (после заполнения ``ctx.metadata`` learner_profile в ``query_service``):
``orchestrate_pedagogical_action_step`` → ``execute_specialized_agent_step`` →
``self_correction_and_compose_step`` — см. ``app.pipeline_factory.build_tutor_pipeline``.
Специализированный «агент» в RAG-режиме воплощён в ``build_tutor_rag_prompt_with_quiz_difficulty`` + metadata;
отдельный LLM-вызов на каждый под-агент не делается (избегаем дублирования и стоимости).
"""

import json
import logging
import time
from typing import Any, Callable, Optional

from app.config import get_settings
from app.llm_resilience import complete_with_resilience
from app.logging_config import log_event, setup_logging
from app.models import QueryContext
from app.prompts import (
    CLASSIFY_SYSTEM_PROMPT,
    REWRITE_SYSTEM_PROMPT,
    SUBQUESTION_SYSTEM_PROMPT,
    select_prompt_id,
)
from app.query_routing import KEYWORD_QUERY, detect_extended_query_type, detect_query_type
from app.usage_cost import estimate_cost_usd, extract_token_usage, merge_token_usage

logger = setup_logging()

_STRATEGY_BY_TYPE = {
    "qa": "default",
    "keyword": "bm25_only",
    "overview": "doc_then_chunk",
    "synthesis": "doc_then_chunk",
    "learning_plan": "default",
}

VALID_QUERY_TYPES = frozenset(_STRATEGY_BY_TYPE.keys())


def run_step_safe(
    step_fn: Callable[[QueryContext], QueryContext],
    ctx: QueryContext,
    fallback_fn: Optional[Callable[[QueryContext], QueryContext]] = None,
) -> QueryContext:
    """Unified stage wrapper: try -> fallback -> trace -> metrics."""
    step_name = step_fn.__name__
    start = time.perf_counter()
    try:
        ctx = step_fn(ctx)
        ctx.trace[f"{step_name}_ms"] = round((time.perf_counter() - start) * 1000, 1)
        return ctx
    except Exception as e:  # noqa: BLE001 - pipeline boundary must trace and degrade through fallback.
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        log_event(
            logger,
            logging.WARNING,
            "pipeline_step_failed",
            step_name=step_name,
            elapsed_ms=elapsed,
            error=str(e),
            fallback_used=bool(fallback_fn),
        )
        ctx.trace[f"{step_name}_error"] = str(e)
        ctx.trace[f"{step_name}_ms"] = elapsed
        ctx.trace.setdefault("pipeline_step_failures", []).append(
            {
                "step": step_name,
                "error": str(e),
                "fallback_used": bool(fallback_fn),
            }
        )
        if fallback_fn:
            try:
                ctx = fallback_fn(ctx)
                ctx.trace[f"{step_name}_fallback"] = "applied"
                return ctx
            except Exception as fallback_error:  # noqa: BLE001 - failed fallbacks must be traced without breaking optional pipeline stages.
                log_event(
                    logger,
                    logging.WARNING,
                    "pipeline_step_fallback_failed",
                    step_name=step_name,
                    error=str(fallback_error),
                )
                ctx.trace[f"{step_name}_fallback_error"] = str(fallback_error)
                ctx.trace.setdefault("pipeline_step_failures", []).append(
                    {
                        "step": f"{step_name}_fallback",
                        "error": str(fallback_error),
                        "fallback_used": False,
                    }
                )
                return ctx
        return ctx


def _classify_fallback(ctx: QueryContext) -> QueryContext:
    """Safe fallback: classify as qa."""
    ctx.query_type = "qa"
    ctx.classify_confidence = 1.0
    ctx.classify_method = "fallback"
    ctx.prompt_key = select_prompt_id("qa")
    ctx.retrieval_strategy = "default"
    return ctx


def _parse_classifier_response(text: str) -> dict:
    """Parse LLM JSON response, tolerant to markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()
    try:
        result = json.loads(cleaned)
        qtype = str(result.get("type", "qa")).strip().lower()
        confidence = float(result.get("confidence", 0.5))
        if qtype not in VALID_QUERY_TYPES:
            qtype = "qa"
            confidence = min(confidence, 0.5)
        return {"type": qtype, "confidence": confidence}
    except (json.JSONDecodeError, ValueError, TypeError):
        log_event(
            logger,
            logging.WARNING,
            "classifier_response_parse_failed",
            raw_response=text,
        )
        return {"type": "qa", "confidence": 0.3}


def classify_step(ctx: QueryContext) -> QueryContext:
    """MVP classify: heuristic keyword detection + optional LLM classification."""
    settings = get_settings()
    heuristic_type = detect_query_type(ctx.original_question)

    if not settings.enable_classifier:
        if heuristic_type == KEYWORD_QUERY:
            ctx.query_type = "keyword"
            ctx.classify_method = "heuristic"
            ctx.classify_confidence = 1.0
            ctx.prompt_key = select_prompt_id("keyword", retrieval_mode="bm25_only")
            ctx.retrieval_strategy = "bm25_only"
            ctx.trace["classify_heuristic"] = "keyword"
            return ctx
        ext = detect_extended_query_type(ctx.original_question)
        ctx.query_type = ext
        ctx.classify_method = "heuristic"
        ctx.classify_confidence = 1.0
        ctx.prompt_key = select_prompt_id(ext)
        ctx.retrieval_strategy = _STRATEGY_BY_TYPE.get(ext, "default")
        ctx.trace["classify_heuristic"] = ext
        return ctx

    if heuristic_type == KEYWORD_QUERY:
        ctx.query_type = "keyword"
        ctx.classify_method = "heuristic"
        ctx.classify_confidence = 1.0
        ctx.prompt_key = select_prompt_id("keyword", retrieval_mode="bm25_only")
        ctx.retrieval_strategy = "bm25_only"
        ctx.trace["classify_heuristic"] = "keyword"
        return ctx

    from app.provider import get_classifier_llm

    llm = get_classifier_llm()
    response = complete_with_resilience(
        llm,
        f"{CLASSIFY_SYSTEM_PROMPT}\n\nQuestion: {ctx.original_question}",
        stage="classify",
    )
    result = _parse_classifier_response(response.text)
    classify_usage = extract_token_usage(response)

    ctx.query_type = result["type"]
    ctx.classify_confidence = result["confidence"]
    ctx.classify_method = "llm"
    ctx.trace["classify_llm_raw"] = response.text.strip()
    ctx.trace["classify_model"] = settings.classifier_model or settings.llm_model
    if classify_usage:
        ctx.trace["classify_usage"] = classify_usage
        ctx.trace["classify_estimated_cost_usd"] = estimate_cost_usd(
            settings.classifier_model or settings.llm_model,
            classify_usage,
        )

    if ctx.classify_confidence < 0.6:
        ctx.trace["classify_low_confidence_fallback"] = True
        ctx.query_type = "qa"

    ctx.prompt_key = select_prompt_id(ctx.query_type)
    ctx.retrieval_strategy = _STRATEGY_BY_TYPE.get(ctx.query_type, "default")
    return ctx


def rewrite_step(ctx: QueryContext) -> QueryContext:
    """Query rewriting using cheap model. Passthrough when disabled."""
    settings = get_settings()

    if not settings.enable_rewrite:
        ctx.trace["rewrite_enabled"] = False
        return ctx

    from app.provider import get_rewrite_llm

    llm = get_rewrite_llm()
    rewrite_model = settings.rewrite_model or settings.llm_model

    base_question = (
        ctx.metadata.get("condensed_text")
        or ctx.condensed_question
        or ctx.original_question
    )

    response = complete_with_resilience(
        llm,
        f"{REWRITE_SYSTEM_PROMPT}\n\nOriginal question: {base_question}",
        stage="rewrite",
    )
    rewritten = response.text.strip()
    rewrite_usage = extract_token_usage(response)

    if rewritten and rewritten != base_question:
        ctx.rewritten_query = rewritten

    ctx.trace["rewrite_enabled"] = True
    ctx.trace["rewritten_question"] = ctx.rewritten_query
    ctx.trace["rewrite_model"] = rewrite_model

    if ctx.query_type in {"overview", "synthesis"}:
        try:
            subquestion_response = complete_with_resilience(
                llm,
                f"{SUBQUESTION_SYSTEM_PROMPT}\n\nQuestion: {base_question}",
                stage="subquestions",
            )
            subquestion_usage = extract_token_usage(subquestion_response)
            parsed = json.loads(subquestion_response.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
            raw_subquestions = parsed.get("subquestions") or []
            normalized = []
            seen = set()
            for item in raw_subquestions:
                subq = " ".join(str(item).split()).strip()
                if not subq:
                    continue
                key = subq.lower()
                if key in seen:
                    continue
                seen.add(key)
                normalized.append(subq)
            ctx.subquestions = normalized[:5]
            ctx.trace["subquestions"] = ctx.subquestions
            rewrite_usage = merge_token_usage(rewrite_usage, subquestion_usage)
        except Exception as exc:  # noqa: BLE001 - subquestion LLM/JSON failures fall back to rewrite-only context.
            log_event(
                logger,
                logging.WARNING,
                "subquestion_generation_failed",
                error=str(exc),
            )
            ctx.trace["subquestions_error"] = str(exc)

    if rewrite_usage:
        ctx.trace["rewrite_usage"] = rewrite_usage
        ctx.trace["rewrite_estimated_cost_usd"] = estimate_cost_usd(
            rewrite_model,
            rewrite_usage,
        )

    return ctx


# ─────────────────────────────────────────────────────────────
# Tutor 19.4 — шаги после tutor_session_state (вызываются из query_service)
# ─────────────────────────────────────────────────────────────


def orchestrate_pedagogical_action_step(ctx: QueryContext) -> QueryContext:
    """Pedagogical Orchestrator: JSON-решение LLM → metadata (агент, micro-quiz, socratic…)."""
    from app.tutor_orchestrator import (
        apply_pedagogical_orchestrator_to_metadata,
        invoke_pedagogical_orchestrator_llm,
        make_rule_fallback_orchestrator_decision,
    )
    from app.tutor_pipeline_contract import (
        merge_orchestration_pipeline_contract,
        merge_qa_handoff_into_pipeline_metadata,
        record_tutor_pipeline_step,
    )

    opts = ctx.query_options
    if (opts.query_mode or "").strip().lower() != "tutor":
        ctx.trace["orchestrate_pedagogical_action_step"] = "skipped_not_tutor"
        record_tutor_pipeline_step(
            ctx, "orchestrate_pedagogical_action_step", "skipped_not_tutor"
        )
        return ctx
    qh_meta = ctx.metadata.get("qa_handoff_context")
    if isinstance(qh_meta, dict) and qh_meta:
        merge_qa_handoff_into_pipeline_metadata(ctx.metadata, qh_meta)
    if not get_settings().enable_tutor_pedagogical_orchestrator:
        ctx.trace["orchestrate_pedagogical_action_step"] = "skipped_disabled"
        merge_orchestration_pipeline_contract(
            ctx.metadata,
            phase="orchestrate",
            decision_source="disabled",
            selected_agent=None,
            should_trigger_microquiz=None,
        )
        record_tutor_pipeline_step(
            ctx, "orchestrate_pedagogical_action_step", "skipped_disabled"
        )
        return ctx
    learner_profile = ctx.metadata.get("learner_profile")
    if not isinstance(learner_profile, dict):
        ctx.trace["orchestrate_pedagogical_action_step"] = "skipped_no_learner_profile"
        merge_orchestration_pipeline_contract(
            ctx.metadata,
            phase="orchestrate",
            decision_source="skipped_no_learner_profile",
            selected_agent=None,
            should_trigger_microquiz=None,
        )
        record_tutor_pipeline_step(
            ctx,
            "orchestrate_pedagogical_action_step",
            "skipped_no_learner_profile",
        )
        return ctx

    try:
        try:
            from app.knowledge_graph import get_active_knowledge_graph

            active_kg = get_active_knowledge_graph()
        except Exception as _exc:  # noqa: BLE001 - KG lookup is optional context for tutor orchestration.
            logging.getLogger(__name__).debug(
                "! caught exception: %s", _exc
            )
            active_kg = None
        from app.tutor_personalization_policy import (
            apply_orchestrator_policy_clamp,
            attach_personalization_policy_to_learner_profile,
        )

        learner_profile = attach_personalization_policy_to_learner_profile(
            dict(learner_profile)
        )
        learner_profile["orchestrator_clamp_user_message"] = str(
            ctx.original_question or ""
        ).strip()
        hist = getattr(ctx, "conversation_history", None) or []
        learner_profile["orchestrator_prior_assistant_context"] = any(
            str(getattr(m, "role", "") or "").strip().lower() in {"assistant", "model", "ai"}
            for m in hist[-8:]
        )
        ctx.metadata["learner_profile"] = learner_profile

        decision, orch_usage = invoke_pedagogical_orchestrator_llm(
            learner_profile=learner_profile,
            current_user_message=ctx.original_question,
            conversation_history=ctx.conversation_history,
            kg=active_kg,
        )
        decision, clamp_meta = apply_orchestrator_policy_clamp(decision, learner_profile)
        ctx.trace["orchestrator_policy_clamp"] = clamp_meta
        apply_pedagogical_orchestrator_to_metadata(
            ctx, decision, policy_clamp_meta=clamp_meta
        )
        if orch_usage:
            ctx.trace["pedagogical_orchestrator_usage"] = orch_usage
        detail = "rule_fallback" if decision.get("_fallback") else "ok"
        ctx.trace["orchestrate_pedagogical_action_step"] = detail
        record_tutor_pipeline_step(
            ctx, "orchestrate_pedagogical_action_step", detail
        )
    except Exception as e:  # noqa: BLE001 - tutor orchestrator failures use rule fallback metadata.
        log_event(
            logger,
            logging.WARNING,
            "orchestrate_pedagogical_action_step_failed",
            error=str(e),
        )
        ctx.trace["orchestrate_pedagogical_action_step"] = f"error:{e}"
        fb = make_rule_fallback_orchestrator_decision(reason=f"step_exception:{e}")
        apply_pedagogical_orchestrator_to_metadata(ctx, fb)
        record_tutor_pipeline_step(
            ctx,
            "orchestrate_pedagogical_action_step",
            "error_fallback",
            detail=str(e),
        )
    return ctx


def execute_specialized_agent_step(ctx: QueryContext) -> QueryContext:
    """Выбор агента применяется через tutor RAG prompt + metadata (без второго LLM на этом шаге)."""
    from app.tutor_pipeline_contract import (
        merge_orchestration_pipeline_contract,
        record_tutor_pipeline_step,
    )

    if (ctx.query_options.query_mode or "").strip().lower() != "tutor":
        ctx.trace["execute_specialized_agent_step"] = "skipped_not_tutor"
        record_tutor_pipeline_step(
            ctx, "execute_specialized_agent_step", "skipped_not_tutor"
        )
        return ctx
    agent = ctx.metadata.get("orchestrator_selected_agent")
    if not agent:
        ped = ctx.metadata.get("pedagogical_orchestrator")
        if isinstance(ped, dict):
            agent = ped.get("selected_agent")
    ctx.trace["execute_specialized_agent_step"] = {
        "mode": "embedded_in_tutor_rag_prompt",
        "selected_agent": agent,
    }
    merge_orchestration_pipeline_contract(ctx.metadata, phase="rag_prepare")
    record_tutor_pipeline_step(ctx, "execute_specialized_agent_step", "ok")
    return ctx


def self_correction_and_compose_step(ctx: QueryContext) -> QueryContext:
    """Маркер этапа self-correction: фактическая правка — после generation в query_service.

    LLM self-correction по ``SELF_CORRECTION_PROMPT`` не вызывается здесь (pre-retrieval),
    чтобы не плодить лишние вызовы; rule-based ``apply_tutor_self_correction`` — в ``query_service``.
    """
    from app.tutor_pipeline_contract import (
        merge_orchestration_pipeline_contract,
        record_tutor_pipeline_step,
    )

    if (ctx.query_options.query_mode or "").strip().lower() != "tutor":
        ctx.trace["self_correction_and_compose_step"] = "skipped_not_tutor"
        record_tutor_pipeline_step(
            ctx, "self_correction_and_compose_step", "skipped_not_tutor"
        )
        return ctx
    ctx.trace["self_correction_and_compose_step"] = (
        "post_generation_apply_tutor_self_correction_in_query_service"
    )
    merge_orchestration_pipeline_contract(ctx.metadata, phase="pre_generate")
    record_tutor_pipeline_step(ctx, "self_correction_and_compose_step", "scheduled")
    return ctx


# ── SSR Concept Recovery Ladder persistence hooks (resume / metadata fusion) ─

SSR_CONCEPT_RECOVERY_LADDER_KEY_V1 = "ssr_concept_recovery_ladder_v1"


def clear_concept_recovery_ladder_from_metadata(metadata: dict[str, Any]) -> None:
    """Removes ladder resume key and service marks without touching trust/resume/due blocks."""
    metadata.pop(SSR_CONCEPT_RECOVERY_LADDER_KEY_V1, None)
    marks = metadata.get("_ssr_recovery_ladder_marks")
    if isinstance(marks, dict):
        marks.pop("last_resume", None)
        marks.pop("last_touch", None)
        if not marks:
            metadata.pop("_ssr_recovery_ladder_marks", None)


def merge_concept_recovery_ladder_into_metadata(
    metadata: dict[str, Any],
    *,
    ladder_resume: dict[str, Any] | None,
    trace_note: bool = False,
) -> dict[str, Any] | None:
    """Writes ladder resume JSON into learner metadata dict (opaque to pipeline core).

    Returns the stored resume blob for chaining; ``None`` if nothing persisted.
    """
    if ladder_resume is None:
        clear_concept_recovery_ladder_from_metadata(metadata)
        return None
    bucket = metadata.setdefault("_ssr_recovery_ladder_marks", {})
    bucket["last_resume"] = dict(ladder_resume)
    metadata[SSR_CONCEPT_RECOVERY_LADDER_KEY_V1] = dict(ladder_resume)
    if trace_note:
        bucket["last_touch"] = time.time()
    return dict(ladder_resume)


def read_concept_recovery_ladder_resume_v1(metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Reads resume blob merged via ``merge_concept_recovery_ladder_into_metadata``."""
    raw = metadata.get(SSR_CONCEPT_RECOVERY_LADDER_KEY_V1)
    if isinstance(raw, dict) and raw:
        return dict(raw)
    return None


def annotate_trace_with_recovery_ladder(ctx: QueryContext, *, ladder_resume: dict[str, Any] | None) -> None:
    """Lightweight SSR observability hook (optional instrumentation from query_service/UI)."""
    if ladder_resume:
        ctx.trace["ssr_concept_recovery_ladder_resume"] = dict(ladder_resume)
