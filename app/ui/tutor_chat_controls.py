"""Session and depth controls for tutor chat UI."""

from __future__ import annotations

import re
import uuid
from typing import Any
import streamlit as st


def render_tutor_depth_switcher() -> None:
    """Глубина ответа: short | examples | deep (human labels only — W9)."""
    st.markdown("##### Глубина ответа")
    opts = ["short", "examples", "deep"]
    # W9: no JSON/API terminology in normal UI.
    labels = {
        "short": "Кратко",
        "examples": "С объяснением",
        "deep": "Глубоко",
    }
    cur = st.session_state.get("tutor_answer_depth", "examples")
    if cur not in opts:
        cur = "examples"
    sel = st.radio(
        "Глубина ответа",
        opts,
        index=opts.index(cur),
        format_func=lambda x: labels[x],
        horizontal=True,
        label_visibility="collapsed",
    )
    st.session_state["tutor_answer_depth"] = sel
    st.caption("Влияет на следующий ответ тьютора: объём и детализация объяснения.")


def render_tutor_extra_controls(session_id: str | None = None) -> None:
    """Extra controls: quiz template, learner profile, focus mode."""
    _quiz_tpl_labels = {
        "auto": "Как цель обучения (авто)",
        "default": "Нейтральный шаблон",
        "understand_topic": "Освоение темы",
        "exam_prep": "Экзамен",
        "solve_homework": "Домашка и задачи",
    }
    with st.expander("Дополнительно: шаблон квиза, профиль, фокус", expanded=False):
        st.selectbox(
            "Шаблон промпта квиза (micro-quiz после ответа тьютора)",
            options=list(_quiz_tpl_labels.keys()),
            format_func=lambda k: _quiz_tpl_labels[k],
            key="quiz_learning_mode",
            help="Авто: стиль вопросов совпадает с выбранной целью сессии (Понять тему / Экзамен / Задание).",
        )
        try:
            from app.ui.learner_profile_panel import render_personalized_learner_panel
            render_personalized_learner_panel(session_id=session_id, variant="compact")
        except Exception as _exc:  # noqa: BLE001 - compact rendering panel is optional in UI
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            pass
        st.checkbox(
            "Фокус: скрыть прогресс графа и сводку (только чат и действия)",
            key="tutor_focus_mode",
        )
        st.caption(
            "Policy-диагностика и сброс сессии (эксперт) — в нижнем блоке чата, без изменения обычного потока."
        )


def format_tutor_session_title(session_row: dict[str, Any] | None, *, session_id: str = "") -> str:
    """Human-readable session label (topic/preview · date) — not raw UUID (W9)."""
    row = session_row if isinstance(session_row, dict) else {}
    lu = str(row.get("last_updated") or "").replace("T", " ")[:16]
    topic = str(row.get("topic") or row.get("current_topic") or "").strip()
    pv = str(row.get("last_user_preview") or "").strip()
    head = topic or pv
    if head:
        short = head if len(head) <= 48 else head[:45] + "…"
        return f"{short}" + (f" · {lu}" if lu else "")
    if lu:
        return f"Чат · {lu}"
    sid = str(session_id or row.get("session_id") or "").strip()
    return f"Новый чат" if not sid else f"Чат · {sid[:6]}"


def render_tutor_session_selector(sessions: list[dict[str, Any]], current_session_id: str) -> str:
    """Session switcher and 'New Chat' button. Returns the selected or new session_id."""
    stored_ids = [s["session_id"] for s in sessions]
    _sess_by_id = {s["session_id"]: s for s in sessions}
    
    session_options = [current_session_id] + [x for x in stored_ids if x != current_session_id]

    def _format_tutor_session_pick(sid_pick: str) -> str:
        if sid_pick not in stored_ids:
            return "Новый чат"
        row = _sess_by_id.get(sid_pick) or {}
        return format_tutor_session_title(row, session_id=sid_pick)

    c1, c2 = st.columns([2, 1])
    with c1:
        pick = st.selectbox(
            "Сессия",
            options=session_options,
            index=0,
            format_func=_format_tutor_session_pick,
            key="tutor_session_select",
        )
        if pick != current_session_id:
            st.session_state["tutor_session_id"] = pick
            st.session_state.pop("tutor_last_nba", None)
            st.session_state.pop("tutor_last_graph", None)
            st.session_state.pop("tutor_micro_quiz_active", None)
            st.rerun()
    with c2:
        if st.button("Новый чат", key="tutor_new_session", width='stretch'):
            new_id = str(uuid.uuid4())
            st.session_state["tutor_session_id"] = new_id
            st.session_state.pop("tutor_last_nba", None)
            st.session_state.pop("tutor_last_graph", None)
            st.session_state.pop("tutor_micro_quiz_active", None)
            st.rerun()
            return new_id
    
    return pick


def render_tutor_progress_bar(pct: int, mp: float) -> None:
    """Unified progress representation."""
    if not st.session_state.get("tutor_focus_mode"):
        avg = (pct + mp) / 200.0
        st.progress(min(1.0, avg), text=f"Прогресс: покрытие графа {pct}% · mastery {mp:.0f}%")
