"""Interactive in-app tutorial guide runtime."""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.tutorial_service import load_tutorial_progress, save_tutorial_progress
from app.ui.tutorial_chapters import CHAPTERS, TutorialChapter, TutorialStep


def _user_id() -> str:
    return str(st.session_state.get("user_id") or "local").strip() or "local"


def _chapter_index_by_id(chapter_id: str) -> int:
    target = str(chapter_id or "").strip()
    for idx, chapter in enumerate(CHAPTERS):
        if chapter.id == target:
            return idx
    return 0


def _current_chapter() -> TutorialChapter:
    idx = max(0, min(int(st.session_state.get("tutorial_chapter_index") or 0), len(CHAPTERS) - 1))
    return CHAPTERS[idx]


def _current_step(chapter: TutorialChapter) -> TutorialStep:
    idx = max(0, min(int(st.session_state.get("tutorial_step_index") or 0), len(chapter.steps) - 1))
    return chapter.steps[idx]


def _persist_now() -> None:
    chapter = _current_chapter()
    save_tutorial_progress(
        _user_id(),
        chapter.id,
        int(st.session_state.get("tutorial_step_index") or 0),
        list(st.session_state.get("tutorial_completed_chapters") or []),
    )


def hydrate_tutorial_progress_once() -> None:
    if st.session_state.get("tutorial_progress_hydrated"):
        return
    st.session_state["tutorial_progress_hydrated"] = True
    payload = load_tutorial_progress(_user_id())
    if not payload:
        return
    st.session_state["tutorial_chapter_index"] = _chapter_index_by_id(payload.get("chapter_id", ""))
    st.session_state["tutorial_step_index"] = int(payload.get("step_index") or 0)
    st.session_state["tutorial_completed_chapters"] = list(payload.get("completed_chapters") or [])
    # Не поднимаем overlay автоматически: позиция сохраняется, вход — «Продолжить тур» на главной.


def start_tutorial(chapter_index: int = 0) -> None:
    st.session_state["tutorial_active"] = True
    st.session_state["tutorial_chapter_index"] = max(0, min(chapter_index, len(CHAPTERS) - 1))
    st.session_state["tutorial_step_index"] = 0
    _persist_now()


def stop_tutorial(*, keep_progress: bool = True) -> None:
    st.session_state["tutorial_active"] = False
    if keep_progress:
        _persist_now()


def _handle_completion(chapter: TutorialChapter) -> None:
    completed = set(st.session_state.get("tutorial_completed_chapters") or [])
    completed.add(chapter.id)
    st.session_state["tutorial_completed_chapters"] = sorted(completed)


def _advance_step() -> None:
    chapter = _current_chapter()
    step_index = int(st.session_state.get("tutorial_step_index") or 0)
    if step_index + 1 < len(chapter.steps):
        st.session_state["tutorial_step_index"] = step_index + 1
    else:
        _handle_completion(chapter)
        chapter_index = int(st.session_state.get("tutorial_chapter_index") or 0)
        if chapter_index + 1 < len(CHAPTERS):
            st.session_state["tutorial_chapter_index"] = chapter_index + 1
            st.session_state["tutorial_step_index"] = 0
        else:
            st.session_state["tutorial_active"] = False
    _jump_to_target_view()
    _persist_now()
    st.rerun()


def _go_back_step() -> None:
    step_index = int(st.session_state.get("tutorial_step_index") or 0)
    chapter_index = int(st.session_state.get("tutorial_chapter_index") or 0)
    if step_index > 0:
        st.session_state["tutorial_step_index"] = step_index - 1
    elif chapter_index > 0:
        prev_ch = CHAPTERS[chapter_index - 1]
        st.session_state["tutorial_chapter_index"] = chapter_index - 1
        st.session_state["tutorial_step_index"] = max(0, len(prev_ch.steps) - 1)
    _jump_to_target_view()
    _persist_now()
    st.rerun()


def _jump_to_target_view() -> None:
    chapter = _current_chapter()
    step = _current_step(chapter)
    if step.target_view:
        st.session_state["current_view"] = step.target_view


def _tutorial_on_dismiss() -> None:
    """Закрытие модалки (X / ESC / клик снаружи) — как «Пропустить», с сохранением прогресса."""
    stop_tutorial(keep_progress=True)


@st.dialog(
    "Интерактивный тур",
    width="medium",
    on_dismiss=_tutorial_on_dismiss,
)
def _interactive_tutorial_modal() -> None:
    chapter = _current_chapter()
    step = _current_step(chapter)
    chapter_idx = int(st.session_state.get("tutorial_chapter_index") or 0)
    step_idx = int(st.session_state.get("tutorial_step_index") or 0)
    level_label = chapter.level.capitalize()
    wow = " ✨" if step.wow else ""
    st.markdown(
        (
            '<div class="tutorial-callout tutorial-callout--dialog">'
            f'<div class="tutorial-kicker">{level_label} · {chapter.summary_ru}</div>'
            f'<h4>{chapter.title_ru} — шаг {step_idx + 1}/{len(chapter.steps)}{wow}</h4>'
            f"<p><strong>{step.title_ru}</strong><br>{step.body_ru}</p>"
            f'<p class="tutorial-us">US: {", ".join(step.us_refs)}</p>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )
    dot_row = " ".join(
        "●" if idx == step_idx else "○" for idx in range(len(chapter.steps))
    )
    st.markdown(
        f'<div class="tutorial-progress-dots">Глава {chapter_idx + 1}/{len(CHAPTERS)} · {dot_row}</div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Назад", key="tutorial_prev", width="stretch"):
            _go_back_step()
    with c2:
        if st.button(step.cta_label_ru, key="tutorial_next", type="primary", width="stretch"):
            _advance_step()
    with c3:
        if st.button("Пропустить", key="tutorial_skip", width="stretch"):
            stop_tutorial(keep_progress=True)
            st.rerun()


def render_tutorial_entry() -> None:
    completed = set(st.session_state.get("tutorial_completed_chapters") or [])
    chapter_idx = int(st.session_state.get("tutorial_chapter_index") or 0)
    total = len(CHAPTERS)
    current = max(1, min(chapter_idx + 1, total))
    st.markdown(
        f'<div class="tutorial-ribbon">Тур: глава {current} из {total} · завершено: {len(completed)}/{total}</div>',
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns([2, 1])
    with c1:
        if st.button(
            f"Пройти интерактивный тур ({total} глав)",
            key="tutorial_start_btn",
            type="primary",
            width="stretch",
        ):
            start_tutorial(chapter_idx if st.session_state.get("tutorial_active") else 0)
            _jump_to_target_view()
            st.rerun()
    with c2:
        if st.button("Продолжить тур", key="tutorial_continue_btn", width="stretch"):
            st.session_state["tutorial_active"] = True
            _jump_to_target_view()
            st.rerun()


def render_tutorial_overlay() -> None:
    if not st.session_state.get("tutorial_active"):
        return
    _interactive_tutorial_modal()


def tutorial_progress_payload() -> dict[str, Any]:
    chapter = _current_chapter()
    return {
        "active": bool(st.session_state.get("tutorial_active")),
        "total_chapters": len(CHAPTERS),
        "chapter_id": chapter.id,
        "chapter_index": int(st.session_state.get("tutorial_chapter_index") or 0),
        "step_index": int(st.session_state.get("tutorial_step_index") or 0),
        "completed_chapters": list(st.session_state.get("tutorial_completed_chapters") or []),
    }

