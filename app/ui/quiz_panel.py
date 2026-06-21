"""Панель самопроверки (генерация quiz из текста)."""
from __future__ import annotations

import streamlit as st

from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

_QUIZ_PANEL_MODE_LABELS = {
    "default": "Нейтральный",
    "understand_topic": "Освоение темы",
    "exam_prep": "Экзамен",
    "solve_homework": "Домашка и задачи",
}

_FEEDBACK_ALLOWED_STATUSES = {"correct", "partial", "incorrect"}
_FEEDBACK_STATUS_LABELS = {
    "correct": "Верно",
    "partial": "Частично верно",
    "incorrect": "Неверно",
}
_FEEDBACK_CTA_LABELS = {
    "retry": "Попробовать еще раз",
    "continue_tutor": "Продолжить с тьютором",
    "review": "Перейти к повторению",
    "progress": "Открыть прогресс",
}
_FEEDBACK_BLOCKED_TOKENS = ("router", "debug", "trace", "raw")


def _cta_route_for_status(status: str) -> str:
    if status == "correct":
        return "continue_tutor"
    if status == "partial":
        return "review"
    if status == "incorrect":
        return "retry"
    return "retry"


def normalize_feedback_status(value: str | None) -> str:
    status = str(value or "").strip().lower()
    if status in _FEEDBACK_ALLOWED_STATUSES:
        return status
    return "incorrect"


def short_feedback_explanation(value: str | None, *, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    lowered = text.lower()
    if any(token in lowered for token in _FEEDBACK_BLOCKED_TOKENS):
        return fallback
    first_sentence = text.split(".", 1)[0].strip()
    short = first_sentence or text[:140].strip()
    if len(short) > 160:
        short = short[:157].rstrip() + "..."
    if not short:
        return fallback
    if not short.endswith((".", "!", "?")):
        short += "."
    return short


def _hint_text_from_explanation(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    hint_len = max(30, min(140, len(text) // 2))
    hint = text[:hint_len].strip()
    if not hint:
        return ""
    if not hint.endswith(("...", ".", "!", "?")):
        hint = hint.rstrip() + "..."
    return hint


def _status_for_submission(*, is_correct: bool, hint_used: bool) -> str:
    if is_correct and not hint_used:
        return "correct"
    if hint_used:
        return "partial"
    return "incorrect"


def render_stable_feedback_block(
    *,
    block_key: str,
    status: str,
    explanation: str,
    cta_route: str,
    cta_type: str = "primary",
) -> bool:
    normalized_status = normalize_feedback_status(status)
    cta_label = _FEEDBACK_CTA_LABELS.get(cta_route, _FEEDBACK_CTA_LABELS["retry"])
    status_label = _FEEDBACK_STATUS_LABELS[normalized_status]
    icon = {
        "correct": "✅",
        "partial": "🟡",
        "incorrect": "❌",
    }[normalized_status]

    with st.container():
        if normalized_status == "correct":
            st.success(f"{icon} Статус: {status_label}")
        elif normalized_status == "partial":
            st.warning(f"{icon} Статус: {status_label}")
        else:
            st.error(f"{icon} Статус: {status_label}")
        st.caption(explanation)
        return st.button(
            cta_label,
            key=f"{block_key}_primary_cta",
            type=cta_type,
            width="stretch",
        )


def render_quiz_panel(*, source_key: str, title: str, material: str, min_chars: int = 120) -> None:
    text = (material or "").strip()
    if len(text) < min_chars:
        st.caption("Недостаточно текста для quiz — сначала получите ответ, конспект или план.")
        return
    mode_key = f"quiz_panel_mode_{source_key}"
    st.selectbox(
        "Шаблон промпта квиза",
        options=list(_QUIZ_PANEL_MODE_LABELS.keys()),
        format_func=lambda k: _QUIZ_PANEL_MODE_LABELS[k],
        key=mode_key,
    )
    gen_key = f"quiz_gen_{source_key}"
    if st.button("Сгенерировать quiz (5 вопросов)", key=gen_key, width="stretch", type="secondary"):
        with st.spinner("Генерируем вопросы..."):
            from app import quiz_service  # lazy: avoids llama_index at Synthesis-tab import time
            _lm = str(st.session_state.get(mode_key) or "default").strip().lower()
            questions, err = quiz_service.generate_self_check_quiz(
                text, title=title, learning_mode=_lm
            )
        if err:
            st.error(err)
        else:
            st.session_state[f"quiz_data_{source_key}"] = questions
            st.rerun()
    data = st.session_state.get(f"quiz_data_{source_key}")
    if not data:
        return

    submitted_count = 0
    correct_count = 0
    for i, q in enumerate(data):
        opts = q.get("options") or []
        try:
            ok_idx = int(q.get("correct_index", 0))
        except (TypeError, ValueError):
            ok_idx = -1
        st.markdown(f"**{i + 1}.** {q.get('question', '')}")
        choice_key = f"quiz_panel_choice_{source_key}_{i}"
        choice = st.radio(
            "Варианты",
            options=list(range(len(opts))),
            index=None,
            format_func=lambda j, o=opts: o[j] if j < len(o) else "",
            key=choice_key,
            label_visibility="collapsed",
        )
        result_key = f"quiz_panel_result_{source_key}_{i}"
        submit_key = f"quiz_panel_submit_{source_key}_{i}"
        hint_key = f"quiz_panel_hint_{source_key}_{i}"
        if hint_key not in st.session_state:
            st.session_state[hint_key] = False
        result = st.session_state.get(result_key)
        result_status = str(result.get("status") or "") if isinstance(result, dict) else ""
        hint_text = _hint_text_from_explanation(q.get("explanation"))
        allow_hint = bool(hint_text) and (not isinstance(result, dict) or result_status == "incorrect")
        if allow_hint and not bool(st.session_state.get(hint_key)):
            if st.button("💡 Подсказка", key=f"quiz_panel_hint_btn_{source_key}_{i}", type="secondary", width="stretch"):
                st.session_state[hint_key] = True
                st.rerun()
        if bool(st.session_state.get(hint_key)) and hint_text:
            st.info(f"💡 {hint_text}")

        if st.button("Ответить", key=submit_key, type="secondary", width="stretch"):
            if choice is None:
                st.warning("Выберите вариант ответа перед отправкой.")
            else:
                is_correct = (choice == ok_idx) and ok_idx >= 0
                status = _status_for_submission(
                    is_correct=is_correct,
                    hint_used=bool(st.session_state.get(hint_key)),
                )
                expl = (q.get("explanation") or "").strip()
                if is_correct:
                    expl = "Верно! Это правильный ответ."
                explanation = short_feedback_explanation(
                    expl,
                    fallback="Сверьтесь с разбором темы.",
                )
                st.session_state[result_key] = {
                    "status": status,
                    "explanation": explanation,
                    "cta_route": _cta_route_for_status(status),
                }
                st.rerun()

        result = st.session_state.get(result_key)
        if isinstance(result, dict):
            submitted_count += 1
            if result.get("status") == "correct":
                correct_count += 1
            cta_clicked = render_stable_feedback_block(
                block_key=f"quiz_panel_{source_key}_{i}",
                status=str(result.get("status") or "incorrect"),
                explanation=str(result.get("explanation") or ""),
                cta_route=str(result.get("cta_route") or "retry"),
                cta_type="secondary",
            )
            if cta_clicked:
                route = str(result.get("cta_route") or "retry")
                if route == "retry":
                    st.session_state[f"{source_key}_next_cta_route"] = "retry"
                    st.session_state.pop(result_key, None)
                    st.session_state.pop(choice_key, None)
                    st.session_state.pop(hint_key, None)
                    st.rerun()
                elif route == "continue_tutor":
                    st.session_state[f"{source_key}_next_cta_route"] = route
                    st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
                    st.rerun()
                elif route in {"review", "progress"}:
                    st.session_state[f"{source_key}_next_cta_route"] = route
                    st.session_state[PENDING_CURRENT_VIEW_KEY] = "Прогресс обучения"
                    st.rerun()

    if submitted_count > 0:
        st.caption(f"Правильных ответов: **{correct_count}** из {submitted_count}.")
