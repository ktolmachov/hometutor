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

    B3: when autopilot is active and completion_key changes (new step reached),
    autopilot.step_completed is called to decrement budget and prevent re-execution
    on refresh.
    """
    prev_ck = st.session_state.get(_CHECKPOINT_COMPLETION_KEY)
    prev_ck_existed = _CHECKPOINT_COMPLETION_KEY in st.session_state
    new_ck = str(completion_key or "").strip() or None

    instance_id = st.session_state.get(_CHECKPOINT_INSTANCE_KEY)
    is_new_checkpoint = not instance_id or prev_ck != new_ck
    if is_new_checkpoint:
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

    if is_new_checkpoint and prev_ck_existed:
        try:
            from app.ui.autopilot import is_autopilot_active, step_completed
            if is_autopilot_active():
                step_completed(str(decision_id or ""), completion_key=str(new_ck or ""))
        except Exception:  # noqa: BLE001 — autopilot is opt-in, never block checkpoint
            pass


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
    _autopilot_budget = _autopilot_budget_min_for_compass()
    _render_compass_above_checkpoint(
        rec_for_card,
        return_point=_compass_return_point(return_view),
        time_budget_min=_autopilot_budget,
    )

    # B3 autopilot: status indicator when active
    _render_autopilot_status()

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

    # B3 autopilot: activation widget when autopilot is inactive
    _render_autopilot_activation(key_prefix=key_prefix, surface=surface)


def _render_checkpoint_actions(
    *,
    key_prefix: str,
    return_view: str,
    on_finish: object = None,
) -> None:
    """Render «Закончить» / «Вручную» buttons below the SSR card.
    B3: when autopilot is active, shows «Пауза» / «Продолжить» / «Готово» / «Вручную».
    """
    try:
        from app.ui.autopilot import is_autopilot_active, is_autopilot_paused, pause_autopilot, resume_autopilot, finish_autopilot
        autopilot_active = is_autopilot_active()
        autopilot_paused = is_autopilot_paused()
    except Exception:  # noqa: BLE001 — autopilot is opt-in
        autopilot_active = False
        autopilot_paused = False

    if autopilot_active:
        _render_autopilot_actions(
            key_prefix=key_prefix,
            return_view=return_view,
            paused=autopilot_paused,
            on_finish=on_finish,
            on_pause=pause_autopilot,
            on_resume=resume_autopilot,
            on_done=finish_autopilot,
        )
    else:
        _render_default_checkpoint_actions(
            key_prefix=key_prefix,
            return_view=return_view,
            on_finish=on_finish,
        )


def _render_autopilot_actions(
    *,
    key_prefix: str,
    return_view: str,
    paused: bool,
    on_finish: object = None,
    on_pause: object = None,
    on_resume: object = None,
    on_done: object = None,
) -> None:
    col1, col2, col3 = st.columns(3)
    with col1:
        if paused:
            if st.button(
                "▶ Продолжить",
                key=f"{key_prefix}_chkpt_resume",
                width="stretch",
                type="primary",
            ):
                if callable(on_resume):
                    on_resume()
                st.rerun()
        else:
            if st.button(
                "⏸ Пауза",
                key=f"{key_prefix}_chkpt_pause",
                width="stretch",
                type="secondary",
            ):
                if callable(on_pause):
                    on_pause()
                st.rerun()
    with col2:
        if st.button(
            "🖐 Вручную",
            key=f"{key_prefix}_chkpt_manual_ap",
            width="stretch",
            type="secondary",
        ):
            if callable(on_finish):
                on_finish()
            if callable(on_done):
                on_done("manual_override")
            _navigate_manual()
    with col3:
        if st.button(
            "✅ Готово",
            key=f"{key_prefix}_chkpt_done",
            width="stretch",
            type="secondary",
        ):
            if callable(on_finish):
                on_finish()
            if callable(on_done):
                on_done("user_finished")
            _navigate_to_return_view(return_view)


def _render_default_checkpoint_actions(
    *,
    key_prefix: str,
    return_view: str,
    on_finish: object = None,
) -> None:
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


def _autopilot_budget_min_for_compass() -> int | None:
    try:
        from app.ui.autopilot import is_autopilot_active, is_autopilot_paused, budget_remaining_min
        if is_autopilot_active() and not is_autopilot_paused():
            return budget_remaining_min()
    except Exception:  # noqa: BLE001 — autopilot is opt-in
        pass
    return None


def _render_autopilot_status() -> None:
    """B3: show autopilot status indicator when active."""
    try:
        from app.ui.autopilot import is_autopilot_active, is_autopilot_paused, get_autopilot_state
        if not is_autopilot_active():
            return
        state = get_autopilot_state()
        budget_rem = state.get("budget_remaining_min", 0)
        steps = state.get("steps_completed", 0)
        paused = is_autopilot_paused()

        if paused:
            status_text = f"⏸ Автопилот на паузе · {budget_rem} мин осталось · {steps} шагов"
            status_style = "opacity:0.85;color:var(--ink-muted,#888);"
        else:
            status_text = f"🤖 Автопилот · {budget_rem} мин осталось · {steps} шагов"
            status_style = "opacity:0.85;color:var(--ink,#333);"

        st.html(
            f'<div data-testid="e2e-autopilot-status" '
            f'style="font-size:0.82rem;margin:0.15rem 0 0.35rem 0;{status_style}">'
            f"{status_text}</div>"
        )
    except Exception:  # noqa: BLE001 — autopilot is opt-in UI
        pass


def _render_autopilot_activation(*, key_prefix: str, surface: str = "Mission Control") -> None:
    """B3: offer autopilot opt-in when autopilot is not active."""
    try:
        from app.ui.autopilot import is_autopilot_active, enable_autopilot
        if is_autopilot_active():
            return
    except Exception:  # noqa: BLE001 — autopilot is opt-in
        return

    with st.expander("🤖 Включить автопилот", expanded=False):
        st.caption("Автопилот предложит цепочку шагов по маршруту, но после каждого шага "
                   "будет останавливаться. Вы сами решаете, продолжать или свернуть.")
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("5 мин", key=f"{key_prefix}_ap_5", width="stretch", type="primary"):
                try:
                    from app.ui.autopilot import enable_autopilot
                    enable_autopilot(5, entry_surface=surface)
                except Exception:  # noqa: BLE001
                    pass
                st.rerun()
        with col2:
            if st.button("15 мин", key=f"{key_prefix}_ap_15", width="stretch"):
                try:
                    from app.ui.autopilot import enable_autopilot
                    enable_autopilot(15, entry_surface=surface)
                except Exception:  # noqa: BLE001
                    pass
                st.rerun()
        with col3:
            if st.button("25 мин", key=f"{key_prefix}_ap_25", width="stretch"):
                try:
                    from app.ui.autopilot import enable_autopilot
                    enable_autopilot(25, entry_surface=surface)
                except Exception:  # noqa: BLE001
                    pass
                st.rerun()


def _render_compass_above_checkpoint(
    rec: SmartStudyRecommendation,
    *,
    return_point: str | None = None,
    time_budget_min: int | None = None,
) -> None:
    """B2/B3: render compass line above the checkpoint's SSR card."""
    try:
        from app.ui.learning_compass import render_learning_compass

        render_learning_compass(
            rec,
            return_point=return_point,
            time_budget_min=time_budget_min,
        )
    except Exception:  # noqa: BLE001 — compass is optional UI decoration
        pass


def _navigate_manual() -> None:
    from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
    st.session_state[PENDING_CURRENT_VIEW_KEY] = "Mission Control"
    clear_checkpoint_context()
    st.rerun()
