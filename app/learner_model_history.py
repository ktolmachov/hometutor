"""Versioned personalized learner profile history (KV-backed)."""

from __future__ import annotations

import json
from typing import Any

_PERSONALIZED_HISTORY_MAX_ROWS = 120

PERSONALIZED_LEARNER_HISTORY_KV_KEY = "personalized_learner_model_history_json"


def load_profile_history_rows() -> list[dict[str, Any]]:
    from app import learner_model_service as lms

    raw = lms.get_kv(PERSONALIZED_LEARNER_HISTORY_KV_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def get_learner_profile_history(*, limit: int = 20) -> list[dict[str, Any]]:
    """Последние versioned snapshots профиля (старые -> новые)."""
    if limit < 1:
        limit = 1
    rows = load_profile_history_rows()
    if len(rows) <= limit:
        return rows
    return rows[-limit:]


def get_learner_profile_migration_metrics(*, limit: int = 200) -> dict[str, Any]:
    """
    Лёгкие observability-агрегаты по versioned learner profile history.
    """
    history = get_learner_profile_history(limit=limit)
    total = len(history)
    rehydrated = 0
    index_changed = 0
    by_generation: dict[str, int] = {}
    for row in history:
        migration = row.get("state_migration") if isinstance(row.get("state_migration"), dict) else {}
        if migration.get("history_rehydrated") is True:
            rehydrated += 1
        if migration.get("index_changed") is True:
            index_changed += 1
        idx_ctx = row.get("index_context") if isinstance(row.get("index_context"), dict) else {}
        gen = str(idx_ctx.get("generation_id") or "").strip()
        if gen:
            by_generation[gen] = by_generation.get(gen, 0) + 1
    return {
        "window_size": total,
        "rehydrated_total": rehydrated,
        "rehydrated_rate": round(rehydrated / total, 4) if total else None,
        "index_changed_total": index_changed,
        "index_changed_rate": round(index_changed / total, 4) if total else None,
        "generations_seen": len(by_generation),
        "latest_generation_id": (history[-1].get("index_context") or {}).get("generation_id") if total else None,
        "by_generation": by_generation,
    }


def append_profile_history(payload: dict[str, Any]) -> None:
    from app import learner_model_service as lms

    rows = load_profile_history_rows()
    item = {
        "timestamp": payload.get("last_updated"),
        "profile_schema_version": payload.get("profile_schema_version"),
        "index_context": payload.get("index_context") if isinstance(payload.get("index_context"), dict) else {},
        "state_migration": payload.get("state_migration") if isinstance(payload.get("state_migration"), dict) else {},
        "mastery_vector": payload.get("mastery_vector") if isinstance(payload.get("mastery_vector"), dict) else {},
        "sessions_completed": payload.get("sessions_completed"),
        "learning_velocity": payload.get("learning_velocity"),
        "cognitive_load": payload.get("cognitive_load"),
        "emotional_state": payload.get("emotional_state"),
        "optimal_depth": payload.get("optimal_depth"),
    }
    rows.append(item)
    lms.set_kv(
        PERSONALIZED_LEARNER_HISTORY_KV_KEY,
        json.dumps(rows[-_PERSONALIZED_HISTORY_MAX_ROWS :], ensure_ascii=False),
    )
