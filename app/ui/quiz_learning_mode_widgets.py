"""Выбор режима шаблона квиза для вызовов POST /quiz/generate из Streamlit."""

from __future__ import annotations

import streamlit as st

# Согласовано с app.prompts.KNOWN_QUIZ_LEARNING_MODES (без auto — только явные профили API)
SCOPED_QUIZ_LEARNING_MODE_LABELS: dict[str, str] = {
    "default": "Нейтральный",
    "understand_topic": "Освоение темы",
    "exam_prep": "Экзамен",
    "solve_homework": "Домашка и задачи",
}


def render_scoped_quiz_learning_mode_select(*, session_key: str, label: str = "Шаблон промпта квиза") -> None:
    """Сохраняет выбор в ``st.session_state[session_key]``."""
    opts = list(SCOPED_QUIZ_LEARNING_MODE_LABELS.keys())
    st.selectbox(
        label,
        options=opts,
        format_func=lambda k: SCOPED_QUIZ_LEARNING_MODE_LABELS[k],
        key=session_key,
        help="Стиль формулировок при генерации теста (соответствует learning_mode в API).",
    )


def scoped_quiz_learning_mode_value(session_key: str) -> str:
    v = st.session_state.get(session_key)
    if isinstance(v, str) and v in SCOPED_QUIZ_LEARNING_MODE_LABELS:
        return v
    return "default"
