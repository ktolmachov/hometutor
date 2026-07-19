"""B1 unified checkpoint: one renderer for tutor/quiz/flashcard completions.

Re-invokes canonical Route Policy with updated signals. Shows:
  primary → continue as proposed
  secondary → change direction (intent palette, ≤2 alternatives)
  «Закончить» → navigate to return_view
  «Вручную» → navigate to Mission Control (full access, no forced route)

Stores privacy-safe context (ids, not question/answer text) in session_state.
No new view, no new mode, no auto-start — checkpoint is a user-initiated gate.
"""

from __future__ import annotations

import streamlit as st

from app.smart_study_router import SmartStudyRecommendation

_CHECKPOINT_CONTEXT_KEY = "_checkpoint_context"

_emitted_checkpoint_ids: set[tuple[str, str]] = set()


def store_checkpoint_context(
    *,
    topic_hint: str | None = None,
    origin: str | None = None,
    return_view: str | None = None,
    decision_id: str | None = None,
    phase: str | None = None,
) -> None:
    """Save checkpoint context in session_state (privacy-safe: ids, not text)."""
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


def _emit_checkpoint_offered(rec: SmartStudyRecommendation, surface: str) -> None:
    """Emit session-tape checkpoint_offered once per (session_id, decision_id)."""
    did = str(rec.decision_id)
    if not did:
        return
    try:
        from app.session_tape import append_event

        sid = str(st.session_state.get("_session_tape_id") or "").strip()
        if not sid:
            return
    except Exception:  # noqa: BLE001 - tape must never block UI
        return
    dedupe_key = (sid, did)
    if dedupe_key in _emitted_checkpoint_ids:
        return
    try:
        append_event(sid, "checkpoint_offered", {
            "surface": surface,
            "primary_nav": str(rec.primary_nav),
            "hint_kind": str(rec.hint_kind),
            "decision_id": did,
            "phase": str(rec.phase),
        })
        _emitted_checkpoint_ids.add(dedupe_key)
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
) -> None:
    """Unified checkpoint after learning step completion.

    Renders SSR card with primary button + «Сменить направление» palette,
    plus «Закончить» (back to return_view) / «Вручную» (Mission Control full access).
    Does NOT auto-start the next step.
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

    render_smart_study_next_step_card(
        rec,
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
            _navigate_to_return_view(return_view)
    with col2:
        if st.button(
            "🖐 Вручную",
            key=f"{key_prefix}_chkpt_manual",
            width="stretch",
            type="secondary",
        ):
            _navigate_manual()


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
