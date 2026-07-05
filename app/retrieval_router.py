from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from app.config import KNOWN_PROFILES, RAG_PROFILE_DEFAULTS
from app.models import PipelineOverrides, QueryContext, RagProfile, RetrievalRoutingDecision, QueryOptions
from app.rag_runtime_preferences import effective_retrieval_settings, effective_settings

LOW_CONFIDENCE_ROUTE_THRESHOLD = 0.5


def get_rag_profile(name: str) -> RagProfile:
    profile_name = (name or "fast").strip().lower()
    if profile_name not in KNOWN_PROFILES:
        profile_name = "quality"
    data = RAG_PROFILE_DEFAULTS[profile_name]
    return RagProfile(name=profile_name, **data)


@dataclass(frozen=True)
class RagProfileResolution:
    """Статическая фаза A1 ADR‑021a: метка профиля → эффективный ключ профиля (без graph gate)."""

    selected_profile_key: str
    effective_profile_key: str
    manual_override: bool
    profile_resolved_from: str
    routing_fallback_reason: str | None


def resolve_rag_profile_for_pipeline(
    ctx: QueryContext,
    options: QueryOptions,
    overrides: Optional[PipelineOverrides] = None,
) -> RagProfileResolution:
    """Profile resolver: request/settings → ключи профилей + low-confidence policy.

    Не трогает ``QueryContext.trace`` (наблюдаемость — в фазе router ниже).
    """
    requested_profile = (
        (overrides.rag_profile if overrides else None)
        or options.rag_profile
        or effective_retrieval_settings().rag_profile
        or "fast"
    )
    selected_profile_key = str(requested_profile).strip().lower() or "fast"
    manual_override = bool((overrides and overrides.rag_profile) or options.rag_profile)
    profile_resolved_from = "request" if manual_override else "settings"
    effective_profile_key = selected_profile_key
    routing_fallback_reason: str | None = None

    confidence = ctx.classify_confidence
    if not manual_override and confidence < LOW_CONFIDENCE_ROUTE_THRESHOLD:
        effective_profile_key = "quality"
        profile_resolved_from = "rule"
        routing_fallback_reason = "low_confidence"

    return RagProfileResolution(
        selected_profile_key=selected_profile_key,
        effective_profile_key=effective_profile_key,
        manual_override=manual_override,
        profile_resolved_from=profile_resolved_from,
        routing_fallback_reason=routing_fallback_reason,
    )


def _profile_deadline_exceeded(ctx: QueryContext) -> bool:
    if ctx.trace.get("profile_deadline_exceeded"):
        return True
    meta = ctx.metadata if isinstance(ctx.metadata, dict) else {}
    return bool(meta.get("profile_deadline_exceeded"))


def build_retrieval_routing_decision(
    ctx: QueryContext,
    resolution: RagProfileResolution,
) -> RetrievalRoutingDecision:
    """Retrieval router: hydrate RagProfile, graph gate, упаковка ``RetrievalRoutingDecision``."""
    manual = resolution.manual_override
    effective_key = resolution.effective_profile_key
    fallback_reason = resolution.routing_fallback_reason
    signals: dict[str, object] = {
        "effective_query_source": ctx.effective_query_source,
        "retrieval_strategy_before_routing": ctx.retrieval_strategy,
    }

    from app.course_cache import resolve_active_generation_uplift_prerequisites
    from app.metrics_slo import (
        load_graph_route_demotion_state,
        record_route_demotion_skipped_event,
    )

    demotion_state = load_graph_route_demotion_state()
    if demotion_state.get("corrupt"):
        signals["demotion_state_corrupt"] = True

    demoted = bool(demotion_state.get("demoted"))

    if _profile_deadline_exceeded(ctx) and not manual:
        effective_key = "quality"
        fallback_reason = "profile_deadline_exceeded"

    if demoted and not manual:
        effective_key = "quality"
        fallback_reason = "graph_no_uplift_below_delta"
    elif demoted and manual:
        record_route_demotion_skipped_event(
            details={
                "selected_profile": resolution.selected_profile_key,
                "demotion_state_path": demotion_state.get("path"),
            }
        )

    selected = get_rag_profile(resolution.selected_profile_key)
    effective = get_rag_profile(effective_key)

    if not manual and effective.graph_augmented:
        prereqs = resolve_active_generation_uplift_prerequisites()
        if not prereqs.get("uplift_prerequisites_met"):
            effective_key = "quality"
            effective = get_rag_profile(effective_key)
            fallback_reason = "uplift_gate_blocked"
            signals["uplift_prerequisites"] = {
                "gate_passed": prereqs.get("gate_passed"),
                "stale_binding": prereqs.get("stale_binding"),
                "stale_binding_reason": prereqs.get("stale_binding_reason"),
                "generation_id": prereqs.get("generation_id"),
            }

    graph_requested = effective.graph_augmented
    graph_enabled = bool(effective_settings().enable_graph_augmented_retrieval)
    effective_graph = graph_requested and graph_enabled
    if graph_requested and not effective_graph:
        fallback_reason = fallback_reason or "graph_augmented_disabled"

    return RetrievalRoutingDecision(
        selected_profile=selected.name,
        effective_profile=effective.name,
        selected_retrieval_mode=selected.retrieval_mode,
        effective_retrieval_mode=effective.retrieval_mode,
        graph_augmented_requested=graph_requested,
        effective_graph_augmented=effective_graph,
        fallback_reason=fallback_reason,
        profile_resolved_from=resolution.profile_resolved_from,
        manual_override=manual,
        classify_query_type=ctx.query_type,
        classify_confidence=ctx.classify_confidence,
        classify_method=ctx.classify_method,
        signals=signals,
    )


def resolve_retrieval_routing(
    ctx: QueryContext,
    options: QueryOptions,
    overrides: Optional[PipelineOverrides] = None,
) -> PipelineOverrides:
    resolution = resolve_rag_profile_for_pipeline(ctx, options, overrides)
    decision = build_retrieval_routing_decision(ctx, resolution)
    ctx.trace["retrieval_routing"] = decision.model_dump()

    base = overrides or PipelineOverrides()
    # Не записываем retrieval_mode из профиля в overrides: иначе _maybe_boost_first_turn_hybrid
    # (US-3.4) воспринимает его как явный пользовательский override и блокирует boost.
    # Режим по профилю выбирает resolve_retrieval_strategy по rag_profile.
    return replace(
        base,
        rag_profile=decision.effective_profile,
    )
