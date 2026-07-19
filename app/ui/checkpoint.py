"""B1 unified checkpoint: one renderer for tutor/quiz/flashcard completions.

Re-invokes canonical Route Policy with updated signals. Shows:
  primary → continue as proposed
  secondary → change direction (intent palette, ≤2 alternatives)
  «Закончить» → navigate to return_view (caller's origin)
  «Вручную» → navigate to Mission Control (full manual access)

Instance identity: each call passes a ``completion_key`` unique per learning
result (quiz_hash, msg_idx+batch, session+step). UUID rotates on new completion_key,
stays stable on rerender. Two completions → two events, always.

return_view is injected into the SSR recommendation and forwarded to
primary/secondary/intent handlers so breadcrumbs survive checkpoint transitions.

Stores privacy-safe context (ids, not text) in session_state.
No auto-start, no background write — checkpoint is a user-initiated gate.
"""

from __future__ import annotations

import uuid

import streamlit as st

from app.smart_study_router import SmartStudyRecommendation

_CHECKPOINT_CONTEXT_KEY = "_checkpoint_context"
_CHECKPOINT_INSTANCE_KEY = "_checkpoint_instance_id"
_CHECKPOINT_COMPLETION_KEY = "_checkpoint_completion_key"

_emitted_checkpoint_instances: set[str] = set()


def store_checkpoint_context(
    *,
    topic_hint: str | None = None,
    origin: str | None = None,
    return_view: str | None = None,
    decision_id: str | None = None,
    phase: str | None = None,
    completion_key: str | None = None,
) -> None:
    """Save checkpoint context. Generates a new instance UUID when completion_key
    changes (new learning result). On rerenders of the same checkpoint, UUID is reused.

    completion_key is the completion-level identity: quiz_hash, msg_idx, or batch_id.
    It MUST differ between two distinct completions of the same surface.
    """
    prev_ck = st.session_state.get(_CHECKPOINT_COMPLETION_KEY)
    new_ck = str(completion_key or "").strip() or None

    instance_id = st.session_state.get(_CHECKPOINT_INSTANCE_KEY)
    if not instance_id or prev_ck != new_ck:
        instance_id = str(uuid.uuid4())
        st.session_state[_CHECKPOINT_INSTANCE_KEY] = instance_id
    st.session_state[_CHECKPOINT_COMPLETION_KEY] = new_ck

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
    st.session_state.pop(_CHECKPOINT_COMPLETION_KEY, None)


def _emit_checkpoint_offered(rec: SmartStudyRecommendation, surface: str) -> None:
    """Emit session-tape checkpoint_offered once per checkpoint instance UUID.

    UUID is stable across rerenders but rotates on new completion_key
    (new learning result). Two completions always produce two events.
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


def _inject_return_view(
    rec: SmartStudyRecommendation, origin: str, return_view: str
) -> SmartStudyRecommendation:
    """Return a copy of rec with origin/return_view set so SSR actions
    (primary, secondary, intent palette) share the correct breadcrumb."""
    return SmartStudyRecommendation(
        hint_kind=rec.hint_kind,
        primary_label_ru=rec.primary_label_ru,
        why_now_ru=rec.why_now_ru,
        primary_nav=rec.primary_nav,
        secondaries=rec.secondaries,
        route_pedagogy_ru=rec.route_pedagogy_ru,
        ml_audit_ru=rec.ml_audit_ru,
        flashcard_due_n=rec.flashcard_due_n,
        sm2_due_n=rec.sm2_due_n,
        phase=rec.phase,
        topic_hint=rec.topic_hint,
        origin=origin,
        return_view=return_view,
        decision_id=rec.decision_id,
    )


def render_checkpoint(
    rec: SmartStudyRecommendation,
    *,
    surface: str,
    origin: str,
    return_view: str,
    key_prefix: str,
    completion_key: str | None = None,
    tutor_session_id: str | None = None,
    tutor_topic: str | None = None,
    weak_concept: str | None = None,
    plan_block: dict | None = None,
    on_finish: object = None,
) -> None:
    """Unified checkpoint after learning step completion.

    Renders SSR card with primary button + ≤2 alternatives + «Сменить направление»
    palette, plus «Закончить» (back to return_view) / «Вручную» (Mission Control).

    ``completion_key`` — unique identity of this learning result (quiz_hash,
    msg_idx, batch_id). Used for UUID rotation so two distinct completions
    always produce two checkpoint_offered events.

    ``on_finish`` — optional callable invoked on finish/manual click.
    """
    from app.ui.smart_study_next_step_card import render_smart_study_next_step_card

    topic_hint = str(rec.topic_hint or "").strip() or None

    store_checkpoint_context(
        topic_hint=topic_hint,
        origin=origin,
        return_view=return_view,
        decision_id=str(rec.decision_id),
        phase=str(rec.phase),
        completion_key=completion_key,
    )
    _emit_checkpoint_offered(rec, surface)

    st.markdown("---")
    st.caption("Завершение шага")

    rec_capped = _cap_secondaries(rec)
    rec_for_card = _inject_return_view(rec_capped, origin=origin, return_view=return_view)

    # B2 compass: compact status line above route shell
    _render_compass_above_checkpoint(
        rec_for_card,
        return_point=_compass_return_point(return_view),
    )

    render_smart_study_next_step_card(
        rec_for_card,
        key_prefix=f"{key_prefix}_chkpt",
        primary_topic_hint=topic_hint,
        tutor_session_id=tutor_session_id,
        tutor_topic=tutor_topic,
        weak_concept=weak_concept,
        plan_block=plan_block,
        show_primary_button=True,
        enable_what_if_preview=False,
    )

    _render_checkpoint_actions(
        key_prefix=key_prefix,
        return_view=return_view,
        on_finish=on_finish,
    )


def _render_checkpoint_actions(
    *,
    key_prefix: str,
    return_view: str,
    on_finish: object = None,
) -> None:
    """Render «Закончить» / «Вручную» buttons below the SSR card."""
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
    secs = rec.secondaries
    if len(secs) <= 2:
        return rec
    capped = tuple(secs[:2])
    return SmartStudyRecommendation(
        hint_kind=rec.hint_kind, primary_label_ru=rec.primary_label_ru,
        why_now_ru=rec.why_now_ru, primary_nav=rec.primary_nav,
        secondaries=capped, route_pedagogy_ru=rec.route_pedagogy_ru,
        ml_audit_ru=rec.ml_audit_ru, flashcard_due_n=rec.flashcard_due_n,
        sm2_due_n=rec.sm2_due_n, phase=rec.phase, topic_hint=rec.topic_hint,
        origin=rec.origin, return_view=rec.return_view, decision_id=rec.decision_id,
    )


def _navigate_to_return_view(return_view: str) -> None:
    from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
    rv = str(return_view or "").strip()
    if rv:
        st.session_state[PENDING_CURRENT_VIEW_KEY] = rv
    clear_checkpoint_context()
    st.rerun()


def _compass_return_point(return_view: str) -> str | None:
    """Return a human-readable return-point label from the view name."""
    rv = str(return_view or "").strip()
    if not rv:
        return None
    _RETURN_MAP: dict[str, str] = {
        "Mission Control": "на главную",
        "Чат с тьютором": "в чат",
        "Прогресс обучения": "в прогресс",
        "Flashcards": "к карточкам",
        "Темы": "к темам",
        "Живой конспект": "в конспект",
        "Быстрый ответ": "к ответу",
        "Адаптивный план": "в план",
    }
    return _RETURN_MAP.get(rv, rv)


def _render_compass_above_checkpoint(
    rec: SmartStudyRecommendation,
    *,
    return_point: str | None = None,
) -> None:
    """B2: render compass line above the checkpoint's SSR card."""
    try:
        from app.ui.learning_compass import render_learning_compass

        render_learning_compass(
            rec,
            return_point=return_point,
        )
    except Exception:  # noqa: BLE001 — compass is optional UI decoration
        pass


def _navigate_manual() -> None:
    from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
    st.session_state[PENDING_CURRENT_VIEW_KEY] = "Mission Control"
    clear_checkpoint_context()
    st.rerun()
