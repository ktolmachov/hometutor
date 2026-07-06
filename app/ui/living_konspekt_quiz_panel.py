"""Scoped quiz panel for Living Konspekt workbench rows."""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.living_konspekt_scoped_quiz import generate_living_konspekt_quiz
from app.ui.helpers import format_request_error
from app.ui.quiz_learning_mode_widgets import (
    render_scoped_quiz_learning_mode_select,
    scoped_quiz_learning_mode_value,
)
from app.ui.scoped_quiz import render_scoped_self_check_quiz


def render_living_konspekt_quiz_panel(rows: list[dict[str, Any]], *, title: str, goal: dict[str, Any]) -> None:
    st.markdown("### ✅ Проверить себя по сборке")
    st.caption("Вопросы строятся только из текстов фрагментов в текущей корзине, без повторного поиска по индексу.")
    lm_key = "living_konspekt_scoped_quiz_lm"
    render_scoped_quiz_learning_mode_select(session_key=lm_key)
    if st.button("Сгенерировать 6 вопросов по моей сборке", key="living_konspekt_scoped_quiz_btn", type="primary"):
        try:
            quiz = generate_living_konspekt_quiz(
                rows,
                title=title,
                goal=goal,
                num_questions=6,
                difficulty="adaptive",
                learning_mode=scoped_quiz_learning_mode_value(lm_key),
            )
        except Exception as exc:  # noqa: BLE001 - user-facing generation error in Streamlit
            st.session_state["living_konspekt_scoped_quiz_err"] = format_request_error(exc)
        else:
            if quiz.get("success"):
                st.session_state["living_konspekt_scoped_quiz"] = quiz
                st.session_state.pop("living_konspekt_scoped_quiz_err", None)
                try:
                    from app.ui_events import track_event

                    track_event("living_konspekt_scoped_quiz_generated", {"sections": len(rows)})
                except Exception:  # noqa: BLE001 - analytics must not block quiz generation
                    pass
            else:
                st.session_state["living_konspekt_scoped_quiz_err"] = str(quiz.get("error") or "Quiz не сгенерирован.")
        st.rerun()

    err = st.session_state.pop("living_konspekt_scoped_quiz_err", None)
    if err:
        st.warning(err)
    data = st.session_state.get("living_konspekt_scoped_quiz")
    if isinstance(data, dict) and data.get("questions"):
        render_scoped_self_check_quiz(
            data["questions"],
            source_key="living_konspekt_scoped_quiz",
            quiz_meta=data,
        )


__all__ = ["render_living_konspekt_quiz_panel"]
