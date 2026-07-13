"""First-session artifact loading and cache helpers for Mission Control.

Extracted from mission_control.py (AR-2026-05-29-004).
"""
from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any, Callable, Final

import streamlit as st

from app.course_cache import (
    course_scope_hash,
    first_session_artifact_is_populated,
    first_session_artifact_path,
    load_first_session_artifact_for_scope,
    resolve_first_session_scope_for_home,
)
from app.config import get_settings
from app.provider import get_e2e_primary_chat_call_count
from app.latency_budget import (
    BudgetMeta,
    budget_meta_to_session_event,
    classify_mission_load_variant,
    with_budget,
)
from app.ui.study_scope import get_active_scope

_FIRST_SESSION_CACHE_KEYS: Final[tuple[str, ...]] = (
    "first_session_artifact_cache",
    "first_session_artifact_scope_hash",
    "first_session_load_status",
    "first_session_course_id",
)


def clear_first_session_session_cache() -> None:
    """Drop parsed first-session cache (scope change / cockpit deactivate)."""
    for key in _FIRST_SESSION_CACHE_KEYS:
        st.session_state.pop(key, None)


def _citation_basename(path: object) -> str:
    raw = str(path or "").strip().replace("\\", "/")
    if not raw:
        return ""
    return PurePosixPath(raw).name or raw


def _apply_latency_budget_session_state(meta: BudgetMeta) -> None:
    st.session_state["latency_budget_last_event"] = budget_meta_to_session_event(meta)
    if meta.event == "surface_breached_soft":
        st.session_state["latency_budget_soft_breach_active"] = True


def _sync_first_session_scope_cache(index_stats: dict | None) -> None:
    scope = resolve_first_session_scope_for_home(
        index_stats=index_stats,
        active_scope=get_active_scope(),
    )
    folder = str((scope or {}).get("folder_rel") or "").strip()
    cached_folder = str(st.session_state.get("first_session_course_id") or "").strip()
    if cached_folder and folder and cached_folder != folder:
        clear_first_session_session_cache()


def _load_first_session_artifact_uncached(
    scope: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    """Disk/cache load path for first-session artifact (no budget wrapper)."""
    folder = str(scope.get("folder_rel") or "").strip()
    paths = scope.get("source_paths") if isinstance(scope.get("source_paths"), list) else []
    current_hash = course_scope_hash(paths) if paths else ""

    cached = st.session_state.get("first_session_artifact_cache")
    cached_hash = str(st.session_state.get("first_session_artifact_scope_hash") or "")
    cached_folder = str(st.session_state.get("first_session_course_id") or "")
    if (
        isinstance(cached, dict)
        and cached_hash == current_hash
        and cached_folder == folder
        and first_session_artifact_is_populated(cached)
    ):
        st.session_state["first_session_load_status"] = "ok"
        return cached, "ok"

    path = first_session_artifact_path(folder)
    if not path.exists():
        st.session_state["first_session_load_status"] = "empty"
        return None, "empty"

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        st.session_state["first_session_load_status"] = "error"
        return None, "error"

    try:
        json.loads(raw)
    except json.JSONDecodeError:
        st.session_state["first_session_load_status"] = "error"
        return None, "error"

    try:
        artifact = load_first_session_artifact_for_scope(scope)
    except Exception as exc:  # noqa: BLE001 - home hero must degrade gracefully.
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("first session load failed: %s", exc)
        st.session_state["first_session_load_status"] = "error"
        return None, "error"

    if not first_session_artifact_is_populated(artifact):
        st.session_state["first_session_load_status"] = "empty"
        return None, "empty"

    st.session_state["first_session_artifact_cache"] = artifact
    st.session_state["first_session_artifact_scope_hash"] = current_hash
    st.session_state["first_session_course_id"] = folder
    st.session_state["first_session_load_status"] = "ok"
    return artifact, "ok"


def load_first_session_artifact_cached_for_scope(
    scope: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str]:
    """Load first-session artifact with session cache; returns (artifact, ok|empty|error)."""
    if not isinstance(scope, dict):
        budget = with_budget(
            "mission_load",
            lambda: (None, "empty"),
            empty_scope=True,
        )
        _apply_latency_budget_session_state(budget.meta)
        return budget.result

    folder = str(scope.get("folder_rel") or "").strip()
    if not folder:
        budget = with_budget(
            "mission_load",
            lambda: (None, "empty"),
            empty_scope=True,
        )
        _apply_latency_budget_session_state(budget.meta)
        return budget.result

    variant = classify_mission_load_variant(scope, st.session_state)
    budget = with_budget(
        "mission_load",
        lambda: _load_first_session_artifact_uncached(scope),
        variant=variant,
    )
    _apply_latency_budget_session_state(budget.meta)
    return budget.result


def render_first_session_block(
    artifact: dict[str, Any],
    *,
    key_prefix: str,
    folder_rel: str,
    navigate_to_question: Callable[[str], None],
    compact: bool = False,
) -> None:
    """Render mission, seed questions, and citations from a first-session artifact."""
    baseline = artifact.get("baseline_mission") if isinstance(artifact.get("baseline_mission"), dict) else {}
    title = str(baseline.get("title") or "").strip()
    primary_cta = str(baseline.get("primary_cta") or "Стартовый вопрос").strip()
    built_at = str(artifact.get("built_at") or "").strip()
    heading = "####" if compact else "###"
    st.markdown(f"{heading} 🎯 {title}")
    st.caption(f"из материалов курса{' · ' + built_at[:10] if built_at else ''}")

    seeds = artifact.get("seed_questions") if isinstance(artifact.get("seed_questions"), list) else []
    first_seed_q = ""
    for index, seed in enumerate(seeds[:3]):
        if not isinstance(seed, dict):
            continue
        question = str(seed.get("q") or "").strip()
        if not question:
            continue
        first_seed_q = first_seed_q or question
        trace = seed.get("retrieval_trace") if isinstance(seed.get("retrieval_trace"), dict) else {}
        source_paths = trace.get("source_paths") if isinstance(trace.get("source_paths"), list) else []
        if st.button(question, key=f"{key_prefix}_seed_{folder_rel}_{index}", type="secondary"):
            navigate_to_question(question)
        cite = _citation_basename(source_paths[0] if source_paths else "")
        if cite:
            st.caption(f"📄 {cite}")
        if seed.get("draft_answer"):
            with st.expander("Черновик ответа", expanded=False):
                st.write(str(seed["draft_answer"]))

    if st.button(primary_cta, key=f"{key_prefix}_primary_cta_{folder_rel}", type="primary"):
        navigate_to_question(first_seed_q or title)


def render_first_session_hero(
    index_stats: dict | None,
    *,
    navigate_to_question: Callable[[str], None],
) -> bool:
    """Render the cached first-session hero for Mission Control."""
    _sync_first_session_scope_cache(index_stats)
    scope = resolve_first_session_scope_for_home(index_stats=index_stats, active_scope=get_active_scope())
    st.markdown(
        '<div data-testid="first-session-hero" class="first-session-hero-shell" '
        'style="min-height:1px" aria-label="First session">&nbsp;</div>',
        unsafe_allow_html=True,
    )
    with st.spinner("Загружаем первый обзор курса…"):
        artifact, load_status = load_first_session_artifact_cached_for_scope(scope)
    st.session_state["first_session_cold_open_done"] = True
    rendered_cta = False
    if load_status == "empty":
        # A2 (wave-onboarding-closure): never promise a build that isn't happening.
        # The First Session Artifact is opt-in (enable_first_session_precompute, off
        # by default), so it is built only when a reindex is actually running AND the
        # precompute tail is enabled. In every other case "готовится" was a false
        # promise — say nothing false; the seed chips below already give the next step.
        precompute_on = bool(get_settings().enable_first_session_precompute)
        reindex_running = bool(st.session_state.get("poll_reindex_status"))
        if precompute_on and reindex_running:
            st.info("Первый обзор курса собирается после индексации — это займёт немного времени.")
        else:
            st.caption("Первый обзор курса пока не собран. Начните с вопроса ниже — ответ появится сразу.")
    elif load_status == "error":
        st.warning("Не удалось прочитать сохранённый обзор курса.")
        st.caption("Показан обычный режим")
    elif load_status == "ok" and isinstance(artifact, dict):
        folder_rel = str(scope.get("folder_rel") or "course") if isinstance(scope, dict) else "course"
        render_first_session_block(
            artifact,
            key_prefix="first_session",
            folder_rel=folder_rel,
            navigate_to_question=navigate_to_question,
        )
        rendered_cta = True
    if get_settings().home_rag_e2e_offline:
        count = get_e2e_primary_chat_call_count()
        st.markdown(
            f'<span data-testid="e2e-primary-chat-call-count" aria-hidden="true">{count}</span>',
            unsafe_allow_html=True,
        )
    return rendered_cta
