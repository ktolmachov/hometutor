"""Инициализация session_state и уровня тьютора из SQLite."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import streamlit as st

from app import user_state

# Отложенный переход раздела: обработчики ниже ``st.selectbox(..., key="current_view")``
# в ``main.py`` не могут присваивать ``session_state["current_view"]`` напрямую.
PENDING_CURRENT_VIEW_KEY = "_pending_current_view"
FLASHCARDS_REVIEW_RECEIPT_BASELINE_KEY = "flashcards_review_receipt_baseline"
MICRO_QUIZ_RECEIPT_BASELINES_KEY = "_micro_quiz_receipt_baselines"
PROGRESS_FOCUS_SECTION_KEY = "_progress_focus_section"
PROGRESS_FOCUS_STREAK_WEEKLY = "streak_weekly"


def init_state() -> None:
    if "_session_tape_id" not in st.session_state:
        st.session_state["_session_tape_id"] = f"sess-{uuid4().hex[:12]}"
    defaults = {
        "history": [],
        "last_answer": None,
        "last_studied_document": None,
        "hero_prev_gamification": None,
        "last_debug": None,
        "flow_stats": None,
        "topics_catalog": None,
        "last_synthesis": None,
        "last_learning_plan": None,
        "active_topic_id": None,
        "question_draft": "",
        "current_view": "Mission Control",
        "reading_mode": False,
        "focus_view": False,
        "print_view_payload": None,
        "current_topic": None,
        "tutor_cta_action": None,
        "learning_goal": None,
        "quiz_learning_mode": "auto",
        "tutor_answer_depth": "examples",
        "estimated_minutes": None,
        "onboarding_goal_label": None,
        "ui_event_log": [],
        # E24-A / E24-B-2-2: цель сессии; снимок в SQLite подтягивается при старте и сохраняется с CTA «5 минут»
        "tutor_goal_subtopic": None,
        "tutor_goal_target_level": None,
        "tutor_goal_desired_outcome": None,
        "tutor_goal_time_budget_min": None,
        # Flashcards (E12)
        "flashcards_subview": "decks",
        "flashcards_review_queue": [],
        "flashcards_review_index": 0,
        "flashcards_card_flipped": False,
        "flashcards_active_deck_id": None,
        "flashcards_review_stats": {},
        # Interactive tutorial guide
        "tutorial_active": False,
        "tutorial_chapter_index": 0,
        "tutorial_step_index": 0,
        "tutorial_completed_chapters": [],
        "tutorial_progress_hydrated": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def hydrate_tutor_mastery_from_db() -> None:
    """Уровень тьютора (beginner/intermediate/advanced) хранится в SQLite, не только в session_state."""
    if "tutor_mastery_level" in st.session_state:
        st.session_state.setdefault(
            "mastery_level", st.session_state.get("tutor_mastery_level", "intermediate")
        )
        return
    try:
        v = user_state.get_kv("tutor_mastery_level")
        st.session_state["tutor_mastery_level"] = v if v else "intermediate"
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        st.session_state["tutor_mastery_level"] = "intermediate"
    st.session_state.setdefault(
        "mastery_level", st.session_state.get("tutor_mastery_level", "intermediate")
    )


def set_last_studied_document(relative_path: str | None) -> None:
    path = (relative_path or "").strip()
    if path:
        st.session_state["last_studied_document"] = path


_VALID_LEARNING_GOALS_UI = frozenset({"understand_topic", "exam_prep", "solve_homework"})


def goal_snapshot_context_to_session_patch(gc: dict[str, Any]) -> dict[str, Any]:
    """E24-B-2-2: чистое отображение ``goal_context`` → ключи ``st.session_state`` (для тестов)."""
    patch: dict[str, Any] = {}
    sub = gc.get("subtopic")
    if sub:
        patch["tutor_goal_subtopic"] = sub
    tl = gc.get("target_level")
    if tl:
        patch["tutor_goal_target_level"] = tl
    dout = gc.get("desired_outcome")
    if dout:
        patch["tutor_goal_desired_outcome"] = dout
    tbm = gc.get("time_budget_min")
    if tbm is not None:
        patch["tutor_goal_time_budget_min"] = tbm
    lg = gc.get("learning_goal")
    if isinstance(lg, str) and lg.strip().lower() in _VALID_LEARNING_GOALS_UI:
        patch["learning_goal"] = lg.strip().lower()
    raw_topic = gc.get("topic")
    t = str(raw_topic or "").strip()
    if t and t != "general":
        patch["current_topic"] = t
    return patch


def hydrate_tutor_goal_snapshot_once() -> None:
    """Один раз за Streamlit-сессию: подтянуть сохранённую цель из SQLite в session_state."""
    if st.session_state.get("e24_tutor_goal_snapshot_hydrated"):
        return
    st.session_state["e24_tutor_goal_snapshot_hydrated"] = True
    try:
        row = user_state.get_learner_goal_snapshot()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return
    if not row or not isinstance(row.get("goal_context"), dict):
        return
    gc = row["goal_context"]
    patch = goal_snapshot_context_to_session_patch(gc)
    for key, value in patch.items():
        if key == "learning_goal":
            if st.session_state.get("learning_goal"):
                continue
            st.session_state["learning_goal"] = value
            continue
        if key == "current_topic":
            if (st.session_state.get("current_topic") or "").strip():
                continue
            st.session_state["current_topic"] = value
            continue
        cur = st.session_state.get(key)
        if cur is None or (isinstance(cur, str) and not cur.strip()):
            st.session_state[key] = value


def persist_tutor_goal_snapshot_from_session() -> None:
    """Сохранить текущие поля цели из session в ``learner_goal_snapshot`` (E24-B)."""
    try:
        user_state.upsert_learner_goal_snapshot(
            topic=st.session_state.get("current_topic"),
            subtopic=st.session_state.get("tutor_goal_subtopic"),
            target_level=st.session_state.get("tutor_goal_target_level"),
            desired_outcome=st.session_state.get("tutor_goal_desired_outcome"),
            time_budget_min=st.session_state.get("tutor_goal_time_budget_min"),
            preferred_style=user_state.get_preferred_style(),
            learning_goal=st.session_state.get("learning_goal"),
        )
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        pass


def clear_tutor_goal_and_snapshot() -> None:
    """Очистить цель в UI-сессии и удалить строку ``learner_goal_snapshot`` в SQLite (E24-B-2)."""
    try:
        user_state.clear_learner_goal_snapshot()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        pass
    for key in (
        "tutor_goal_subtopic",
        "tutor_goal_target_level",
        "tutor_goal_desired_outcome",
        "tutor_goal_time_budget_min",
    ):
        st.session_state[key] = None
    st.session_state.pop("learning_goal", None)
    st.session_state.pop("e24_tutor_goal_snapshot_hydrated", None)


def persist_tutor_mastery_level(level: str) -> None:
    lv = (level or "intermediate").strip().lower()
    if lv not in ("beginner", "intermediate", "advanced"):
        lv = "intermediate"
    st.session_state["tutor_mastery_level"] = lv
    st.session_state["mastery_level"] = lv
    try:
        user_state.set_kv("tutor_mastery_level", lv)
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        pass
