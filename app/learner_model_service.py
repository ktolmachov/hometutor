"""
Personalized Learner Model 19.5: когнитивный + эмоциональный + velocity профиль для оркестратора.

Источники: ``quiz_mastery`` (через ``get_mastery_vector``), история сессии (``session_store``),
снимок в ``app_kv`` (ключ ``personalized_learner_model_json``).
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.adaptive_plan import AdaptiveDailyPlan
from app.index_registry import get_index_version_public
from app.knowledge_graph import get_active_knowledge_graph, get_mastery_vector
from app.learner_model_history import (
    PERSONALIZED_LEARNER_HISTORY_KV_KEY,
    append_profile_history,
    get_learner_profile_history,
    get_learner_profile_migration_metrics,
    load_profile_history_rows,
)
from app.user_state import get_kv, set_kv

logger = logging.getLogger(__name__)

PERSONALIZED_LEARNER_KV_KEY = "personalized_learner_model_json"
EMOTIONAL_HEATMAP_KV_KEY = "emotional_heatmap_json"
_EMOTIONAL_HEATMAP_MAX_ROWS = 2000
PERSONALIZED_LEARNER_PROFILE_SCHEMA_VERSION = 2

EmotionalStateLiteral = Literal["frustrated", "engaged", "confident", "bored", "neutral"]
OptimalDepthLiteral = Literal["beginner", "intermediate", "advanced"]


class PersonalizedLearnerModel(BaseModel):
    """Динамическая модель ученика (сериализуется в JSON для оркестратора и KV)."""

    model_config = ConfigDict(extra="ignore")

    user_id: str = "local"
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    mastery_vector: Dict[str, float] = Field(default_factory=dict)

    preferred_styles: Dict[str, float] = Field(
        default_factory=lambda: {"theory": 0.3, "examples": 0.35, "practice": 0.35}
    )

    cognitive_load: float = 0.4
    fatigue_level: float = 0.3

    emotional_state: EmotionalStateLiteral = "neutral"
    confidence_indicator: float = 0.7

    learning_velocity: float = 0.12
    sessions_completed: int = 0

    optimal_depth: OptimalDepthLiteral = "intermediate"
    recommended_session_length_min: int = 15
    best_time_of_day: Optional[str] = None
    profile_schema_version: int = PERSONALIZED_LEARNER_PROFILE_SCHEMA_VERSION
    index_context: Dict[str, Any] = Field(default_factory=dict)
    state_migration: Dict[str, Any] = Field(default_factory=dict)
    is_stale: bool = False


def _parse_iso_ts(raw: str | None) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def get_session_interaction_messages(session_id: str | None, *, last_n: int = 10) -> list[dict[str, Any]]:
    """Сообщения сессии как записи для эвристик (content, response_time секунд при наличии)."""
    if not session_id:
        return []
    from app.session_store import session_store

    messages = list(session_store.get(str(session_id)))
    if not messages:
        return []
    tail = messages[-max(1, last_n) :]
    out: list[dict[str, Any]] = []
    prev_ts: datetime | None = None
    for m in tail:
        role = str(getattr(m, "role", "user") or "user")
        content = str(getattr(m, "content", "") or "")
        meta = getattr(m, "metadata", None) or {}
        rt: float | None = None
        if isinstance(meta, dict):
            raw_rt = meta.get("response_time_ms")
            if raw_rt is None:
                raw_rt = meta.get("response_time")
            if raw_rt is not None:
                try:
                    v = float(raw_rt)
                    # эвристика: значения > 90 считаем миллисекундами
                    rt = v / 1000.0 if v > 90.0 else v
                except (TypeError, ValueError):
                    rt = None
        ts = _parse_iso_ts(getattr(m, "timestamp", None))
        if rt is None and prev_ts is not None and ts is not None and role == "assistant":
            delta = (ts - prev_ts).total_seconds()
            if 0 < delta < 600:
                rt = delta
        if ts is not None:
            prev_ts = ts
        row: dict[str, Any] = {"role": role, "content": content}
        if rt is not None:
            row["response_time"] = rt
        out.append(row)
    return out


def _load_snapshot() -> dict[str, Any]:
    raw = get_kv(PERSONALIZED_LEARNER_KV_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _current_index_context() -> dict[str, Any]:
    try:
        raw = get_index_version_public()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.debug("personalized_learner_index_context_failed", exc_info=True)
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ("index_version", "generation_id", "activated_at"):
        value = raw.get(key)
        if value is not None and value != "":
            out[key] = value
    return out


def _active_concept_ids() -> set[str]:
    try:
        concepts = get_active_knowledge_graph().get_concepts()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.debug("personalized_learner_active_concepts_failed", exc_info=True)
        return set()
    return {
        str(concept_id).strip()
        for concept_id, node in concepts.items()
        if isinstance(node, dict) and str(concept_id).strip()
    }


def _normalize_concept_lookup_text(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _concept_lookup_terms(concept_id: str, node: dict[str, Any]) -> set[str]:
    terms = {_normalize_concept_lookup_text(concept_id)}
    for key in ("label", "name", "title", "display_name", "topic_name"):
        term = _normalize_concept_lookup_text(node.get(key))
        if term:
            terms.add(term)
    for key in ("aliases", "keywords", "key_concepts"):
        values = node.get(key)
        if isinstance(values, (list, tuple, set)):
            terms.update(_normalize_concept_lookup_text(item) for item in values if _normalize_concept_lookup_text(item))
    return {term for term in terms if term}


def _source_path_matches_concept(source_path: str, node: dict[str, Any]) -> bool:
    wanted = source_path.replace("\\", "/").casefold().strip()
    if not wanted:
        return False
    for key in ("documents", "related_documents"):
        values = node.get(key)
        if not isinstance(values, (list, tuple, set)):
            continue
        for item in values:
            candidate = str(item or "").replace("\\", "/").casefold().strip()
            if candidate and (candidate == wanted or candidate.endswith("/" + wanted) or wanted.endswith("/" + candidate)):
                return True
    return False


def resolve_canonical_concept_id_for_learner_signal(
    *signals: Any,
    source_path: str | None = None,
) -> str | None:
    """Map tutor/flashcard learner signals onto active graph concept ids."""
    try:
        concepts = get_active_knowledge_graph().get_concepts()
    except Exception:  # noqa: BLE001 - unresolved signals should not break learner actions.
        logger.debug("canonical_concept_resolve_graph_failed", exc_info=True)
        return None
    if not isinstance(concepts, dict) or not concepts:
        return None

    source = str(source_path or "").strip()
    if source:
        for concept_id, node in concepts.items():
            if isinstance(node, dict) and _source_path_matches_concept(source, node):
                return str(concept_id).strip() or None

    normalized_signals = [
        _normalize_concept_lookup_text(signal)
        for signal in signals
        if _normalize_concept_lookup_text(signal)
    ]
    if not normalized_signals:
        return None

    lookup: dict[str, str] = {}
    for concept_id, node in concepts.items():
        if not isinstance(node, dict):
            continue
        cid = str(concept_id).strip()
        if not cid:
            continue
        for term in _concept_lookup_terms(cid, node):
            lookup.setdefault(term, cid)

    for signal in normalized_signals:
        if signal in lookup:
            return lookup[signal]

    for signal in normalized_signals:
        for term, cid in lookup.items():
            if len(signal) >= 4 and len(term) >= 4 and (signal in term or term in signal):
                return cid
    return None


def _filter_mastery_vector_for_active_index(
    mastery_vector: dict[str, float],
    *,
    active_concepts: set[str],
) -> tuple[dict[str, float], dict[str, Any]]:
    normalized: dict[str, float] = {}
    orphaned: list[str] = []
    for concept, value in (mastery_vector or {}).items():
        cid = str(concept or "").strip()
        if not cid or cid == "avg":
            continue
        try:
            score = float(value)
        except (TypeError, ValueError):
            continue
        if active_concepts and cid not in active_concepts:
            orphaned.append(cid)
            continue
        normalized[cid] = max(0.0, min(1.0, score))
    normalized["avg"] = (sum(normalized.values()) / float(len(normalized))) if normalized else 0.0
    migration: dict[str, Any] = {
        "filter_applied": bool(active_concepts),
        "active_concepts_total": len(active_concepts),
        "active_mastery_concepts": max(0, len(normalized) - 1),
        "orphaned_mastery_concepts": len(orphaned),
    }
    if orphaned:
        migration["orphaned_mastery_sample"] = orphaned[:8]
    return normalized, migration


def _build_state_migration_summary(
    *,
    snapshot: dict[str, Any],
    current_index_context: dict[str, Any],
    filtered_mastery_meta: dict[str, Any],
) -> dict[str, Any]:
    snapshot_index = snapshot.get("index_context")
    if not isinstance(snapshot_index, dict):
        snapshot_index = {}
    source_index_version = snapshot_index.get("index_version")
    source_generation_id = snapshot_index.get("generation_id")
    current_index_version = current_index_context.get("index_version")
    current_generation_id = current_index_context.get("generation_id")
    index_changed = False
    if source_index_version is not None and current_index_version is not None:
        index_changed = source_index_version != current_index_version
    if source_generation_id and current_generation_id:
        index_changed = index_changed or (source_generation_id != current_generation_id)
    previous_migration = snapshot.get("state_migration")
    if not isinstance(previous_migration, dict):
        previous_migration = {}
    return {
        "source_index_version": source_index_version,
        "source_generation_id": source_generation_id,
        "current_index_version": current_index_version,
        "current_generation_id": current_generation_id,
        "index_changed": index_changed,
        "learning_interactions_total": int(previous_migration.get("learning_interactions_total") or 0),
        "learning_interactions_by_type": dict(previous_migration.get("learning_interactions_by_type") or {}),
        **filtered_mastery_meta,
    }


def _snapshot_is_stale(snapshot: dict[str, Any], current_index_context: dict[str, Any]) -> bool:
    snapshot_index = snapshot.get("index_context")
    if not isinstance(snapshot_index, dict) or not current_index_context:
        return False
    source_generation_id = str(snapshot_index.get("generation_id") or "").strip()
    current_generation_id = str(current_index_context.get("generation_id") or "").strip()
    if source_generation_id and current_generation_id and source_generation_id != current_generation_id:
        return True
    source_index_version = snapshot_index.get("index_version")
    current_index_version = current_index_context.get("index_version")
    if source_index_version is not None and current_index_version is not None:
        return source_index_version != current_index_version
    return False


def _decorate_snapshot_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data or {})
    payload["profile_schema_version"] = PERSONALIZED_LEARNER_PROFILE_SCHEMA_VERSION
    payload["index_context"] = _current_index_context()
    state_migration = payload.get("state_migration")
    if not isinstance(state_migration, dict):
        payload["state_migration"] = {}
    return payload


def _apply_history_heuristics(profile: PersonalizedLearnerModel, history: list[dict[str, Any]]) -> None:
    if not history:
        return

    response_times = [float(m["response_time"]) for m in history if m.get("response_time") is not None]
    if response_times:
        avg_time = float(statistics.mean(response_times))
        profile.cognitive_load = min(0.95, max(0.05, avg_time / 45.0))

    last_msgs = [str(m.get("content") or "").lower() for m in history[-3:]]
    blob = " ".join(last_msgs)
    frustrated_markers = ("не понимаю", "сложно", "устал", "не получается")
    engaged_markers = ("понял", "круто", "да!", "отлично", "ясно")
    if any(w in blob for w in frustrated_markers):
        profile.emotional_state = "frustrated"
        profile.confidence_indicator = max(0.1, profile.confidence_indicator * 0.6)
    elif any(w in blob for w in engaged_markers):
        profile.emotional_state = "engaged"
        profile.confidence_indicator = min(1.0, profile.confidence_indicator * 1.1)

    gains = [float(m.get("mastery_gain", 0) or 0) for m in history if "mastery_gain" in m]
    if len(history) > 3 and gains:
        profile.learning_velocity = max(
            0.0, min(1.0, sum(1 for g in gains if g > 0.1) / float(len(history)))
        )

    avg_m = float(profile.mastery_vector.get("avg") or 0.0)
    if avg_m > 0.75:
        profile.optimal_depth = "advanced"
    elif avg_m < 0.4:
        profile.optimal_depth = "beginner"
    else:
        profile.optimal_depth = "intermediate"


def _rehydrate_mastery_from_profile_history(
    *,
    active_concepts: set[str],
) -> tuple[dict[str, float], dict[str, Any] | None]:
    """
    Восстановление mastery из versioned history (последняя совместимая запись).
    Используется как migration-safe fallback при пустом текущем mastery после фильтрации.
    """
    rows = load_profile_history_rows()
    if not rows:
        return {}, None
    for row in reversed(rows):
        raw = row.get("mastery_vector")
        if not isinstance(raw, dict):
            continue
        candidate, meta = _filter_mastery_vector_for_active_index(
            raw,
            active_concepts=active_concepts,
        )
        active_count = int(meta.get("active_mastery_concepts") or 0)
        if active_count <= 0:
            continue
        source_ctx = row.get("index_context") if isinstance(row.get("index_context"), dict) else {}
        return candidate, {
            "history_rehydrated": True,
            "history_rehydrated_active_mastery_concepts": active_count,
            "history_rehydrated_source_generation_id": source_ctx.get("generation_id"),
            "history_rehydrated_source_index_version": source_ctx.get("index_version"),
            # US-8.2: fallback date for badge if index_context.activated_at is missing
            "history_rehydrated_row_timestamp": row.get("timestamp"),
        }
    return {}, None


def get_personalized_learner_profile(
    user_id: str | None = None,
    *,
    session_id: str | None = None,
) -> PersonalizedLearnerModel:
    """Полный профиль: снимок KV + вектор из графа + эвристики по истории сессии."""
    uid = (user_id or "").strip() or "local"
    snap = _load_snapshot()
    base: dict[str, Any] = {**snap, "user_id": uid}
    try:
        profile = PersonalizedLearnerModel.model_validate(base)
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.debug("personalized_learner_validate_fallback", exc_info=True)
        profile = PersonalizedLearnerModel(user_id=uid)

    current_index_context = _current_index_context()
    active_concepts = _active_concept_ids()
    raw_mastery_vector = get_mastery_vector(uid)
    filtered_mastery_vector, filtered_mastery_meta = _filter_mastery_vector_for_active_index(
        raw_mastery_vector,
        active_concepts=active_concepts,
    )
    if int(filtered_mastery_meta.get("active_mastery_concepts") or 0) <= 0:
        restored_mastery, restore_meta = _rehydrate_mastery_from_profile_history(
            active_concepts=active_concepts,
        )
        if restored_mastery:
            filtered_mastery_vector = restored_mastery
            filtered_mastery_meta = {**filtered_mastery_meta, **(restore_meta or {})}
    profile.mastery_vector = filtered_mastery_vector
    profile.profile_schema_version = PERSONALIZED_LEARNER_PROFILE_SCHEMA_VERSION
    profile.index_context = current_index_context
    profile.is_stale = _snapshot_is_stale(snap, current_index_context)
    profile.state_migration = _build_state_migration_summary(
        snapshot=snap,
        current_index_context=current_index_context,
        filtered_mastery_meta=filtered_mastery_meta,
    )
    profile.state_migration["is_stale"] = profile.is_stale
    history = get_session_interaction_messages(session_id, last_n=10)
    _apply_history_heuristics(profile, history)
    profile.last_updated = datetime.now(timezone.utc)
    return profile


def merge_personalized_into_learner_profile(
    base: dict[str, Any],
    *,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Объединяет профиль тьютора (route, weak_concepts, …) с PersonalizedLearnerModel.
    Поля ``base`` имеют приоритет при совпадении ключей.
    """
    plm = get_personalized_learner_profile(user_id, session_id=session_id)
    extra = plm.model_dump(mode="json")
    styles = extra.pop("preferred_styles", {})
    out: dict[str, Any] = {**extra, **base}
    out["style_weights"] = styles
    out["personalized_model_version"] = "19.5"
    return out


def emotional_state_to_score(state: str) -> float:
    """Грубая шкала 0..1 для heatmap (не медицинская оценка)."""
    m: dict[str, float] = {
        "engaged": 0.82,
        "confident": 0.88,
        "neutral": 0.52,
        "bored": 0.38,
        "frustrated": 0.22,
    }
    return float(m.get(str(state or "").strip().lower(), 0.5))


def load_emotional_heatmap_rows() -> list[dict[str, Any]]:
    raw = get_kv(EMOTIONAL_HEATMAP_KV_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return data if isinstance(data, list) else []


def _save_emotional_heatmap_rows(rows: list[dict[str, Any]]) -> None:
    set_kv(EMOTIONAL_HEATMAP_KV_KEY, json.dumps(rows[-_EMOTIONAL_HEATMAP_MAX_ROWS:], ensure_ascii=False))


def save_emotional_snapshot(
    user_id: str | None,
    emotional_state: str,
    concept: str = "global",
) -> None:
    """Одна точка для Emotional Heatmap (день × концепт); вызывать после tutor/quiz."""
    _ = user_id
    rows = load_emotional_heatmap_rows()
    day = datetime.now(timezone.utc).date().isoformat()
    c = (concept or "global").strip() or "global"
    rows.append(
        {
            "date": day,
            "concept": c,
            "emotional_score": emotional_state_to_score(emotional_state),
            "state": str(emotional_state or "neutral").strip().lower(),
        }
    )
    _save_emotional_heatmap_rows(rows)


def get_emotional_heatmap_pivot(last_days: int = 30):
    """DataFrame concept×date для Plotly или ``None``, если данных нет."""
    from datetime import timedelta

    import pandas as pd

    rows = load_emotional_heatmap_rows()
    if not rows:
        return None
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=max(1, int(last_days)))).isoformat()
    filt = [r for r in rows if str(r.get("date") or "") >= cutoff]
    if not filt:
        return None
    df = pd.DataFrame(filt)
    if df.empty or "concept" not in df.columns or "date" not in df.columns:
        return None
    df = df.dropna(subset=["concept", "date"])
    if df.empty:
        return None
    p = df.pivot_table(index="concept", columns="date", values="emotional_score", aggfunc="mean")
    return p.sort_index().sort_index(axis=1)


def save_learner_profile(user_id: str | None, data: dict[str, Any]) -> None:
    """Сохранить снимок модели (JSON в ``app_kv``)."""
    _ = user_id
    payload = _decorate_snapshot_payload(dict(data or {}))
    payload["last_updated"] = datetime.now(timezone.utc).isoformat()
    set_kv(PERSONALIZED_LEARNER_KV_KEY, json.dumps(payload, ensure_ascii=False))
    append_profile_history(payload)


def get_learner_state_health(
    user_id: str | None = None,
    *,
    session_id: str | None = None,
    limit_history: int = 200,
) -> dict[str, Any]:
    profile = get_personalized_learner_profile(user_id, session_id=session_id)
    metrics = get_learner_profile_migration_metrics(limit=limit_history)
    try:
        from app.user_state import get_learner_state_diagnostics

        diagnostics = get_learner_state_diagnostics(recent_limit=8)
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.debug("learner_state_health_diagnostics_failed", exc_info=True)
        diagnostics = {}

    status = "stale" if profile.is_stale else "ok"
    rehydrated_rate = metrics.get("rehydrated_rate")
    return {
        "schema_version": 1,
        "status": status,
        "user_id": profile.user_id,
        "is_stale": profile.is_stale,
        "profile_schema_version": profile.profile_schema_version,
        "current_index_context": profile.index_context,
        "state_migration": profile.state_migration,
        "migration_metrics": metrics,
        "learner_state_lineage": diagnostics,
        "rehydrated_rate": rehydrated_rate,
    }


def _clamp01(value: Any, *, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _outcome_concept_gains(outcome: dict[str, Any]) -> dict[str, float]:
    raw = outcome.get("concept_gains") if isinstance(outcome.get("concept_gains"), dict) else {}
    gains: dict[str, float] = {}
    for key, value in raw.items():
        concept = str(key or "").strip()
        if concept:
            gains[concept] = _clamp01(value)
    if gains:
        return gains
    concept = str(outcome.get("concept") or outcome.get("focus_topic") or outcome.get("topic") or "").strip()
    if concept:
        gains[concept] = _clamp01(outcome.get("mastery_score"), default=_clamp01(outcome.get("mastery_gain")))
    return gains


def _canonical_outcome_concept_gains(outcome: dict[str, Any]) -> dict[str, float]:
    raw_gains = _outcome_concept_gains(outcome)
    if not raw_gains:
        return {}
    source_path = str(outcome.get("source_path") or "").strip() or None
    canonical: dict[str, float] = {}
    for concept, score in raw_gains.items():
        cid = resolve_canonical_concept_id_for_learner_signal(
            concept,
            outcome.get("concept"),
            outcome.get("focus_topic"),
            outcome.get("topic"),
            source_path=source_path,
        )
        if cid:
            canonical[cid] = max(canonical.get(cid, 0.0), _clamp01(score))
    return canonical


def _mean_gain(outcome: dict[str, Any], gains: dict[str, float]) -> float:
    if "mastery_gain" in outcome:
        return _clamp01(outcome.get("mastery_gain"))
    if gains:
        return sum(gains.values()) / float(len(gains))
    return 0.0


def _merge_outcome_mastery(profile: PersonalizedLearnerModel, gains: dict[str, float], *, monotonic: bool) -> None:
    if not gains:
        return
    merged = {**profile.mastery_vector}
    for concept, score in gains.items():
        if monotonic:
            previous = float(merged.get(concept, 0.0) or 0.0)
            merged[concept] = max(previous, score)
        else:
            merged[concept] = score
    concept_values = [value for key, value in merged.items() if key != "avg"]
    if concept_values:
        merged["avg"] = sum(concept_values) / float(len(concept_values))
    profile.mastery_vector = merged


def _bump_session_velocity(profile: PersonalizedLearnerModel, gain: float) -> None:
    profile.sessions_completed = max(0, int(profile.sessions_completed or 0)) + 1
    sc = profile.sessions_completed
    profile.learning_velocity = (
        float(profile.learning_velocity) * float(sc - 1) + _clamp01(gain)
    ) / float(sc)


def _bump_interaction_velocity(profile: PersonalizedLearnerModel, interaction_type: str, gain: float) -> None:
    migration = dict(profile.state_migration or {})
    total = int(migration.get("learning_interactions_total") or 0) + 1
    by_type = dict(migration.get("learning_interactions_by_type") or {})
    key = (interaction_type or "unknown").strip().lower() or "unknown"
    by_type[key] = int(by_type.get(key) or 0) + 1
    migration["learning_interactions_total"] = total
    migration["learning_interactions_by_type"] = by_type
    profile.state_migration = migration
    profile.learning_velocity = (
        float(profile.learning_velocity) * float(total - 1) + _clamp01(gain)
    ) / float(total)


def update_learner_model_after_interaction(
    user_id: str | None,
    interaction_type: str,
    outcome: dict[str, Any],
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Хук после micro-quiz или tutor-ответа: обновить метрики и сохранить."""
    sid = (outcome.get("session_id") if isinstance(outcome, dict) else None) or session_id
    profile = get_personalized_learner_profile(user_id, session_id=sid)
    it = (interaction_type or "").strip().lower()
    outcome = outcome if isinstance(outcome, dict) else {}
    concept_gains: dict[str, float] = {}

    if it == "quiz":
        concept_gains = _outcome_concept_gains(outcome)
        gain = _mean_gain(outcome, concept_gains)
        _merge_outcome_mastery(profile, concept_gains, monotonic=False)
        _bump_session_velocity(profile, gain)

    elif it == "tutor":
        concept_gains = _canonical_outcome_concept_gains(outcome)
        gain = _mean_gain(outcome, concept_gains)
        _merge_outcome_mastery(profile, concept_gains, monotonic=True)
        _bump_interaction_velocity(profile, it, gain or 0.05)
        load_delta = float(outcome.get("cognitive_load_delta", -0.05) or -0.05)
        profile.cognitive_load = max(0.05, min(0.95, float(profile.cognitive_load) + load_delta))
        confidence_delta = float(outcome.get("confidence_delta", 0.02) or 0.0)
        profile.confidence_indicator = max(0.05, min(1.0, float(profile.confidence_indicator) + confidence_delta))

    elif it == "flashcard":
        concept_gains = _canonical_outcome_concept_gains(outcome)
        gain = _mean_gain(outcome, concept_gains)
        _merge_outcome_mastery(profile, concept_gains, monotonic=True)
        _bump_interaction_velocity(profile, it, gain)
        if gain >= 0.7:
            profile.confidence_indicator = min(1.0, float(profile.confidence_indicator) + 0.03)
            profile.cognitive_load = max(0.05, float(profile.cognitive_load) - 0.03)
        else:
            profile.confidence_indicator = max(0.05, float(profile.confidence_indicator) - 0.02)
            profile.cognitive_load = min(0.95, float(profile.cognitive_load) + 0.04)

    profile_saved = False
    try:
        save_learner_profile(user_id, profile.model_dump(mode="json"))
        profile_saved = True
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.debug("save_learner_profile_after_interaction failed", exc_info=True)

    try:
        concept_snap = "global"
        if isinstance(outcome, dict):
            cg = outcome.get("concept_gains")
            if isinstance(cg, dict) and cg:
                concept_snap = str(next(iter(cg.keys()))).strip() or "global"
            else:
                concept_snap = (
                    str(
                        outcome.get("concept")
                        or outcome.get("focus_topic")
                        or outcome.get("topic")
                        or "global"
                    ).strip()
                    or "global"
                )
        save_emotional_snapshot(user_id, str(profile.emotional_state), concept=concept_snap)
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        logger.debug("save_emotional_snapshot failed", exc_info=True)

    if isinstance(outcome, dict) and outcome.get("adaptive_block_for_xp"):
        try:
            from app.gamification_service import award_xp_for_block

            blk = outcome["adaptive_block_for_xp"]
            if isinstance(blk, dict):
                award_xp_for_block(
                    user_id or "local",
                    blk,
                    session_id=sid,
                )
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            logger.debug("award_xp_for_block from interaction failed", exc_info=True)

    try:
        AdaptiveDailyPlan(user_id or "local", session_id=sid).build_adaptive_daily_plan()
    except Exception as exc:  # noqa: BLE001 - downstream best-effort
        logger.warning("adaptive_daily_plan_after_interaction_failed", exc_info=exc)

    updated_concepts = {
        concept: score
        for concept, score in sorted(concept_gains.items())
    }
    return {
        "interaction_type": it,
        "mastery_updated": bool(updated_concepts),
        "updated_concepts": updated_concepts,
        "profile_saved": profile_saved,
    }


_SSR_UI_METADATA_KEY = "ssr_ui_metadata"


def load_learner_ssr_metadata() -> dict[str, Any]:
    """Reads SSR UI metadata bucket from raw learner KV snapshot."""
    snap = _load_snapshot()
    state_migration = snap.get("state_migration")
    if not isinstance(state_migration, dict):
        return {}
    meta = state_migration.get(_SSR_UI_METADATA_KEY)
    if not isinstance(meta, dict):
        return {}
    return dict(meta)


def save_learner_ssr_metadata(metadata: dict[str, Any]) -> None:
    """Persists SSR UI metadata via raw snapshot merge (preserves extension keys)."""
    snap = _load_snapshot()
    state_migration = snap.get("state_migration")
    if not isinstance(state_migration, dict):
        state_migration = {}
    state_migration[_SSR_UI_METADATA_KEY] = dict(metadata or {})
    snap["state_migration"] = state_migration
    payload = _decorate_snapshot_payload(snap)
    payload["last_updated"] = datetime.now(timezone.utc).isoformat()
    set_kv(PERSONALIZED_LEARNER_KV_KEY, json.dumps(payload, ensure_ascii=False))


def read_persisted_concept_recovery_ladder() -> dict[str, Any] | None:
    """Reads ladder resume blob from ``state_migration.ssr_ui_metadata``."""
    from app.pipeline_steps import read_concept_recovery_ladder_resume_v1

    return read_concept_recovery_ladder_resume_v1(load_learner_ssr_metadata())


def persist_concept_recovery_ladder(
    step: int,
    *,
    concept_anchor: str = "",
    scope_id: str | None = None,
    clear: bool = False,
) -> dict[str, Any] | None:
    """Round-trip ladder resume into learner KV via pipeline merge helpers."""
    from app.pipeline_steps import (
        clear_concept_recovery_ladder_from_metadata,
        merge_concept_recovery_ladder_into_metadata,
    )
    from app.smart_study_recovery_ladder import concept_recovery_resume_v1

    meta = load_learner_ssr_metadata()
    if clear:
        clear_concept_recovery_ladder_from_metadata(meta)
        save_learner_ssr_metadata(meta)
        return None

    blob = concept_recovery_resume_v1(step, concept_anchor=concept_anchor, scope_id=scope_id)
    merge_concept_recovery_ladder_into_metadata(meta, ladder_resume=blob)
    save_learner_ssr_metadata(meta)
    return dict(blob)


__all__ = [
    "EMOTIONAL_HEATMAP_KV_KEY",
    "PERSONALIZED_LEARNER_HISTORY_KV_KEY",
    "PERSONALIZED_LEARNER_KV_KEY",
    "PersonalizedLearnerModel",
    "emotional_state_to_score",
    "get_emotional_heatmap_pivot",
    "get_learner_profile_history",
    "get_learner_profile_migration_metrics",
    "get_learner_state_health",
    "get_personalized_learner_profile",
    "get_session_interaction_messages",
    "load_emotional_heatmap_rows",
    "load_learner_ssr_metadata",
    "merge_personalized_into_learner_profile",
    "persist_concept_recovery_ladder",
    "read_persisted_concept_recovery_ladder",
    "resolve_canonical_concept_id_for_learner_signal",
    "save_emotional_snapshot",
    "save_learner_profile",
    "save_learner_ssr_metadata",
    "update_learner_model_after_interaction",
]
