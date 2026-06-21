"""Due review and flashcard cards for the home resume surface."""
from __future__ import annotations

import re
import uuid
from typing import Any

import streamlit as st

from app.due_queue_display import (
    DUE_QUEUE_TOP_LIMIT,
    due_queue_overflow_caption,
    due_queue_preview_caption,
    is_soft_recovery_overflow,
)
from app.knowledge_service import get_active_knowledge_graph
from app.learner_state_scope import count_due_reviews_for_kg, filter_due_reviews_for_kg
from app.spaced_repetition import due_priority_reason
from app.ui.helpers import esc_html
from app.ui.streamlit_activity import days_since_previous_session_start

_DUE_QUEUE_PREVIEW_LIMIT = DUE_QUEUE_TOP_LIMIT


def _due_queue_preview_rows(kg: Any, *, limit: int = _DUE_QUEUE_PREVIEW_LIMIT) -> list[dict[str, Any]]:
    return filter_due_reviews_for_kg(kg, limit=max(1, int(limit)))


def _due_queue_overflow_text(*, due_count: int, shown_count: int) -> str:
    return due_queue_overflow_caption(due_count, shown_count)


def _due_queue_preview_text(
    rows: list[dict[str, Any]] | None,
    *,
    due_count: int,
    shown_limit: int = _DUE_QUEUE_PREVIEW_LIMIT,
) -> str:
    return due_queue_preview_caption(rows, due_count, shown_limit=shown_limit)


def spaced_due_priority_label(row: dict[str, Any]) -> str:
    try:
        score = float(row.get("priority_score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    if score >= 7.0:
        return "высокий"
    if score >= 2.5:
        return "средний"
    return "спокойный"


def _sm2_due_explanation(row: dict) -> str:
    """Короткая строка по SM-2 (без данных квизов)."""
    from datetime import datetime, timezone

    easiness = float(row.get("easiness") or 2.5)
    reps = int(row.get("repetitions") or 0)
    days_overdue = 0
    next_r = row.get("next_review") or ""
    if next_r:
        try:
            nr = datetime.fromisoformat(str(next_r))
            if nr.tzinfo is None:
                nr = nr.replace(tzinfo=timezone.utc)
            days_overdue = max(0, (datetime.now(timezone.utc) - nr).days)
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            pass

    if days_overdue > 7:
        return f"давно не повторялось ({days_overdue} дн. назад)"
    if easiness < 1.8:
        return "низкий easiness — тема даётся сложно"
    if reps == 0:
        return "первое знакомство — нужно закрепить"
    if days_overdue > 0:
        return f"просрочено на {days_overdue} дн."
    return "плановое повторение"


def _concepts_with_recent_quiz_miss(concepts: list[str]) -> set[str]:
    """Концепты с недавними попытками квиза с низким score (если есть записи)."""
    from app.user_state import get_recent_quiz_levels_low_score

    out: set[str] = set()
    for c in concepts:
        if not c:
            continue
        try:
            low = get_recent_quiz_levels_low_score(c, limit=3)
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            continue
        if low:
            out.add(c)
    return out


def _due_reason(
    row: dict,
    *,
    weak_set: set[str] | None = None,
    quiz_miss: set[str] | None = None,
) -> str:
    """US-7.4: почему сейчас — SM-2 + слабые места и ошибки квизов при наличии данных."""
    c = str(row.get("concept") or "").strip()
    weak_set = weak_set or set()
    quiz_miss = quiz_miss or set()
    return due_priority_reason(
        row,
        has_quiz_errors=c in quiz_miss,
        has_low_mastery_signal=c in weak_set,
    )


def render_due_reviews_card() -> None:
    """Карточка due items: get_due_reviews() из spaced_repetition (SQLite)."""
    kg = get_active_knowledge_graph()
    n = count_due_reviews_for_kg(kg)
    st.markdown('<div class="home-dash-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="home-dash-head home-dash-head-due"><h3>🔥 Пора повторить</h3></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="home-dash-body">', unsafe_allow_html=True)
    if n == 0:
        st.success("На сейчас всё повторено — отличная работа.")
        st.caption("Новые повторения появятся по расписанию spaced repetition (SM-2).")
        st.markdown("</div></div>", unsafe_allow_html=True)
        return

    st.caption(
        f"В очереди spaced repetition: **{n}** концепций (SM-2, по `next_review`). "
        f"Ниже — топ до **7** по приоритету очереди (US-7.1)."
    )
    gap_days = days_since_previous_session_start()
    # US-7.2: Soft recovery for overdue users
    if n > 20:
        st.warning(
            f"\U0001f4cb **Recovery-план:** у вас {n} просроченных повторений. "
            f"Рекомендуем проходить по 5\u20137 в день, начиная с самых приоритетных. "
            f"Ниже — топ-7 на сегодня, остальные можно отложить."
        )
        if gap_days is not None and gap_days > 3.0:
            st.info(
                f"Давно не заходили (~{gap_days:.0f} дн. с прошлой сессии): можно **разнести** "
                "хвост очереди на несколько дней — останутся только эти 7, остальные получат новые даты повторения."
            )
            if st.button(
                "Разнести остальные повторения на 5 дней",
                key="due_recovery_spread_v1",
                width='stretch',
                type="secondary",
            ):
                from app.spaced_repetition import defer_overdue_reviews_for_recovery

                try:
                    moved = defer_overdue_reviews_for_recovery(kg, keep_limit=7, stagger_days=5)
                    st.success(f"Отложено записей: **{moved}**. Обновите страницу при необходимости.")
                    st.rerun()
                except Exception as ex:  # noqa: BLE001 - Recovery deferral errors handled gracefully in UI
                    st.error(str(ex))
    if is_soft_recovery_overflow(n):
        st.info("Большая очередь: показаны 7 приоритетных повторений.")
    from app.quiz_adaptive import get_weak_concepts

    due = filter_due_reviews_for_kg(kg, limit=7)
    concepts_shown = [str(r.get("concept") or "").strip() for r in due if str(r.get("concept") or "").strip()]
    weak_set = set(get_weak_concepts(threshold=60, limit=64))
    quiz_miss = _concepts_with_recent_quiz_miss(concepts_shown)
    for i, row in enumerate(due):
        c = str(row.get("concept") or "").strip()
        if not c:
            continue
        pri = spaced_due_priority_label(row)
        safe = re.sub(r"[^\w\-]", "_", c[:24]) or str(i)
        with st.container(border=True):
            reason = _due_reason(row, weak_set=weak_set, quiz_miss=quiz_miss)
            st.markdown(
                f'<div class="home-dash-due-row"><strong>{esc_html(c)}</strong><br/>'
                f'<span style="opacity:0.75;font-size:0.82rem;">{reason}</span><br/>'
                f'<span style="opacity:0.85;font-size:0.85rem;">Приоритет: {pri}</span></div>',
                unsafe_allow_html=True,
            )
            if st.button("Повторить сейчас", key=f"due_home_{i}_{safe}", width='stretch'):
                try:
                    from app.ui_events import track_due_review_started

                    track_due_review_started(c)
                except Exception as _exc:  # noqa: BLE001
                    import logging  # noqa: BLE001
                    logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                    pass
                try:
                    from app.user_state import increment_weekly_progress

                    increment_weekly_progress("reviews", 1)
                except Exception as _exc:  # noqa: BLE001
                    import logging  # noqa: BLE001
                    logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                    pass
                if "tutor_session_id" not in st.session_state:
                    st.session_state["tutor_session_id"] = str(uuid.uuid4())
                st.session_state["current_view"] = "Чат с тьютором"
                st.session_state["tutor_pending_prompt"] = (
                    f"Помоги коротко повторить концепт «{c}» (он в очереди spaced repetition)."
                )
                st.session_state["tutor_pending_session_id"] = st.session_state["tutor_session_id"]
                st.session_state["tutor_cta_action"] = "Повторить сейчас"
                st.session_state["current_topic"] = c
                st.rerun()
    overflow_text = due_queue_overflow_caption(n, len(due))
    if overflow_text:
        st.caption(overflow_text)
        st.markdown("</div></div>", unsafe_allow_html=True)
        return
    st.markdown("</div></div>", unsafe_allow_html=True)


def render_due_flashcards_card() -> None:
    """Карточка главной: flashcards к повторению (SM-2 per-card, E12)."""
    from app.ui.flashcards_read_cache import flashcards_due_count

    try:
        n = flashcards_due_count(())
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        n = 0

    st.markdown('<div class="home-dash-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="home-dash-head home-dash-head-fc"><h3>🃏 Flashcards</h3></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="home-dash-body">', unsafe_allow_html=True)

    if n == 0:
        st.success("Все flashcards повторены — отлично!")
        st.caption("Новые карточки появятся по расписанию SM-2.")
    else:
        st.markdown(
            f"<p>К повторению: <strong>{n} flashcard{'ов' if n > 4 else 'и' if n > 1 else 'а'}</strong></p>",
            unsafe_allow_html=True,
        )
        if st.button(
            f"🔁 Повторить {n} карточек",
            key="fc_due_home_btn",
            width='stretch',
            type="primary",
        ):
            st.session_state["current_view"] = "Flashcards"
            st.session_state["flashcards_subview"] = "review"
            st.session_state["flashcards_review_queue"] = []
            st.rerun()

    st.markdown("</div></div>", unsafe_allow_html=True)
