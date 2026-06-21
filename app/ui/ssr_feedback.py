"""SSR recommendation misroute feedback (accept / reject / defer).

Persists privacy-safe rows in SQLite via ``app.ssr_feedback_collection`` (no
free-text explanation bodies, no raw learner topics in storage).

Legacy JSONL path (👍/👎 explanation quality) is removed; L5 collection uses
structured actions only.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    from app.smart_study_router import SmartStudyRecommendation

logger = logging.getLogger(__name__)

_SESSION_KEY_PREFIX = "_ssr_fb_done_"  # st.session_state flag after rating


def render_ssr_feedback_widget(
    rec: "SmartStudyRecommendation",
    *,
    key_prefix: str,
    why_now_text: str = "",
    weak_concept: str | None = None,
) -> None:
    """Три кнопки: принять рекомендацию / отклонить / отложить — локальная запись в БД.

    Посle выбора показываем короткое подтверждение (scope сессии Streamlit).
    """
    from app.ssr_feedback_collection import record_ssr_misroute_feedback

    done_key = f"{_SESSION_KEY_PREFIX}{key_prefix}"
    if st.session_state.get(done_key):
        st.caption("✓ Реакция учтена. Спасибо!")
        return

    st.caption("Эта подсказка подходит?")
    cols = st.columns(3)
    actions = [
        ("accept", "Принять", "Согласен с следующим шагом"),
        ("reject", "Не то", "Рекомендация сейчас не подходит"),
        ("defer", "Позже", "Вернуться к этому позже"),
    ]
    for col, (act, label, help_txt) in zip(cols, actions):
        with col:
            if st.button(label, key=f"{key_prefix}_fb_{act}", help=help_txt, width="stretch"):
                try:
                    record_ssr_misroute_feedback(
                        action=act,  # type: ignore[arg-type]
                        rec=rec,
                        weak_concept=weak_concept,
                        why_now_text=why_now_text,
                        session_key=key_prefix,
                    )
                except Exception as exc:  # noqa: BLE001 — не ломаем карточку
                    logger.warning("ssr_misroute_feedback_write_failed", extra={"error": str(exc)})
                st.session_state[done_key] = True
                st.rerun()
