"""W1: interactive quiz assessment integrity (pre-submit answer leak)."""

from __future__ import annotations

import inspect

from app.ui import interactive_quiz as iq
from app.ui.interactive_quiz import (
    _quiz_answer_correct,
    normalize_true_false_answer,
    presentation_leaks_answer_before_submit,
    quiz_type_label_ru,
)


def test_true_false_labels_map_to_canonical():
    assert normalize_true_false_answer("Верно") == "True"
    assert normalize_true_false_answer("Неверно") == "False"
    assert normalize_true_false_answer("True") == "True"
    q = {"type": "true_false", "correct": "True"}
    assert _quiz_answer_correct(q, "Верно") is True
    assert _quiz_answer_correct(q, "Неверно") is False


def test_type_labels_are_russian():
    assert "выбор" in quiz_type_label_ru("multiple_choice").casefold()
    assert "верно" in quiz_type_label_ru("true_false").casefold()
    assert "порядок" in quiz_type_label_ru("ordering").casefold()


def test_presentation_leak_detector():
    assert presentation_leaks_answer_before_submit("Неверно. Правильно: B") is True
    assert presentation_leaks_answer_before_submit("Выберите ответ") is False


def test_source_has_no_pre_submit_check_expander():
    """Regression: old expander 'Проверка вопроса' scored live before submit."""
    src = inspect.getsource(iq._render_interactive_quiz_tab)
    assert "Проверка вопроса" not in src
    assert "Ответить" in src
    # Correctness feedback only via post-submit helper
    assert "_render_question_feedback" in src
    assert "st.balloons()" in src
    assert "_CELEBRATE_MIN_PCT" in inspect.getsource(iq)


def test_finish_requires_submitted_score_helper():
    src = inspect.getsource(iq._render_interactive_quiz_tab)
    assert "_score_submitted_questions" in src
    # Graph update path must use submitted score, not live radio values alone
    assert "mark_concepts_as_learned" in src


def test_ordering_controls_exist_without_drag_copy():
    src = inspect.getsource(iq._render_ordering_controls)
    assert "↑" in src and "↓" in src
    assert "перетаск" in src.casefold() or "без" in src.casefold()
