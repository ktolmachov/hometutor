"""Cockpit activity rotator (E30 A2) — каркас слотов без реальных вызовов tutor/quiz."""

from __future__ import annotations

from typing import Final

import streamlit as st

SESSION_KEY: Final[str] = "cockpit_rotator_slot_index"
DEFAULT_SLOTS: Final[tuple[str, ...]] = ("flashcards", "micro_quiz", "tutor_chat")
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


def living_konspekt_slot_hint(
    rows_count: int,
    *,
    has_goal: bool = False,
    has_saved_artifact: bool = False,
    has_scoped_quiz: bool = False,
) -> str:
    """Deterministic W8 hint for the Living Konspekt cockpit slot."""
    count = max(0, int(rows_count or 0))
    if count < 1:
        return "10 минут: добавь первый раздел в Живой конспект"
    if not has_goal:
        return "10 минут: задай цель конспекта"
    if not has_saved_artifact:
        return "10 минут: собери и сохрани текущую сборку"
    if not has_scoped_quiz:
        return "10 минут: закрепи сборку коротким quiz"
    return "10 минут: пополни конспект недели"


def slot_hint(
    slot_id: str,
    *,
    rows_count: int = 0,
    has_goal: bool = False,
    has_saved_artifact: bool = False,
    has_scoped_quiz: bool = False,
) -> str:
    if slot_id == "living_konspekt":
        return living_konspekt_slot_hint(
            rows_count,
            has_goal=has_goal,
            has_saved_artifact=has_saved_artifact,
            has_scoped_quiz=has_scoped_quiz,
        )
    return slot_label(slot_id)


def _session_slot_hint(slot_id: str) -> str:
    if slot_id != "living_konspekt":
        return slot_label(slot_id)
    try:
        from app import workbench_service

        rows = workbench_service.load_rows()
        goal = workbench_service.load_goal()
    except Exception as exc:  # noqa: BLE001 - cockpit hint must not hide the rotator.
        import logging

        logging.getLogger(__name__).debug("living konspekt slot hint fallback: %s", exc)
        rows = []
        goal = {}
    return slot_hint(
        slot_id,
        rows_count=len(rows),
        has_goal=bool(str(goal.get("text") or "").strip()) if isinstance(goal, dict) else False,
        has_saved_artifact=bool(st.session_state.get("living_konspekt_last_saved")),
        has_scoped_quiz=bool(st.session_state.get("living_konspekt_scoped_quiz_generated")),
    )


def render_rotator_panel() -> None:
    """Простая панель ротации в центре кабины (stub UI)."""
    slot = current_slot()
    hint = _session_slot_hint(slot)
    st.caption(f"Активный слот: **{slot_label(slot)}** (черновик ротации)")
    if hint != slot_label(slot):
        st.caption(hint)
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
    "living_konspekt_slot_hint",
    "slot_hint",
    "slot_label",
    "slot_id_at",
]
