"""Adaptive daily plan datatype.

Extracted from ``learning_plan_service`` to break the import cycle between
``app.learner_model_service`` and ``app.learning_plan_service``: both modules
now import :class:`AdaptiveDailyPlan` from here, and this module avoids any
top-level import of those services.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.knowledge_graph import JsonKnowledgeGraph, get_personalized_subgraph, knowledge_graph
from app.learner_state_scope import (
    filter_due_reviews_for_kg,
    get_quiz_mastery_rows_for_kg,
    weak_concepts_for_kg,
)
from app.quiz_adaptive import mastery_percent_for_level

logger = logging.getLogger(__name__)

ADAPTIVE_DAILY_PLAN_KV_KEY = "adaptive_daily_plan_json"
ADAPTIVE_DAILY_PLAN_HISTORY_KV_KEY = "adaptive_daily_plan_history_json"
_MAX_PLAN_HISTORY = 3


def block_concepts_from_plan(plan: dict[str, Any] | None) -> list[str]:
    """Концепты из блоков плана (для US-6.2 diff)."""
    if not isinstance(plan, dict):
        return []
    out: list[str] = []
    for b in plan.get("blocks") or []:
        if not isinstance(b, dict):
            continue
        c = str(b.get("concept") or "").strip()
        if c:
            out.append(c)
    return out


def plan_snapshot_for_history(plan: dict[str, Any]) -> dict[str, Any]:
    """US-6.3: компактный снимок плана для списка «недавние версии» (без дублирования полного JSON)."""
    blocks = plan.get("blocks") or []
    concepts: list[str] = []
    for b in blocks:
        if isinstance(b, dict):
            c = str(b.get("concept") or "").strip()
            if c:
                concepts.append(c)
    concepts = concepts[:3]
    reviews = sum(1 for b in blocks if isinstance(b, dict) and str(b.get("type") or "").strip() == "review")
    gaps = sum(1 for b in blocks if isinstance(b, dict) and str(b.get("type") or "").strip() == "gap")
    new_c = sum(1 for b in blocks if isinstance(b, dict) and str(b.get("type") or "").strip() == "new")
    return {
        "date": str(plan.get("date") or ""),
        "focus_review_gap_new": [reviews, gaps, new_c],
        "main_concepts": concepts,
        "total_xp_goal": plan.get("total_xp_goal"),
        "motivation_excerpt": (str(plan.get("motivation_message") or "").strip()[:180]),
    }


def _append_previous_plan_to_history(prev_plan: dict[str, Any] | None) -> None:
    """Перед перезаписью текущего плана кладём краткий снимок предыдущего в кольцо (max 3)."""
    from app.user_state import get_kv, set_kv

    if not isinstance(prev_plan, dict) or not prev_plan.get("blocks"):
        return
    entry = plan_snapshot_for_history(prev_plan)
    entry["archived_at"] = datetime.now(timezone.utc).isoformat()
    try:
        raw = get_kv(ADAPTIVE_DAILY_PLAN_HISTORY_KV_KEY)
        hist: list[Any] = json.loads(raw) if raw else []
        if not isinstance(hist, list):
            hist = []
    except (json.JSONDecodeError, TypeError):
        hist = []
    if hist and isinstance(hist[-1], dict) and hist[-1].get("date") == entry.get("date"):
        hist[-1] = entry
    else:
        hist.append(entry)
    hist = hist[-_MAX_PLAN_HISTORY:]
    try:
        set_kv(ADAPTIVE_DAILY_PLAN_HISTORY_KV_KEY, json.dumps(hist, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - KV persistence is best-effort; streak history optional
        logger.error("adaptive_daily_plan_history_save_failed: %s", exc, exc_info=True)


def get_adaptive_daily_plan_history() -> list[dict[str, Any]]:
    """US-6.3: 2–3 последних снимка (тот же KV store, отдельный ключ)."""
    from app.user_state import get_kv

    raw = get_kv(ADAPTIVE_DAILY_PLAN_HISTORY_KV_KEY)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            out.append(item)
    return out


def compute_plan_concepts_delta(
    previous_plan: dict[str, Any] | None, new_plan: dict[str, Any]
) -> dict[str, Any]:
    """
    Сравнение концептов в шагах плана с предыдущим сохранённым снимком (KV).
    Вызывается перед записью нового плана.
    """
    old_c = set(block_concepts_from_plan(previous_plan))
    new_c = set(block_concepts_from_plan(new_plan))
    baseline_date: str | None = None
    if isinstance(previous_plan, dict):
        baseline_date = str(previous_plan.get("date") or "").strip() or None
    return {
        "added": sorted(new_c - old_c),
        "removed": sorted(old_c - new_c),
        "baseline_date": baseline_date,
    }


def _primary_entry_block(plan: dict[str, Any]) -> dict[str, Any] | None:
    """Compact primary block contract for entry surfaces.

    Prefer a learner-facing block over ``auto_loop``. If only ``auto_loop`` is
    available, keep it as an explicit fallback rather than forcing UI layers to
    infer the same rule repeatedly.
    """
    blocks = plan.get("blocks") or []
    fallback: dict[str, Any] | None = None
    for raw in blocks:
        if not isinstance(raw, dict):
            continue
        block = raw
        block_type = str(block.get("type") or "").strip()
        if fallback is None:
            fallback = block
        if block_type != "auto_loop":
            return {
                "type": block_type or "unknown",
                "concept": str(block.get("concept") or "").strip() or None,
                "description": str(block.get("description") or "").strip(),
                "agent": str(block.get("agent") or block.get("recommended_agent") or "").strip() or None,
            }
    if not isinstance(fallback, dict):
        return None
    return {
        "type": str(fallback.get("type") or "auto_loop").strip() or "auto_loop",
        "concept": str(fallback.get("concept") or "").strip() or None,
        "description": str(fallback.get("description") or "").strip(),
        "agent": str(fallback.get("agent") or fallback.get("recommended_agent") or "").strip() or None,
    }


def _attach_entry_surface_contract(plan: dict[str, Any]) -> dict[str, Any]:
    """Annotate the plan with explicit entry-surface semantics."""
    primary = _primary_entry_block(plan)
    if primary is None:
        plan["entry_state"] = "empty"
        plan["has_actionable_blocks"] = False
        plan["primary_block"] = None
        return plan
    primary_type = str(primary.get("type") or "").strip()
    plan["entry_state"] = "actionable" if primary_type and primary_type != "auto_loop" else "auto_loop_only"
    plan["has_actionable_blocks"] = bool(primary_type and primary_type != "auto_loop")
    plan["primary_block"] = primary
    return plan


def _parse_dt_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _days_overdue_from_due_row(row: dict[str, Any]) -> int:
    nr = row.get("next_review")
    if not nr:
        return 1
    try:
        dt = _parse_dt_iso(str(nr))
        if dt is None:
            return 1
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0, int((now - dt).days))
    except (TypeError, ValueError):
        return 1


def _level_to_mastery_float(level: str | None) -> float:
    return float(mastery_percent_for_level(level)) / 100.0


class AdaptiveDailyPlan:
    """План на день с учётом Personalized Learner Model 19.5, графа и spaced repetition."""

    def __init__(
        self,
        user_id: str,
        session_id: str | None = None,
        kg: JsonKnowledgeGraph | None = None,
    ) -> None:
        # Deferred to avoid module-level cycle with learner_model_service.
        from app.learner_model_service import get_personalized_learner_profile

        self.user_id = (user_id or "").strip() or "local"
        self.session_id = session_id
        self._kg = kg or knowledge_graph
        self.profile = get_personalized_learner_profile(self.user_id, session_id=self.session_id)
        self.today = datetime.now(timezone.utc).date()

    def _seed_topic(self) -> str:
        weak = weak_concepts_for_kg(self._kg, threshold=60, limit=5)
        if weak:
            return str(weak[0])
        due = filter_due_reviews_for_kg(self._kg, limit=1)
        if due:
            return str(due[0].get("concept") or "").strip() or "general"
        return "general"

    def _topo_order_ids(self, ids: list[str]) -> list[str]:
        if not ids:
            return []
        all_ids = [cid for cid, c in self._kg.get_concepts().items() if isinstance(c, dict)]
        if not all_ids:
            return ids
        topo = self._kg.topological_sort(all_ids)
        order = {x: i for i, x in enumerate(topo)}
        return sorted(ids, key=lambda x: order.get(x, 10_000))

    def _calculate_session_length(self) -> int:
        base = min(45, max(15, int(self.profile.recommended_session_length_min or 25)))
        if float(self.profile.cognitive_load) > 0.7:
            return max(15, base - 10)
        if float(self.profile.learning_velocity) > 0.18:
            return min(45, base + 15)
        return min(45, base + int(float(self.profile.confidence_indicator) * 10))

    def _calculate_xp_goal(self) -> int:
        streak = 0
        try:
            from app.gamification_service import get_snapshot

            streak = int((get_snapshot() or {}).get("daily_streak") or 0)
        except Exception as exc:  # noqa: BLE001 - gamification snapshot is optional; failures are heterogeneous
            logger.error("adaptive_daily_plan_streak_unavailable: %s", exc, exc_info=True)
        return 150 + (streak * 20) + int(float(self.profile.learning_velocity) * 100)

    def _new_reviews_ratio_note(self, n_due: int, n_gaps: int, n_new: int) -> str:
        tot = max(1, n_due + n_gaps + n_new)
        return f"reviews {n_due}/{tot} · gaps {n_gaps}/{tot} · new {n_new}/{tot}"

    def _create_review_block(self, review: dict[str, Any]) -> dict[str, Any]:
        c = str(review.get("concept") or "").strip()
        ddays = max(1, int(review.get("days_overdue") or 1))
        agent = "MicroQuizGenerator" if ddays > 3 else "ConceptExplainer"
        return {
            "type": "review",
            "concept": c,
            "due_in_days": ddays,
            "agent": agent,
            "duration_min": 7,
            "xp_base": 25,
            "xp_multiplier_description": "velocity × streak × fast",
            "description": f"Повторение **{c}** (due, ~{ddays} дн.)",
        }

    def _create_gap_block(self, gap: dict[str, Any]) -> dict[str, Any]:
        m = float(gap.get("mastery") or 0.0)
        name = str(gap.get("name") or gap.get("id") or "")
        agent = "ErrorDiagnoser" if m < 0.4 else "SocraticQuestioner"
        return {
            "type": "gap",
            "concept": name,
            "current_mastery": round(m, 2),
            "recommended_agent": agent,
            "duration_min": 10,
            "xp_base": 40,
            "xp_multiplier_description": "mastery gap ×2 · velocity × streak",
            "description": f"Закрыть пробел: **{name}** (mastery {round(m, 2)})",
        }

    def _create_new_topic_block(self, topic: dict[str, Any]) -> dict[str, Any]:
        name = str(topic.get("name") or topic.get("id") or "")
        return {
            "type": "new",
            "concept": name,
            "agent": "ConceptExplainer",
            "duration_min": 12,
            "xp_base": 35,
            "xp_multiplier_description": "velocity × streak × fast",
            "description": f"Новый шаг по графу: **{name}**",
        }

    def _create_motivation_block(self) -> dict[str, Any]:
        return {
            "type": "motivation",
            "agent": "MotivationCoach",
            "duration_min": 5,
            "xp_base": 15,
            "xp_multiplier_description": "emotional recovery +20% · velocity × streak",
            "description": f"Короткая поддержка (состояние: {self.profile.emotional_state})",
        }

    def _generate_motivation_message(self) -> str:
        es = str(self.profile.emotional_state)
        xp = self._calculate_xp_goal()
        sess = int(self.profile.sessions_completed or 0)
        if es == "frustrated":
            return f"Сегодня фокус на маленьких победах — пройдено сессий: {sess}."
        if es == "engaged":
            return f"Сильный настрой. Цель XP на сегодня ~{xp}: закрепи повторения и gap'ы."
        if es == "bored":
            return "Чередуем темы и transfer-вопросы — больше разнообразия."
        return "Хороший день, чтобы двигаться по графу и spaced repetition."

    def _save_plan(self, plan: dict[str, Any]) -> None:
        from app.user_state import get_kv, set_kv

        prev_plan: dict[str, Any] | None = None
        try:
            raw = get_kv(ADAPTIVE_DAILY_PLAN_KV_KEY)
            if raw:
                prev = json.loads(raw)
                if isinstance(prev, dict):
                    prev_plan = prev
        except (json.JSONDecodeError, TypeError):
            prev_plan = None

        plan["plan_concepts_delta"] = compute_plan_concepts_delta(prev_plan, plan)
        _append_previous_plan_to_history(prev_plan)

        try:
            set_kv(ADAPTIVE_DAILY_PLAN_KV_KEY, json.dumps(plan, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001 - KV persistence is best-effort
            logger.error("adaptive_daily_plan_save_failed: %s", exc, exc_info=True)

    def build_adaptive_daily_plan(self) -> dict[str, Any]:
        """План на сегодня: блоки review / gap / new + auto_loop."""
        graduation_statuses: dict[str, str] = {}
        graduated_ids: set[str] = set()
        refresh_graduation = getattr(self._kg, "refresh_concept_graduation", None)
        get_graduated_ids = getattr(self._kg, "graduated_concept_ids", None)
        if callable(refresh_graduation) and callable(get_graduated_ids):
            graduation_statuses = refresh_graduation(get_quiz_mastery_rows_for_kg(self._kg))
            graduated_ids = get_graduated_ids()
        seed = self._seed_topic()
        sub = get_personalized_subgraph(seed_topic=seed, limit=14, kg=self._kg)
        nodes_raw = list(sub.get("nodes") or [])
        with_mastery: list[dict[str, Any]] = []
        for n in nodes_raw:
            cid = str(n.get("id") or "").strip()
            if not cid or cid in graduated_ids:
                continue
            lv = str(n.get("quiz_mastery_level") or "recognition")
            m = _level_to_mastery_float(lv)
            with_mastery.append({"id": cid, "name": cid, "quiz_mastery_level": lv, "mastery": m})

        due_reviews: list[dict[str, Any]] = []
        for r in filter_due_reviews_for_kg(self._kg, limit=12):
            c = str(r.get("concept") or "").strip()
            if not c or c in graduated_ids:
                continue
            due_reviews.append(
                {"concept": c, "days_overdue": max(1, _days_overdue_from_due_row(r)), "row": r}
            )

        gaps = sorted([x for x in with_mastery if x["mastery"] < 0.6], key=lambda x: x["mastery"])
        gap_ids = self._topo_order_ids([x["id"] for x in gaps[:3]])
        due_concepts = {d["concept"] for d in due_reviews}
        new_candidates = [x for x in with_mastery if x["mastery"] >= 0.6 and x["id"] not in due_concepts]
        new_ordered = self._topo_order_ids([x["id"] for x in new_candidates])
        new_topics = []
        for nid in new_ordered[:2]:
            for x in with_mastery:
                if x["id"] == nid:
                    new_topics.append(x)
                    break

        n_due = min(3, len(due_reviews))
        n_gap = min(3, len(gap_ids))
        n_new = len(new_topics)

        plan: dict[str, Any] = {
            "date": self.today.isoformat(),
            "recommended_session_length_min": self._calculate_session_length(),
            "total_xp_goal": self._calculate_xp_goal(),
            "blocks": [],
            "motivation_message": self._generate_motivation_message(),
            "seed_topic": seed,
            "learner_model": "19.5",
            "new_reviews_balance": self._new_reviews_ratio_note(n_due, n_gap, n_new),
            "concept_graduation": graduation_statuses,
        }

        es = str(self.profile.emotional_state)
        if es in ("frustrated", "bored"):
            plan["blocks"].append(self._create_motivation_block())
            for r in due_reviews[:2]:
                plan["blocks"].append(self._create_review_block(r))
        else:
            for r in due_reviews[:3]:
                plan["blocks"].append(self._create_review_block(r))
            for gid in gap_ids:
                gnode = next((x for x in with_mastery if x["id"] == gid), None)
                if gnode:
                    plan["blocks"].append(self._create_gap_block(gnode))
            for t in new_topics:
                plan["blocks"].append(self._create_new_topic_block(t))

        plan["blocks"].append(
            {
                "type": "auto_loop",
                "description": "Unified Auto-Loop после блоков (micro-quiz / tutor, Orchestrator)",
                "duration_min": 5,
                "xp_base": 10,
                "xp_multiplier_description": "velocity × streak (бонус за успешный micro-quiz — раз в день)",
            }
        )

        _attach_entry_surface_contract(plan)
        self._save_plan(plan)
        return plan


__all__ = [
    "ADAPTIVE_DAILY_PLAN_HISTORY_KV_KEY",
    "ADAPTIVE_DAILY_PLAN_KV_KEY",
    "AdaptiveDailyPlan",
    "block_concepts_from_plan",
    "compute_plan_concepts_delta",
    "get_adaptive_daily_plan_history",
    "plan_snapshot_for_history",
]
