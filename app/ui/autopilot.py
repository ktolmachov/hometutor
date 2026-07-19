"""B3 safe autopilot: session-state helper for opt-in budget 5/15/25 min.

One session, foreground checkpoint flow. No background worker, no new persistence.
- User explicitly enables autopilot and picks a budget.
- After each step, execution stops at checkpoint; next step only by click.
- Budget decreases per completed step; refresh/resume does NOT re-execute.
- «Пауза» / «Вручную» / «Готово» always available.
- Write-actions remain confirm-only.

State lives entirely in st.session_state; no DB writes.
"""

from __future__ import annotations

import streamlit as st

_AUTOPILOT_PREFIX = "_autopilot"
_BUDGET_OPTIONS = (5, 15, 25)
_STEP_COST_MIN = 5


# ── public state query ──────────────────────────────────────────────────────


def is_autopilot_active() -> bool:
    return bool(st.session_state.get(f"{_AUTOPILOT_PREFIX}_enabled", False))


def is_autopilot_paused() -> bool:
    return bool(st.session_state.get(f"{_AUTOPILOT_PREFIX}_paused", False))


def get_autopilot_state() -> dict:
    """Return privacy-safe snapshot of current autopilot state."""
    return {
        "enabled": is_autopilot_active(),
        "paused": is_autopilot_paused(),
        "budget_total_min": st.session_state.get(f"{_AUTOPILOT_PREFIX}_budget_total_min", 0),
        "budget_remaining_min": st.session_state.get(f"{_AUTOPILOT_PREFIX}_budget_remaining_min", 0),
        "steps_completed": st.session_state.get(f"{_AUTOPILOT_PREFIX}_steps_completed", 0),
        "last_completion_key": st.session_state.get(f"{_AUTOPILOT_PREFIX}_last_completion_key", ""),
        "entry_surface": st.session_state.get(f"{_AUTOPILOT_PREFIX}_entry_surface", ""),
    }


def budget_remaining_min() -> int | None:
    if not is_autopilot_active():
        return None
    rem = st.session_state.get(f"{_AUTOPILOT_PREFIX}_budget_remaining_min")
    try:
        return max(0, int(rem))
    except (TypeError, ValueError):
        return None


# ── lifecycle ───────────────────────────────────────────────────────────────


def enable_autopilot(budget_min: int, *, entry_surface: str = "Mission Control") -> None:
    if budget_min not in _BUDGET_OPTIONS:
        raise ValueError(f"budget_min must be one of {_BUDGET_OPTIONS}, got {budget_min}")
    st.session_state[f"{_AUTOPILOT_PREFIX}_enabled"] = True
    st.session_state[f"{_AUTOPILOT_PREFIX}_paused"] = False
    st.session_state[f"{_AUTOPILOT_PREFIX}_budget_total_min"] = budget_min
    st.session_state[f"{_AUTOPILOT_PREFIX}_budget_remaining_min"] = budget_min
    st.session_state[f"{_AUTOPILOT_PREFIX}_steps_completed"] = 0
    st.session_state[f"{_AUTOPILOT_PREFIX}_last_completion_key"] = ""
    st.session_state[f"{_AUTOPILOT_PREFIX}_entry_surface"] = entry_surface
    _emit_autopilot_started(budget_min)


def pause_autopilot() -> None:
    if not is_autopilot_active():
        return
    st.session_state[f"{_AUTOPILOT_PREFIX}_paused"] = True
    _emit_autopilot_paused("user_paused")


def resume_autopilot() -> None:
    if not is_autopilot_active():
        return
    st.session_state[f"{_AUTOPILOT_PREFIX}_paused"] = False
    _emit_autopilot_resumed()


def step_completed(
    decision_id: str = "",
    *,
    step_latency_ms: int = 0,
    completion_key: str = "",
) -> None:
    """Call after user completes one step via checkpoint primary button.
    Decrements budget, increments step counter. Deduplication is on
    completion_key (the learning-result identity), not decision_id:
    two distinct completions with the same SSR decision_id are still
    two separate steps. Refresh/resume with the same completion_key
    never re-executes.
    """
    if not is_autopilot_active() or is_autopilot_paused():
        return

    ck = str(completion_key or "").strip()
    if ck:
        last_ck = str(st.session_state.get(f"{_AUTOPILOT_PREFIX}_last_completion_key") or "")
        if ck == last_ck:
            return
        st.session_state[f"{_AUTOPILOT_PREFIX}_last_completion_key"] = ck

    st.session_state[f"{_AUTOPILOT_PREFIX}_steps_completed"] = (
        st.session_state.get(f"{_AUTOPILOT_PREFIX}_steps_completed", 0) + 1
    )

    current = max(0, int(st.session_state.get(f"{_AUTOPILOT_PREFIX}_budget_remaining_min", 0) or 0))
    new_budget = max(0, current - _STEP_COST_MIN)
    st.session_state[f"{_AUTOPILOT_PREFIX}_budget_remaining_min"] = new_budget

    _emit_autopilot_step(str(decision_id or ""), new_budget, step_latency_ms)

    if new_budget <= 0:
        _finish_autopilot_internal("budget_exhausted")


def finish_autopilot(reason: str = "user_finished") -> None:
    """User-initiated finish («Готово») or manual navigation."""
    if is_autopilot_active():
        _finish_autopilot_internal(reason)


def _finish_autopilot_internal(reason: str) -> None:
    total = st.session_state.get(f"{_AUTOPILOT_PREFIX}_budget_total_min", 0)
    remaining = max(0, int(st.session_state.get(f"{_AUTOPILOT_PREFIX}_budget_remaining_min", 0) or 0))
    steps = st.session_state.get(f"{_AUTOPILOT_PREFIX}_steps_completed", 0)
    _emit_autopilot_finished(reason, remaining, steps)
    _clear_autopilot_state()


def _clear_autopilot_state() -> None:
    for key_suffix in (
        "enabled", "paused", "budget_total_min", "budget_remaining_min",
        "steps_completed", "last_completion_key", "entry_surface",
    ):
        st.session_state.pop(f"{_AUTOPILOT_PREFIX}_{key_suffix}", None)


# ── session tape ────────────────────────────────────────────────────────────


def _emit_autopilot_started(budget_min: int) -> None:
    try:
        from app.session_tape import append_event
        sid = str(st.session_state.get("_session_tape_id") or "").strip()
        if not sid:
            return
        append_event(sid, "autopilot_started", {
            "budget_min": budget_min,
            "surface": str(st.session_state.get(f"{_AUTOPILOT_PREFIX}_entry_surface", "")),
        })
    except Exception:  # noqa: BLE001 - tape must never block UI
        pass


def _emit_autopilot_step(decision_id: str, budget_remaining: int, latency_ms: int) -> None:
    try:
        from app.session_tape import append_event
        sid = str(st.session_state.get("_session_tape_id") or "").strip()
        if not sid:
            return
        append_event(sid, "autopilot_step", {
            "decision_id": str(decision_id),
            "budget_remaining_min": budget_remaining,
            "latency_ms": latency_ms,
            "surface": str(st.session_state.get(f"{_AUTOPILOT_PREFIX}_entry_surface", "")),
        })
    except Exception:  # noqa: BLE001 - tape must never block UI
        pass


def _emit_autopilot_paused(reason: str) -> None:
    try:
        from app.session_tape import append_event
        sid = str(st.session_state.get("_session_tape_id") or "").strip()
        if not sid:
            return
        remaining = max(0, int(st.session_state.get(f"{_AUTOPILOT_PREFIX}_budget_remaining_min", 0) or 0))
        steps = st.session_state.get(f"{_AUTOPILOT_PREFIX}_steps_completed", 0)
        append_event(sid, "autopilot_paused", {
            "reason": reason,
            "budget_remaining_min": remaining,
            "steps_completed": steps,
        })
    except Exception:  # noqa: BLE001 - tape must never block UI
        pass


def _emit_autopilot_resumed() -> None:
    try:
        from app.session_tape import append_event
        sid = str(st.session_state.get("_session_tape_id") or "").strip()
        if not sid:
            return
        remaining = max(0, int(st.session_state.get(f"{_AUTOPILOT_PREFIX}_budget_remaining_min", 0) or 0))
        append_event(sid, "autopilot_resumed", {
            "budget_remaining_min": remaining,
        })
    except Exception:  # noqa: BLE001 - tape must never block UI
        pass


def _emit_autopilot_finished(reason: str, budget_remaining: int, steps_completed: int) -> None:
    try:
        from app.session_tape import append_event
        sid = str(st.session_state.get("_session_tape_id") or "").strip()
        if not sid:
            return
        append_event(sid, "autopilot_finished", {
            "reason": reason,
            "budget_remaining_min": budget_remaining,
            "steps_completed": steps_completed,
        })
    except Exception:  # noqa: BLE001 - tape must never block UI
        pass
