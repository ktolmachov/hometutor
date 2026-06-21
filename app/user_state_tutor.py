from __future__ import annotations
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Any
import re
import hashlib

from app.user_state_core import *

def upsert_tutor_learning_resume(
    *,
    session_id: str,
    topic: str,
    mastery_level: str,
    last_action_kind: str,
    last_action_label: str,
    quiz_feedback: dict[str, Any] | None = None,
    recommended_next: dict[str, Any] | None = None,
    due_reviews_count: int = 0,
    index_version: str | None = None,
) -> None:
    """Один снимок «где остановились» для главного экрана (связан с session_store.session_id)."""

    sid = (session_id or "").strip()
    if not sid:
        return
    ts = _utc_now_iso()
    qfb = json.dumps(quiz_feedback, ensure_ascii=False) if quiz_feedback else None
    rnj = json.dumps(recommended_next, ensure_ascii=False) if recommended_next else None
    iv = (index_version or "").strip() or None

    def _work(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            INSERT INTO tutor_learning_resume(
                id, session_id, topic, mastery_level, last_action_kind, last_action_label,
                quiz_feedback_json, recommended_next_json, due_reviews_count, updated_at, index_version
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                session_id = excluded.session_id,
                topic = excluded.topic,
                mastery_level = excluded.mastery_level,
                last_action_kind = excluded.last_action_kind,
                last_action_label = excluded.last_action_label,
                quiz_feedback_json = excluded.quiz_feedback_json,
                recommended_next_json = excluded.recommended_next_json,
                due_reviews_count = excluded.due_reviews_count,
                updated_at = excluded.updated_at,
                index_version = excluded.index_version
            """,
            (
                sid,
                (topic or "").strip() or "general",
                (mastery_level or "intermediate").strip() or "intermediate",
                (last_action_kind or "").strip() or "unknown",
                (last_action_label or "").strip() or None,
                qfb,
                rnj,
                max(0, int(due_reviews_count or 0)),
                ts,
                iv,
            ),
        )
        conn.commit()

    _with_db(_work, write=True)


def get_tutor_learning_resume() -> dict[str, Any] | None:
    def _work(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM tutor_learning_resume WHERE id = 1").fetchone()
        if not row:
            return None
        d = dict(row)
        qfj = d.pop("quiz_feedback_json", None)
        rnj = d.pop("recommended_next_json", None)
        d["quiz_feedback"] = None
        d["recommended_next"] = None
        if qfj:
            try:
                d["quiz_feedback"] = json.loads(qfj)
            except (json.JSONDecodeError, TypeError):
                d["quiz_feedback"] = None
        if rnj:
            try:
                d["recommended_next"] = json.loads(rnj)
            except (json.JSONDecodeError, TypeError):
                d["recommended_next"] = None
        return d

    return _with_db(_work)


def clear_tutor_learning_resume() -> None:
    def _work(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM tutor_learning_resume WHERE id = 1")
        conn.commit()

    _with_db(_work, write=True)


def _normalize_lgs_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:_MAX_LGS_STR]


def _normalize_lgs_topic(value: Any) -> str:
    s = str(value or "").strip()
    return s or "general"


def _normalize_lgs_time_budget_min(value: Any) -> int | None:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < 1 or n > 240:
        return None
    return n


def _normalize_lgs_style(value: Any) -> str:
    s = str(value or "balanced").strip().lower() or "balanced"
    return s


def _normalize_lgs_learning_goal(value: Any) -> str:
    s = str(value or "understand_topic").strip().lower() or "understand_topic"
    return s


def normalize_learner_goal_snapshot_payload(
    *,
    topic: Any = None,
    subtopic: Any = None,
    target_level: Any = None,
    desired_outcome: Any = None,
    time_budget_min: Any = None,
    preferred_style: Any = None,
    learning_goal: Any = None,
) -> dict[str, Any]:
    """Нормализованный снимок в форме ``goal_context`` (E24-A) и стабильные defaults."""
    return {
        "topic": _normalize_lgs_topic(topic),
        "subtopic": _normalize_lgs_optional_str(subtopic),
        "target_level": _normalize_lgs_optional_str(target_level),
        "desired_outcome": _normalize_lgs_optional_str(desired_outcome),
        "time_budget_min": _normalize_lgs_time_budget_min(time_budget_min),
        "preferred_style": _normalize_lgs_style(preferred_style),
        "learning_goal": _normalize_lgs_learning_goal(learning_goal),
    }


def upsert_learner_goal_snapshot(
    *,
    topic: Any = None,
    subtopic: Any = None,
    target_level: Any = None,
    desired_outcome: Any = None,
    time_budget_min: Any = None,
    preferred_style: Any = None,
    learning_goal: Any = None,
) -> dict[str, Any]:
    """Сохраняет один снимок цели (id=1). Возвращает ``schema_version``, ``updated_at``, ``goal_context``."""

    gc = normalize_learner_goal_snapshot_payload(
        topic=topic,
        subtopic=subtopic,
        target_level=target_level,
        desired_outcome=desired_outcome,
        time_budget_min=time_budget_min,
        preferred_style=preferred_style,
        learning_goal=learning_goal,
    )
    ts = _utc_now_iso()
    sv = LEARNER_GOAL_SNAPSHOT_SCHEMA_VERSION

    def _work(conn: sqlite3.Connection) -> dict[str, Any]:
        conn.execute(
            """
            INSERT INTO learner_goal_snapshot(
                id, schema_version, topic, subtopic, target_level, desired_outcome,
                time_budget_min, preferred_style, learning_goal, updated_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                schema_version = excluded.schema_version,
                topic = excluded.topic,
                subtopic = excluded.subtopic,
                target_level = excluded.target_level,
                desired_outcome = excluded.desired_outcome,
                time_budget_min = excluded.time_budget_min,
                preferred_style = excluded.preferred_style,
                learning_goal = excluded.learning_goal,
                updated_at = excluded.updated_at
            """,
            (
                sv,
                gc["topic"],
                gc["subtopic"],
                gc["target_level"],
                gc["desired_outcome"],
                gc["time_budget_min"],
                gc["preferred_style"],
                gc["learning_goal"],
                ts,
            ),
        )
        conn.commit()
        return {
            "schema_version": sv,
            "updated_at": ts,
            "goal_context": gc,
        }

    return _with_db(_work, write=True)


def get_learner_goal_snapshot() -> dict[str, Any] | None:
    """Возвращает ``{schema_version, updated_at, goal_context}`` или ``None`` если строки нет."""

    def _work(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM learner_goal_snapshot WHERE id = 1").fetchone()
        if not row:
            return None
        d = dict(row)
        gc = {
            "topic": _normalize_lgs_topic(d.get("topic")),
            "subtopic": _normalize_lgs_optional_str(d.get("subtopic")),
            "target_level": _normalize_lgs_optional_str(d.get("target_level")),
            "desired_outcome": _normalize_lgs_optional_str(d.get("desired_outcome")),
            "time_budget_min": _normalize_lgs_time_budget_min(d.get("time_budget_min")),
            "preferred_style": _normalize_lgs_style(d.get("preferred_style")),
            "learning_goal": _normalize_lgs_learning_goal(d.get("learning_goal")),
        }
        return {
            "schema_version": int(d.get("schema_version") or LEARNER_GOAL_SNAPSHOT_SCHEMA_VERSION),
            "updated_at": str(d["updated_at"]),
            "goal_context": gc,
        }

    return _with_db(_work)


def clear_learner_goal_snapshot() -> None:
    def _work(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM learner_goal_snapshot WHERE id = 1")
        conn.commit()

    _with_db(_work, write=True)


def learner_goal_snapshot_api_empty() -> dict[str, Any]:
    """Тело ответа GET при отсутствии снимка (новая БД / строка не создана)."""
    return {"schema_version": None, "updated_at": None, "goal_context": None}


def get_tutor_learner_profile() -> dict[str, Any]:
    """Persisted lightweight learner model for tutor orchestration."""
    raw = get_kv("tutor_learner_profile_json")
    base = dict(_DEFAULT_TUTOR_LEARNER_PROFILE)
    if not raw:
        return base
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return base
    if not isinstance(data, dict):
        return base
    merged = {**base, **data}
    merged["recent_topics"] = [
        str(x).strip() for x in (merged.get("recent_topics") or []) if str(x).strip()
    ][:8]
    merged["weak_concepts"] = [
        str(x).strip() for x in (merged.get("weak_concepts") or []) if str(x).strip()
    ][:8]
    try:
        merged["sessions_count"] = max(0, int(merged.get("sessions_count") or 0))
    except (TypeError, ValueError):
        merged["sessions_count"] = 0
    try:
        merged["due_review_count"] = max(0, int(merged.get("due_review_count") or 0))
    except (TypeError, ValueError):
        merged["due_review_count"] = 0
    return merged


def get_learner_profile(
    user_id: str | None = None,
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Персонализированная модель 19.5 (JSON). Для оркестратора см. ``merge_personalized_into_learner_profile``."""
    from app.learner_model_service import get_personalized_learner_profile

    return get_personalized_learner_profile(user_id, session_id=session_id).model_dump(mode="json")


def save_learner_profile(user_id: str | None, data: dict[str, Any]) -> None:
    """Сохранить снимок Personalized Learner Model (делегирует ``learner_model_service``)."""
    from app.learner_model_service import save_learner_profile as _save_plm

    _save_plm(user_id, data)


def set_tutor_learner_profile(profile: dict[str, Any]) -> dict[str, Any]:
    current = get_tutor_learner_profile()
    merged = {**current, **(profile or {})}
    merged["preferred_style"] = (
        str(merged.get("preferred_style") or "balanced").strip().lower() or "balanced"
    )
    if merged["preferred_style"] not in _PREFERRED_STYLES:
        merged["preferred_style"] = "balanced"
    merged["last_route"] = str(merged.get("last_route") or "standard").strip() or "standard"
    merged["last_focus_topic"] = str(merged.get("last_focus_topic") or "general").strip() or "general"
    merged["recent_topics"] = [
        str(x).strip() for x in (merged.get("recent_topics") or []) if str(x).strip()
    ][:8]
    merged["weak_concepts"] = [
        str(x).strip() for x in (merged.get("weak_concepts") or []) if str(x).strip()
    ][:8]
    merged["updated_at"] = _utc_now_iso()
    set_kv("tutor_learner_profile_json", json.dumps(merged, ensure_ascii=False))
    return merged


def update_tutor_learner_profile_from_session(session_state: dict[str, Any] | None) -> dict[str, Any]:
    state = session_state or {}
    learner_profile = state.get("learner_profile") if isinstance(state, dict) else {}
    if not isinstance(learner_profile, dict):
        learner_profile = {}
    current = get_tutor_learner_profile()
    focus_topic = str(learner_profile.get("focus_topic") or current.get("last_focus_topic") or "general").strip() or "general"
    recent_topics = [focus_topic] + list(current.get("recent_topics") or [])
    deduped_topics: list[str] = []
    for topic in recent_topics:
        t = str(topic or "").strip()
        if t and t not in deduped_topics:
            deduped_topics.append(t)
        if len(deduped_topics) >= 8:
            break
    return set_tutor_learner_profile(
        {
            "sessions_count": int(current.get("sessions_count") or 0) + 1,
            "preferred_style": learner_profile.get("preferred_style") or current.get("preferred_style") or "balanced",
            "last_route": learner_profile.get("route") or current.get("last_route") or "standard",
            "last_focus_topic": focus_topic,
            "weak_concepts": learner_profile.get("weak_concepts") or current.get("weak_concepts") or [],
            "due_review_count": learner_profile.get("due_review_count") or current.get("due_review_count") or 0,
            "recent_topics": deduped_topics,
        }
    )


def get_weekly_goals_state() -> dict[str, Any]:
    """
    Цели и факт за текущую ISO-неделю (UTC).
    Хранится в app_kv как JSON: week_id, targets, done.
    """

    cur_w = _iso_week_id()
    default: dict[str, Any] = {
        "week_id": cur_w,
        "targets": dict(_DEFAULT_WEEKLY_TARGETS),
        "done": {k: 0 for k in _WEEKLY_GOAL_KEYS},
    }
    raw = get_kv("weekly_goals_json")
    if not raw:
        return default
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default
    if not isinstance(data, dict):
        return default
    if data.get("week_id") != cur_w:
        merged_t = dict(_DEFAULT_WEEKLY_TARGETS)
        old_t = data.get("targets")
        if isinstance(old_t, dict):
            for k in _WEEKLY_GOAL_KEYS:
                if k in old_t:
                    try:
                        merged_t[k] = max(1, int(old_t[k]))
                    except (TypeError, ValueError):
                        pass
        data = {
            "week_id": cur_w,
            "targets": merged_t,
            "done": {k: 0 for k in _WEEKLY_GOAL_KEYS},
        }
        set_kv("weekly_goals_json", json.dumps(data, ensure_ascii=False))
    tgt = data.get("targets")
    if not isinstance(tgt, dict):
        data["targets"] = dict(_DEFAULT_WEEKLY_TARGETS)
    else:
        for k in _WEEKLY_GOAL_KEYS:
            if k not in tgt:
                tgt[k] = _DEFAULT_WEEKLY_TARGETS[k]
    done = data.get("done")
    if not isinstance(done, dict):
        data["done"] = {k: 0 for k in _WEEKLY_GOAL_KEYS}
    else:
        for k in _WEEKLY_GOAL_KEYS:
            if k not in done:
                done[k] = 0
    return data


def increment_weekly_progress(key: str, delta: int = 1) -> dict[str, Any]:
    """Увеличить счётчик недели (quizzes, reviews, new_topics)."""

    k = (key or "").strip()
    if k not in _WEEKLY_GOAL_KEYS:
        return get_weekly_goals_state()
    d = max(1, int(delta))
    state = get_weekly_goals_state()
    done = state.setdefault("done", {x: 0 for x in _WEEKLY_GOAL_KEYS})
    try:
        done[k] = int(done.get(k, 0)) + d
    except (TypeError, ValueError):
        done[k] = d
    set_kv("weekly_goals_json", json.dumps(state, ensure_ascii=False))
    return state

