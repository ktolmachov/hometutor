"""B1 unified checkpoint: one renderer for tutor/quiz/flashcard completions.

Re-invokes canonical Route Policy with updated signals. Shows:
  primary → continue as proposed
  secondary → change direction (intent palette, ≤2 alternatives)
  «Закончить» → navigate to return_view (caller's origin)
  «Вручную» → navigate to Mission Control (full manual access)

Deduplication per completion instance: each render_checkpoint() call generates
a fresh UUID stored alongside the checkpoint context. Two completions → two
UUIDs → two tape events, even if key_prefix is the same.

Stores privacy-safe context (ids, not text) in session_state.
No auto-start, no background write — checkpoint is a user-initiated gate.
"""

from __future__ import annotations

import uuid

import streamlit as st

from app.smart_study_router import SmartStudyRecommendation

_CHECKPOINT_CONTEXT_KEY = "_checkpoint_context"
_CHECKPOINT_INSTANCE_KEY = "_checkpoint_instance_id"

_emitted_checkpoint_instances: set[str] = set()


def store_checkpoint_context(
    *,
    topic_hint: str | None = None,
    origin: str | None = None,
    return_view: str | None = None,
    decision_id: str | None = None,
    phase: str | None = None,
) -> None:
    """Save checkpoint context. Generates stable instance UUID on first call;
    reuse on rerenders so checkpoint_offered fires exactly once per completion."""
    instance_id = st.session_state.get(_CHECKPOINT_INSTANCE_KEY)
    if not instance_id:
        instance_id = str(uuid.uuid4())
        st.session_state[_CHECKPOINT_INSTANCE_KEY] = instance_id
    st.session_state[_CHECKPOINT_CONTEXT_KEY] = {
        "topic_hint": str(topic_hint or "").strip() or None,
        "origin": str(origin or "").strip() or None,
        "return_view": str(return_view or "").strip() or None,
        "decision_id": str(decision_id or "").strip() or None,
        "phase": str(phase or "").strip() or None,
    }


def load_checkpoint_context() -> dict[str, str | None] | None:
    raw = st.session_state.get(_CHECKPOINT_CONTEXT_KEY)
    if not isinstance(raw, dict):
        return None
    return raw


def clear_checkpoint_context() -> None:
    st.session_state.pop(_CHECKPOINT_CONTEXT_KEY, None)
    st.session_state.pop(_CHECKPOINT_INSTANCE_KEY, None)


def _emit_checkpoint_offered(rec: SmartStudyRecommendation, surface: str) -> None:
    """Emit session-tape checkpoint_offered once per checkpoint instance UUID.

    Each render_checkpoint() call generates a new UUID via store_checkpoint_context,
    so two completions on the same surface always produce two tape events.
    """
    instance_id = str(st.session_state.get(_CHECKPOINT_INSTANCE_KEY) or "").strip()
    if not instance_id:
        return
    if instance_id in _emitted_checkpoint_instances:
        return
    try:
        from app.session_tape import append_event

        sid = str(st.session_state.get("_session_tape_id") or "").strip()
        if not sid:
            return
        append_event(sid, "checkpoint_offered", {
            "surface": surface,
            "primary_nav": str(rec.primary_nav),
            "hint_kind": str(rec.hint_kind),
            "decision_id": str(rec.decision_id),
            "phase": str(rec.phase),
        })
        _emitted_checkpoint_instances.add(instance_id)
    except Exception:  # noqa: BLE001 - tape must never block UI
        pass


def render_checkpoint(
    rec: SmartStudyRecommendation,
    *,
    surface: str,
    origin: str,
    return_view: str,
    key_prefix: str,
    tutor_session_id: str | None = None,
    tutor_topic: str | None = None,
    weak_concept: str | None = None,
    plan_block: dict | None = None,
    on_finish: object = None,
) -> None:
    """Unified checkpoint after learning step completion.

    Renders SSR card with primary button + ≤2 alternatives + «Сменить направление»
    palette, plus «Закончить» (back to return_view) / «Вручную» (Mission Control).

    ``on_finish`` — optional callable invoked when the user clicks finish or manual
    (only on explicit action, not during render). Use for surface-specific cleanup.
    """
    from app.ui.smart_study_next_step_card import render_smart_study_next_step_card

    topic_hint = str(rec.topic_hint or "").strip() or None

    store_checkpoint_context(
        topic_hint=topic_hint,
        origin=origin,
        return_view=return_view,
        decision_id=str(rec.decision_id),
        phase=str(rec.phase),
    )
    _emit_checkpoint_offered(rec, surface)

    st.markdown("---")
    st.caption("Завершение шага")

    rec_capped = _cap_secondaries(rec)

    render_smart_study_next_step_card(
        rec_capped,
        key_prefix=f"{key_prefix}_chkpt",
        primary_topic_hint=topic_hint,
        tutor_session_id=tutor_session_id,
        tutor_topic=tutor_topic,
        weak_concept=weak_concept,
        plan_block=plan_block,
        show_primary_button=True,
        enable_what_if_preview=False,
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            "✅ Закончить",
            key=f"{key_prefix}_chkpt_finish",
            width="stretch",
            type="secondary",
        ):
            if callable(on_finish):
                on_finish()
            _navigate_to_return_view(return_view)
    with col2:
        if st.button(
            "🖐 Вручную",
            key=f"{key_prefix}_chkpt_manual",
            width="stretch",
            type="secondary",
        ):
            if callable(on_finish):
                on_finish()
            _navigate_manual()


def _cap_secondaries(rec: SmartStudyRecommendation) -> SmartStudyRecommendation:
    """Clamp secondaries to ≤2 for checkpoint display."""
    secs = rec.secondaries
    if len(secs) <= 2:
        return rec
    capped = tuple(secs[:2])
    return SmartStudyRecommendation(
        hint_kind=rec.hint_kind,
        primary_label_ru=rec.primary_label_ru,
        why_now_ru=rec.why_now_ru,
        primary_nav=rec.primary_nav,
        secondaries=capped,
        route_pedagogy_ru=rec.route_pedagogy_ru,
        ml_audit_ru=rec.ml_audit_ru,
        flashcard_due_n=rec.flashcard_due_n,
        sm2_due_n=rec.sm2_due_n,
        phase=rec.phase,
        topic_hint=rec.topic_hint,
        origin=rec.origin,
        return_view=rec.return_view,
        decision_id=rec.decision_id,
    )


def _navigate_to_return_view(return_view: str) -> None:
    """Navigate back to return_view and clear checkpoint context."""
    from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

    rv = str(return_view or "").strip()
    if rv:
        st.session_state[PENDING_CURRENT_VIEW_KEY] = rv
    clear_checkpoint_context()
    st.rerun()


def _navigate_manual() -> None:
    """Navigate to Mission Control with full manual access — no forced route."""
    from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

    st.session_state[PENDING_CURRENT_VIEW_KEY] = "Mission Control"
    clear_checkpoint_context()
    st.rerun()
