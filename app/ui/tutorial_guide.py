"""Interactive in-app tutorial guide runtime + first-ten activation flow (W2)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.tutorial_service import (
    load_activation_progress,
    load_tutorial_progress,
    save_activation_progress,
    save_tutorial_progress,
)
from app.ui.tutorial_activation import (
    ACTIVATION_ACTIVE_KEY,
    ACTIVATION_CHECKPOINTS,
    ACTIVATION_DONE_KEY,
    ACTIVATION_INDEX_KEY,
    ACTIVATION_SKIPPED_KEY,
    apply_checkpoint_event,
    current_checkpoint,
    read_activation_state,
    write_activation_state,
)
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
    if payload:
        st.session_state["tutorial_chapter_index"] = _chapter_index_by_id(payload.get("chapter_id", ""))
        st.session_state["tutorial_step_index"] = int(payload.get("step_index") or 0)
        st.session_state["tutorial_completed_chapters"] = list(payload.get("completed_chapters") or [])
    # Не поднимаем full tour автоматически: только manual entry / e2e.
    act = load_activation_progress(_user_id())
    if act:
        st.session_state[ACTIVATION_ACTIVE_KEY] = bool(act.get("active")) and not act.get("skipped")
        st.session_state[ACTIVATION_INDEX_KEY] = int(act.get("step_index") or 0)
        st.session_state[ACTIVATION_DONE_KEY] = list(act.get("completed_ids") or [])
        st.session_state[ACTIVATION_SKIPPED_KEY] = bool(act.get("skipped"))


def start_tutorial(chapter_index: int = 0) -> None:
    """Full chaptered tour (dialog). Manual only — not auto on first run."""
    st.session_state["tutorial_active"] = True
    st.session_state["tutorial_chapter_index"] = max(0, min(chapter_index, len(CHAPTERS) - 1))
    st.session_state["tutorial_step_index"] = 0
    # Full tour and activation are mutually exclusive UI modes.
    st.session_state[ACTIVATION_ACTIVE_KEY] = False
    _persist_now()


def start_activation_flow() -> None:
    """Inline first-ten activation (non-blocking). Default first-run path."""
    st.session_state[ACTIVATION_ACTIVE_KEY] = True
    st.session_state[ACTIVATION_SKIPPED_KEY] = False
    st.session_state["tutorial_active"] = False
    done = list(st.session_state.get(ACTIVATION_DONE_KEY) or [])
    st.session_state[ACTIVATION_DONE_KEY] = done
    cur = current_checkpoint(
        step_index=int(st.session_state.get(ACTIVATION_INDEX_KEY) or 0),
        completed_ids=done,
    )
    if cur and cur.target_view:
        st.session_state["current_view"] = cur.target_view
    _persist_activation()


def _persist_activation() -> None:
    save_activation_progress(
        _user_id(),
        step_index=int(st.session_state.get(ACTIVATION_INDEX_KEY) or 0),
        completed_ids=list(st.session_state.get(ACTIVATION_DONE_KEY) or []),
        active=bool(st.session_state.get(ACTIVATION_ACTIVE_KEY)),
        skipped=bool(st.session_state.get(ACTIVATION_SKIPPED_KEY)),
    )


def note_activation_checkpoint(checkpoint_id: str) -> bool:
    """Product surfaces call this when the real action happened."""
    state = st.session_state
    if state.get(ACTIVATION_SKIPPED_KEY):
        return False
    result = apply_checkpoint_event(
        checkpoint_id,
        active=bool(state.get(ACTIVATION_ACTIVE_KEY)),
        step_index=int(state.get(ACTIVATION_INDEX_KEY) or 0),
        completed_ids=list(state.get(ACTIVATION_DONE_KEY) or []),
        skipped=False,
    )
    write_activation_state(state, result)
    if result.get("advanced") or result.get("finished"):
        _persist_activation()
        return bool(result.get("advanced") or result.get("finished"))
    return False


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
    # Full tour is optional reference — no US/JSON/internal contract ids in learner copy.
    st.markdown(
        (
            '<div class="tutorial-callout tutorial-callout--dialog">'
            f'<div class="tutorial-kicker">{level_label} · {chapter.summary_ru}</div>'
            f'<h4>{chapter.title_ru} — шаг {step_idx + 1}/{len(chapter.steps)}{wow}</h4>'
            f"<p><strong>{step.title_ru}</strong><br>{step.body_ru}</p>"
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
    act = read_activation_state(st.session_state)
    if act.get("active") and act.get("current_title"):
        st.markdown(
            f'<div class="tutorial-ribbon">Первые шаги: {act["current_title"]} · '
            f'{len(act.get("completed_ids") or [])}/{act.get("total") or 7}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="tutorial-ribbon">Справка: глава {current} из {total} · '
            f'завершено: {len(completed)}/{total}</div>',
            unsafe_allow_html=True,
        )
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button(
            "Первые 10 минут",
            key="activation_start_btn",
            type="primary",
            width="stretch",
            help="Короткий путь по реальным действиям (не слайды).",
        ):
            start_activation_flow()
            st.rerun()
    with c2:
        if st.button(
            f"Справочный тур ({total} глав)",
            key="tutorial_start_btn",
            width="stretch",
            help="Полный tour — только по запросу, не автозапуск.",
        ):
            start_tutorial(chapter_idx if st.session_state.get("tutorial_active") else 0)
            _jump_to_target_view()
            st.rerun()
    with c3:
        if st.button("Продолжить тур", key="tutorial_continue_btn", width="stretch"):
            st.session_state["tutorial_active"] = True
            st.session_state[ACTIVATION_ACTIVE_KEY] = False
            _jump_to_target_view()
            st.rerun()


def render_activation_inline() -> None:
    """Non-blocking coach strip beside real UI (not a modal)."""
    if st.session_state.get(ACTIVATION_SKIPPED_KEY):
        return
    if not st.session_state.get(ACTIVATION_ACTIVE_KEY):
        return
    done = list(st.session_state.get(ACTIVATION_DONE_KEY) or [])
    cur = current_checkpoint(
        step_index=int(st.session_state.get(ACTIVATION_INDEX_KEY) or 0),
        completed_ids=done,
    )
    if cur is None:
        st.session_state[ACTIVATION_ACTIVE_KEY] = False
        _persist_activation()
        return
    n = len(ACTIVATION_CHECKPOINTS)
    done_n = len(done)
    st.markdown(
        (
            '<div class="tutorial-callout" style="margin:0.5rem 0 0.75rem 0;'
            'border-left:4px solid rgba(102,126,234,0.85);padding:0.65rem 0.85rem;'
            'border-radius:10px;background:rgba(102,126,234,0.08);">'
            f'<div style="font-size:0.75rem;opacity:0.8">Первые шаги · {done_n + 1}/{n}</div>'
            f"<strong>{cur.title_ru}</strong><br>{cur.body_ru}"
            f'<div style="font-size:0.8rem;margin-top:0.35rem;opacity:0.85">'
            f"Зачем: {cur.reason_ru}<br>Действие: {cur.action_hint_ru}</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )
    b1, b2, b3, b4 = st.columns(4)
    with b1:
        if cur.target_view and st.button(
            "К экрану",
            key="activation_goto_view",
            width="stretch",
        ):
            st.session_state["current_view"] = cur.target_view
            st.rerun()
    with b2:
        if st.button("Назад", key="activation_back", width="stretch", disabled=done_n == 0):
            if done:
                done = done[:-1]
                st.session_state[ACTIVATION_DONE_KEY] = done
                cur2 = current_checkpoint(step_index=0, completed_ids=done)
                st.session_state[ACTIVATION_INDEX_KEY] = (
                    ACTIVATION_CHECKPOINTS.index(cur2) if cur2 else 0
                )
                _persist_activation()
                st.rerun()
    with b3:
        if st.button("Пропустить шаг", key="activation_skip_step", width="stretch"):
            note_activation_checkpoint(cur.id)
            st.rerun()
    with b4:
        if st.button("Выйти", key="activation_exit", width="stretch"):
            st.session_state[ACTIVATION_ACTIVE_KEY] = False
            st.session_state[ACTIVATION_SKIPPED_KEY] = True
            _persist_activation()
            st.rerun()


def render_tutorial_overlay() -> None:
    # Full dialog tour only when explicitly active — never auto for first-run.
    if st.session_state.get("tutorial_active"):
        _interactive_tutorial_modal()
    render_activation_inline()


def tutorial_progress_payload() -> dict[str, Any]:
    chapter = _current_chapter()
    act = read_activation_state(st.session_state)
    return {
        "active": bool(st.session_state.get("tutorial_active")),
        "total_chapters": len(CHAPTERS),
        "chapter_id": chapter.id,
        "chapter_index": int(st.session_state.get("tutorial_chapter_index") or 0),
        "step_index": int(st.session_state.get("tutorial_step_index") or 0),
        "completed_chapters": list(st.session_state.get("tutorial_completed_chapters") or []),
        "activation": act,
    }

