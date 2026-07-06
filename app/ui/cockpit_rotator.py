"""Cockpit activity rotator (E30 A2) — каркас слотов без реальных вызовов tutor/quiz."""

from __future__ import annotations

from typing import Final

import streamlit as st

SESSION_KEY: Final[str] = "cockpit_rotator_slot_index"
DEFAULT_SLOTS: Final[tuple[str, ...]] = ("flashcards", "micro_quiz", "tutor_chat", "living_konspekt")
SLOT_LABELS: Final[dict[str, str]] = {
    "flashcards": "Flashcards",
    "micro_quiz": "Micro quiz",
    "tutor_chat": "Tutor chat",
    "living_konspekt": "10 минут: пополни конспект недели",
}


def normalize_slot_index(raw: object, n: int | None = None) -> int:
    """Привести сырой индекс к диапазону [0, n)."""
    size = n if n is not None else len(DEFAULT_SLOTS)
    if size < 1:
        return 0
    try:
        return int(raw) % size
    except (TypeError, ValueError):
        return 0


def slot_id_at(index: int) -> str:
    return DEFAULT_SLOTS[normalize_slot_index(index)]


def next_slot_index(current: int, step: int = 1) -> int:
    n = len(DEFAULT_SLOTS)
    return normalize_slot_index(current + step, n)


def _session_slot_index() -> int:
    return normalize_slot_index(st.session_state.get(SESSION_KEY, 0))


def advance_slot(step: int = 1) -> str:
    """Сдвигает индекс слота и возвращает id активного слота."""
    cur = _session_slot_index()
    nxt = next_slot_index(cur, step)
    st.session_state[SESSION_KEY] = nxt
    return DEFAULT_SLOTS[nxt]


def current_slot() -> str:
    return DEFAULT_SLOTS[_session_slot_index()]


def slot_label(slot_id: str) -> str:
    return SLOT_LABELS.get(slot_id, slot_id)


def render_rotator_panel() -> None:
    """Простая панель ротации в центре кабины (stub UI)."""
    slot = current_slot()
    st.caption(f"Активный слот: **{slot_label(slot)}** (черновик ротации)")
    bc = st.columns(2)
    with bc[0]:
        if st.button("← Назад", key="cockpit_rotator_prev"):
            advance_slot(-1)
            st.rerun()
    with bc[1]:
        if st.button("Далее →", key="cockpit_rotator_next"):
            advance_slot(1)
            st.rerun()


__all__ = [
    "DEFAULT_SLOTS",
    "SESSION_KEY",
    "advance_slot",
    "current_slot",
    "next_slot_index",
    "normalize_slot_index",
    "render_rotator_panel",
    "slot_label",
    "slot_id_at",
]
