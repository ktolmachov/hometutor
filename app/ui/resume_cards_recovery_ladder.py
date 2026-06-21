"""Concept Recovery Ladder UI helpers for Smart Study Router home resume cards.

Extracted from resume_cards_smart_study.py (AR-2026-05-29-002).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st

# US-20.1 v2: concept recovery ladder session ↔ persisted sync (Designer keys).
_CONCEPT_RECOVERY_LADDER_ENABLED_KEY = "concept_recovery_ladder_enabled"
_CONCEPT_RECOVERY_LADDER_STEP_KEY = "concept_recovery_ladder_step"
_CONCEPT_RECOVERY_RESUME_V1_KEY = "concept_recovery_resume_v1"
_CONCEPT_RECOVERY_ANCHOR_TOPIC_KEY = "concept_recovery_anchor_topic"
_CONCEPT_RECOVERY_LADDER_HYDRATING_KEY = "concept_recovery_ladder_hydrating"
_CONCEPT_RECOVERY_LADDER_PERSIST_ERROR_KEY = "concept_recovery_ladder_persist_error"
_CONCEPT_RECOVERY_LADDER_HYDRATED_FLAG = "_concept_recovery_ladder_hydrated_v1"
_LAST_SSR_PRIMARY_NAV_KEY = "_last_ssr_primary_nav"


@dataclass(frozen=True)
class ConceptRecoveryLadderResolved:
    enabled: bool
    step: int
    resume_blob: dict[str, Any] | None
    anchor_topic: str | None


def _active_scope_id() -> str | None:
    from app.ui.study_scope import get_active_scope

    scope = get_active_scope()
    if not isinstance(scope, dict):
        return None
    sid = str(scope.get("id") or "").strip()
    return sid or None


def ensure_concept_recovery_ladder_enabled_in_session() -> bool:
    if _CONCEPT_RECOVERY_LADDER_ENABLED_KEY not in st.session_state:
        st.session_state[_CONCEPT_RECOVERY_LADDER_ENABLED_KEY] = True
    return bool(st.session_state[_CONCEPT_RECOVERY_LADDER_ENABLED_KEY])


def persist_resolved_ladder_context(
    *,
    step: int,
    concept_anchor: str = "",
    scope_id: str | None = None,
    resume_blob: dict[str, Any] | None = None,
    clear: bool = False,
) -> None:
    from app.learner_model_service import persist_concept_recovery_ladder
    from app.smart_study_recovery_ladder import (
        clear_concept_recovery_ladder_session,
        concept_recovery_resume_v1,
        normalize_concept_recovery_ladder_step,
    )

    try:
        if clear:
            persist_concept_recovery_ladder(1, clear=True)
            for key, val in clear_concept_recovery_ladder_session().items():
                st.session_state[key] = val
            st.session_state[_CONCEPT_RECOVERY_ANCHOR_TOPIC_KEY] = ""
            st.session_state.pop(_CONCEPT_RECOVERY_RESUME_V1_KEY, None)
            st.session_state[_CONCEPT_RECOVERY_LADDER_PERSIST_ERROR_KEY] = None
            return

        norm_step = normalize_concept_recovery_ladder_step(step)
        sid = scope_id if scope_id is not None else _active_scope_id()
        blob = resume_blob or concept_recovery_resume_v1(
            norm_step,
            concept_anchor=concept_anchor,
            scope_id=sid,
        )
        saved = persist_concept_recovery_ladder(
            norm_step,
            concept_anchor=concept_anchor or str(blob.get("anchor") or ""),
            scope_id=sid,
        )
        st.session_state[_CONCEPT_RECOVERY_LADDER_STEP_KEY] = norm_step
        st.session_state[_CONCEPT_RECOVERY_RESUME_V1_KEY] = saved or blob
        anchor = str(concept_anchor or (saved or blob).get("anchor") or "").strip()
        if anchor:
            st.session_state[_CONCEPT_RECOVERY_ANCHOR_TOPIC_KEY] = anchor
        st.session_state[_CONCEPT_RECOVERY_LADDER_PERSIST_ERROR_KEY] = None
    except Exception as exc:  # noqa: BLE001 - persist failure must not break SSR surfaces.
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("concept recovery ladder persist: %s", exc)
        st.session_state[_CONCEPT_RECOVERY_LADDER_PERSIST_ERROR_KEY] = str(exc)[:240]


def resolve_concept_recovery_ladder_context(
    *,
    current_anchor: str | None = None,
    quiz_feedback_status: str | None = None,
    hydrate_persisted: bool = True,
) -> ConceptRecoveryLadderResolved:
    from app.learner_model_service import read_persisted_concept_recovery_ladder
    from app.smart_study_recommendation import _quiz_feedback_failed
    from app.smart_study_recovery_ladder import (
        invalidate_concept_recovery_ladder_on_scope_change,
        ladder_step_from_resume_v1,
        normalize_concept_recovery_ladder_step,
        reconcile_concept_recovery_ladder_anchor,
    )

    enabled = ensure_concept_recovery_ladder_enabled_in_session()
    scope_id = _active_scope_id()
    anchor = str(
        current_anchor
        or st.session_state.get(_CONCEPT_RECOVERY_ANCHOR_TOPIC_KEY)
        or st.session_state.get("current_topic")
        or ""
    ).strip() or None

    if hydrate_persisted and not st.session_state.get(_CONCEPT_RECOVERY_LADDER_HYDRATED_FLAG):
        st.session_state[_CONCEPT_RECOVERY_LADDER_HYDRATING_KEY] = True
        try:
            persisted_raw = read_persisted_concept_recovery_ladder()
            persisted = invalidate_concept_recovery_ladder_on_scope_change(
                persisted_raw,
                active_scope_id=scope_id,
            )
            if persisted_raw and persisted is None:
                persist_resolved_ladder_context(clear=True)

            session_step_raw = st.session_state.get(_CONCEPT_RECOVERY_LADDER_STEP_KEY)
            session_blob = st.session_state.get(_CONCEPT_RECOVERY_RESUME_V1_KEY)
            session_step = (
                normalize_concept_recovery_ladder_step(session_step_raw)
                if session_step_raw is not None
                else None
            )

            if isinstance(persisted, dict) and persisted:
                resolved_step, resolved_blob = reconcile_concept_recovery_ladder_anchor(
                    persisted,
                    current_anchor=anchor or str(persisted.get("anchor") or ""),
                    scope_id=scope_id,
                )
                if session_step is not None and session_step > resolved_step:
                    step = session_step
                    blob = session_blob if isinstance(session_blob, dict) else resolved_blob
                else:
                    step = resolved_step
                    blob = resolved_blob
                    if resolved_step != ladder_step_from_resume_v1(persisted) or (
                        anchor and str(resolved_blob.get("anchor") or "") != str(persisted.get("anchor") or "")
                    ):
                        persist_resolved_ladder_context(
                            step=step,
                            concept_anchor=str((blob or {}).get("anchor") or anchor or ""),
                            scope_id=scope_id,
                            resume_blob=blob if isinstance(blob, dict) else None,
                        )
                    else:
                        st.session_state[_CONCEPT_RECOVERY_LADDER_STEP_KEY] = step
                        st.session_state[_CONCEPT_RECOVERY_RESUME_V1_KEY] = blob
                        if blob and blob.get("anchor"):
                            st.session_state[_CONCEPT_RECOVERY_ANCHOR_TOPIC_KEY] = str(blob.get("anchor"))
            elif session_step is not None:
                step = session_step
                blob = session_blob if isinstance(session_blob, dict) else None
            else:
                step = 1
                blob = None
        except Exception as exc:  # noqa: BLE001 - hydration failure falls back to session-only step.
            import logging  # noqa: BLE001

            logging.getLogger(__name__).debug("concept recovery ladder hydrate: %s", exc)
            st.session_state[_CONCEPT_RECOVERY_LADDER_PERSIST_ERROR_KEY] = str(exc)[:240]
            step = normalize_concept_recovery_ladder_step(
                st.session_state.get(_CONCEPT_RECOVERY_LADDER_STEP_KEY, 1)
            )
            blob_raw = st.session_state.get(_CONCEPT_RECOVERY_RESUME_V1_KEY)
            blob = blob_raw if isinstance(blob_raw, dict) else None
        finally:
            st.session_state[_CONCEPT_RECOVERY_LADDER_HYDRATING_KEY] = False
            st.session_state[_CONCEPT_RECOVERY_LADDER_HYDRATED_FLAG] = True
    else:
        step = normalize_concept_recovery_ladder_step(
            st.session_state.get(_CONCEPT_RECOVERY_LADDER_STEP_KEY, 1)
        )
        blob_raw = st.session_state.get(_CONCEPT_RECOVERY_RESUME_V1_KEY)
        blob = blob_raw if isinstance(blob_raw, dict) else None

    if _quiz_feedback_failed(quiz_feedback_status) and anchor:
        if not isinstance(blob, dict):
            persist_resolved_ladder_context(step=1, concept_anchor=anchor, scope_id=scope_id)
            step = 1
            blob = st.session_state.get(_CONCEPT_RECOVERY_RESUME_V1_KEY)
            if not isinstance(blob, dict):
                blob = None
        else:
            resolved_step, resolved_blob = reconcile_concept_recovery_ladder_anchor(
                blob,
                current_anchor=anchor,
                scope_id=scope_id,
            )
            if resolved_step != step or (
                isinstance(resolved_blob, dict)
                and resolved_blob.get("anchor") != blob.get("anchor")
            ):
                persist_resolved_ladder_context(
                    step=resolved_step,
                    concept_anchor=anchor,
                    scope_id=scope_id,
                    resume_blob=resolved_blob if isinstance(resolved_blob, dict) else None,
                )
                step = resolved_step
                blob = st.session_state.get(_CONCEPT_RECOVERY_RESUME_V1_KEY)
                if not isinstance(blob, dict):
                    blob = resolved_blob if isinstance(resolved_blob, dict) else None

    return ConceptRecoveryLadderResolved(
        enabled=enabled,
        step=step,
        resume_blob=blob if isinstance(blob, dict) else None,
        anchor_topic=anchor,
    )


def render_concept_recovery_ladder_status_ui() -> None:
    if st.session_state.get(_CONCEPT_RECOVERY_LADDER_HYDRATING_KEY):
        st.caption("Восстанавливаем шаг восстановления…")
    err = st.session_state.get(_CONCEPT_RECOVERY_LADDER_PERSIST_ERROR_KEY)
    if err:
        st.warning("Не удалось сохранить прогресс восстановления")


def ladder_kwargs_for_build(
    *,
    current_anchor: str | None = None,
    quiz_feedback_status: str | None = None,
) -> dict[str, Any]:
    ctx = resolve_concept_recovery_ladder_context(
        current_anchor=current_anchor,
        quiz_feedback_status=quiz_feedback_status,
    )
    return {
        "concept_recovery_ladder_step": ctx.step,
        "concept_recovery_ladder_enabled": ctx.enabled,
    }


def seed_concept_recovery_ladder_on_quiz_failed(*, topic_anchor: str | None) -> None:
    anchor = str(
        topic_anchor or st.session_state.get("current_topic") or ""
    ).strip()
    if not anchor:
        return
    persist_resolved_ladder_context(step=1, concept_anchor=anchor, scope_id=_active_scope_id())


def maybe_clear_concept_recovery_ladder_on_variant_quiz_success(
    *,
    quiz_feedback: dict[str, Any] | None,
    quiz_concept: str | None,
) -> None:
    from app.smart_study_recovery_ladder import should_clear_ladder_on_variant_quiz_success

    if not isinstance(quiz_feedback, dict):
        return
    status = str(quiz_feedback.get("status") or "").strip()
    blob = st.session_state.get(_CONCEPT_RECOVERY_RESUME_V1_KEY)
    step_raw = st.session_state.get(_CONCEPT_RECOVERY_LADDER_STEP_KEY)
    cta = str(st.session_state.get("tutor_cta_action") or "").strip()
    last_primary = str(st.session_state.get(_LAST_SSR_PRIMARY_NAV_KEY) or "").strip() or None
    if cta == "smart_study_quiz_recovery" and last_primary in (None, ""):
        last_primary = "quiz_recovery_tutor"
    if should_clear_ladder_on_variant_quiz_success(
        quiz_feedback_status=status,
        quiz_concept=quiz_concept,
        ladder_blob=blob if isinstance(blob, dict) else None,
        ladder_step=int(step_raw) if step_raw is not None else None,
        last_ssr_primary=last_primary,
    ):
        persist_resolved_ladder_context(clear=True)


def remember_ssr_primary_nav(primary_nav: str | None) -> None:
    nav = str(primary_nav or "").strip()
    if nav:
        st.session_state[_LAST_SSR_PRIMARY_NAV_KEY] = nav


def _current_ladder_step_for_navigation() -> int:
    from app.smart_study_recovery_ladder import normalize_concept_recovery_ladder_step

    return normalize_concept_recovery_ladder_step(
        st.session_state.get(_CONCEPT_RECOVERY_LADDER_STEP_KEY, 1)
    )


def advance_concept_recovery_ladder_after_primary(rec: Any) -> None:
    from app.smart_study_recovery_ladder import normalize_concept_recovery_ladder_step

    if str(getattr(rec, "hint_kind", "") or "") != "quiz_failed":
        return
    if not ensure_concept_recovery_ladder_enabled_in_session():
        return
    step = _current_ladder_step_for_navigation()
    nav = str(getattr(rec, "primary_nav", "") or "")
    new_step = step
    if step <= 1 and nav == "qa_continue":
        new_step = 2
    elif step == 2 and nav == "qa_continue":
        new_step = 3
    elif step <= 2 and nav == "quiz_recovery_tutor":
        new_step = 3
    elif step <= 3 and nav == "tutor_weak_gap":
        new_step = 4
    if new_step == step:
        return
    anchor = str(st.session_state.get(_CONCEPT_RECOVERY_ANCHOR_TOPIC_KEY) or "").strip()
    persist_resolved_ladder_context(
        step=normalize_concept_recovery_ladder_step(new_step),
        concept_anchor=anchor,
        scope_id=_active_scope_id(),
    )


def advance_concept_recovery_ladder_after_secondary(action_id: str) -> None:
    from app.smart_study_recovery_ladder import normalize_concept_recovery_ladder_step

    if not ensure_concept_recovery_ladder_enabled_in_session():
        return
    step = _current_ladder_step_for_navigation()
    aid = str(action_id or "").strip()
    new_step = step
    if aid == "qa_sources":
        new_step = max(step, 2)
    elif aid == "tutor_simpler":
        new_step = max(step, 3)
    elif aid == "quiz_nav":
        new_step = max(step, 4)
    if new_step == step:
        return
    anchor = str(st.session_state.get(_CONCEPT_RECOVERY_ANCHOR_TOPIC_KEY) or "").strip()
    persist_resolved_ladder_context(
        step=normalize_concept_recovery_ladder_step(new_step),
        concept_anchor=anchor,
        scope_id=_active_scope_id(),
    )
