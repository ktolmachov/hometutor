"""
Генерация динамического учебного плана (шаги review/new, персональный coach-план).

Адаптивные снимки и next-step после quiz — в ``app.learning_plan_adaptive``;
публичный фасад — ``app.learning_plan_service``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.coach_insights import generate_ai_coach_message, generate_retention_insight
from app.knowledge_graph import JsonKnowledgeGraph, knowledge_graph
from app.learner_state_scope import (
    due_priority_by_concept_for_kg,
    filter_due_reviews_for_kg,
    get_mastery_levels_for_kg,
    get_quiz_mastery_rows_for_kg,
    weak_concepts_for_kg,
)
from app.quiz_adaptive import (
    LEVELS,
    mastery_percent_for_level,
)
from app.user_state import list_topic_reading_rows
from app.learning_plan_adaptive import get_saved_adaptive_daily_plan

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _estimate_new_hours(level: str) -> float:
    lv = (level or "recognition").strip().lower()
    if lv == "recall":
        return 3.0
    if lv == "transfer":
        return 4.0
    return 2.0


def _reading_map() -> dict[str, float | None]:
    """topic_id / concept_id -> progress 0..1 или None."""
    out: dict[str, float | None] = {}
    for row in list_topic_reading_rows(limit=300):
        tid = str(row.get("topic_id") or "").strip()
        if not tid:
            continue
        p = row.get("progress")
        out[tid] = None if p is None else float(p)
    return out


def _trim_plan_by_budget(
    items: list[dict[str, Any]],
    budget_hours: float,
) -> list[dict[str, Any]]:
    if budget_hours <= 0:
        return []
    total = 0.0
    kept: list[dict[str, Any]] = []
    for item in items:
        h = float(item.get("estimated_hours") or 0)
        if total + h <= budget_hours + 1e-6:
            kept.append(item)
            total += h
        else:
            remaining = budget_hours - total
            if remaining >= 0.75 and h > 0:
                copy = dict(item)
                copy["estimated_hours"] = round(remaining, 2)
                copy["reason"] = (copy.get("reason") or "") + " (частично под бюджет)"
                kept.append(copy)
            break
    return kept


def _mastery_percent_by_concept(kg: JsonKnowledgeGraph) -> dict[str, float]:
    mastery = get_mastery_levels_for_kg(kg)
    out: dict[str, float] = {}
    concepts = kg.get_concepts()
    for cid, node in concepts.items():
        if not isinstance(node, dict):
            continue
        lv = mastery.get(cid, "recognition")
        out[cid] = float(mastery_percent_for_level(lv))
    return out


class DynamicLearningPlan:
    """Строит упорядоченный список шагов (review + new) по данным user_state и графу."""

    def __init__(self, kg: JsonKnowledgeGraph | None = None) -> None:
        self._kg = kg or knowledge_graph

    def generate(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        params:
            goal — цель (строка для трассировки)
            level — глобальный уровень студента (beginner/intermediate/advanced), влияет на оценку часов слегка
            time_budget_hours — ограничение суммарных оценочных часов
            user_progress — если False, возвращается заглушка без персонализации
        """
        goal = str(params.get("goal") or "").strip()
        level = str(params.get("level") or "intermediate").strip().lower()
        budget = float(params.get("time_budget_hours") or 40.0)
        user_progress = bool(params.get("user_progress"))

        base: dict[str, Any] = {
            "enabled": user_progress,
            "goal": goal,
            "level": level,
            "time_budget_hours": budget,
            "params_used": dict(params),
            "generated_at": _utc_now_iso(),
        }

        if not user_progress:
            return {
                **base,
                "plan": [],
                "total_steps": 0,
                "estimated_hours_total": 0.0,
                "mastery_percentage": None,
                "next_review_count": 0,
                "message": "Включите user_progress для персонализированного порядка шагов.",
            }

        concepts = self._kg.get_concepts()
        all_ids = [cid for cid, c in concepts.items() if isinstance(c, dict)]
        n_nodes = len(all_ids)
        mastery = get_mastery_levels_for_kg(self._kg)
        streak_by_concept = {
            str(r.get("concept") or ""): int(r.get("success_streak") or 0)
            for r in get_quiz_mastery_rows_for_kg(self._kg)
        }
        due_list = filter_due_reviews_for_kg(self._kg, limit=200)
        reading = _reading_map()

        mastered = {c for c, lv in mastery.items() if lv == "transfer"}
        if n_nodes == 0:
            return {
                **base,
                "plan": [],
                "total_steps": 0,
                "estimated_hours_total": 0.0,
                "mastery_percentage": 0.0,
                "next_review_count": len(due_list),
                "quiz_mastery_snapshot": mastery,
                "reading_topics_count": len(reading),
                "message": "В графе нет концептов (data/concept_graph.json).",
            }

        mastery_pct = round(len(mastered) / n_nodes * 100.0, 1)

        level_factor = 1.0
        if level == "beginner":
            level_factor = 1.15
        elif level == "advanced":
            level_factor = 0.9

        plan: list[dict[str, Any]] = []
        seen: set[str] = set()

        for due in due_list[:5]:
            cid = str(due.get("concept") or "").strip()
            if not cid or cid in seen:
                continue
            seen.add(cid)
            plan.append(
                {
                    "topic": cid,
                    "type": "review",
                    "priority": "high",
                    "reason": "spaced repetition due",
                    "quiz_level": mastery.get(cid, "recognition"),
                    "success_streak": streak_by_concept.get(cid, 0),
                    "reading_progress": reading.get(cid),
                    "estimated_hours": round(1.5 * level_factor, 2),
                }
            )

        topo = self._kg.topological_sort(all_ids)
        for topic in topo:
            if topic in mastered:
                continue
            if topic in seen:
                continue
            lv = mastery.get(topic, "recognition")
            if lv not in LEVELS:
                lv = "recognition"
            prog = reading.get(topic)
            read_note = None
            if prog is None:
                read_note = "чтение не отмечено"
            elif prog < 1.0:
                read_note = f"чтение ~{prog * 100:.0f}%"
            plan.append(
                {
                    "topic": topic,
                    "type": "new",
                    "priority": "normal",
                    "reason": f"топопорядок + текущее освоение: {lv}"
                    + (f"; {read_note}" if read_note else ""),
                    "recommended_quiz_level": lv,
                    "success_streak": streak_by_concept.get(topic, 0),
                    "reading_progress": prog,
                    "estimated_hours": round(_estimate_new_hours(lv) * level_factor, 2),
                }
            )
            seen.add(topic)

        trimmed = _trim_plan_by_budget(plan, budget)
        hours_sum = sum(float(x.get("estimated_hours") or 0) for x in trimmed)

        return {
            **base,
            "plan": trimmed[:20],
            "total_steps": len(plan),
            "scheduled_steps": len(trimmed[:20]),
            "estimated_hours_total": round(hours_sum, 2),
            "mastery_percentage": mastery_pct,
            "next_review_count": len(due_list),
            "quiz_mastery_snapshot": mastery,
            "reading_topics_count": len(reading),
        }

    def generate_personalized_plan(
        self,
        *,
        days: int = 7,
        goal: str = "",
        level: str = "intermediate",
        time_budget_hours: float = 40.0,
        user_progress: bool = True,
        weak_threshold: int = 60,
    ) -> dict[str, Any]:
        """
        P2: компактный персональный план (daily slots, эвристики времени, слабые места, NBA).

        Поле ``adaptive_daily_plan`` — только снимок из KV на сегодня (UTC), без автоматического build.
        """
        d = max(1, min(14, int(days)))
        base = self.generate(
            {
                "goal": goal,
                "level": level,
                "time_budget_hours": time_budget_hours,
                "user_progress": user_progress,
            }
        )
        weak_spots = weak_concepts_for_kg(self._kg, threshold=weak_threshold, limit=12)
        user_pct = _mastery_percent_by_concept(self._kg)
        due_map = due_priority_by_concept_for_kg(self._kg, limit=200)
        nba = self._kg.get_next_best_actions(user_pct, limit=8, due_priority=due_map)

        daily_plan: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in nba:
            c = str(row.get("concept") or "").strip()
            if not c or c in seen:
                continue
            seen.add(c)
            m = float(user_pct.get(c, 0.0))
            gain = min(22, max(4, int((100.0 - m) * 0.18)))
            daily_plan.append(
                {
                    "concept": c,
                    "topic": c,
                    "minutes": 25,
                    "mastery_gain": gain,
                    "kind": "next_best",
                }
            )
            if len(daily_plan) >= min(7, d):
                break

        for w in weak_spots:
            if w in seen:
                continue
            seen.add(w)
            m = float(user_pct.get(w, 0.0))
            gain = min(22, max(6, int((100.0 - m) * 0.2)))
            daily_plan.append(
                {
                    "concept": w,
                    "topic": w,
                    "minutes": 20,
                    "mastery_gain": gain,
                    "kind": "weak_spot",
                }
            )
            if len(daily_plan) >= min(7, d):
                break

        concepts = self._kg.get_concepts()
        n_nodes = len([x for x in concepts if isinstance(concepts.get(x), dict)])
        mastery_pct = float(base.get("mastery_percentage") or 0.0)
        forget_risk = min(
            1.0,
            (len(weak_spots) / max(1, n_nodes)) * 0.45 + (100.0 - mastery_pct) / 250.0,
        )
        retention_forecast = {
            "weekly_mastery": round(min(1.0, max(0.0, mastery_pct / 100.0)), 3),
            "forgetting_risk_7d": round(forget_risk, 3),
            "weak_concepts": weak_spots[:8],
        }

        today_min = 30
        if daily_plan:
            today_min = int(daily_plan[0].get("minutes") or 25) + 5

        time_estimate = {
            "today_minutes": today_min,
            "week_minutes": min(int(time_budget_hours * 60), today_min * d),
            "label_today": f"~{today_min} мин сегодня",
        }

        gamification: dict[str, Any] = {}
        try:
            from app.gamification_service import get_snapshot

            gamification = get_snapshot()
        except Exception as exc:  # noqa: BLE001 - optional gamification module
            logger.warning("learning_plan_gamification_snapshot_failed", exc_info=exc)
            gamification = {}

        plan_out: dict[str, Any] = {
            "generated_at": base.get("generated_at"),
            "goal": goal,
            "days": d,
            "daily_plan": daily_plan,
            "weekly_slots": [
                {"day": i + 1, "focus": daily_plan[i]["concept"], "minutes": daily_plan[i]["minutes"]}
                for i in range(min(d, len(daily_plan)))
            ],
            "time_estimate": time_estimate,
            "retention_forecast": retention_forecast,
            "next_best_actions": nba[:5],
            "weak_spots": weak_spots,
            "base_plan": base,
            "gamification": gamification,
        }
        adaptive_daily: dict[str, Any] | None = None
        if user_progress:
            try:
                today_iso = datetime.now(timezone.utc).date().isoformat()
                saved_adp = get_saved_adaptive_daily_plan()
                if saved_adp and str(saved_adp.get("date") or "") == today_iso:
                    adaptive_daily = saved_adp
            except Exception as _exc:  # noqa: BLE001
                logger.debug("adaptive_daily_plan_read_failed", exc_info=True)
                adaptive_daily = None
        plan_out["adaptive_daily_plan"] = adaptive_daily
        if adaptive_daily and isinstance(plan_out.get("time_estimate"), dict):
            rm = int(adaptive_daily.get("recommended_session_length_min") or 0)
            if rm > 0:
                te = plan_out["time_estimate"]
                te["today_minutes"] = rm
                te["label_today"] = f"~{rm} мин (Adaptive Daily Plan 19.5)"
                bal = adaptive_daily.get("new_reviews_balance")
                if bal:
                    te["adaptive_balance"] = bal
        plan_out["motivation_tip"] = generate_ai_coach_message(plan_out)
        plan_out["retention_insight"] = generate_retention_insight(plan_out)
        return plan_out

    def get_smart_resume(self) -> str:
        """Один концепт/тема для кнопки «Продолжить обучение»."""
        from app.visualization_service import dashboard

        rec = dashboard.get_mastery_data().get("next_recommendation") or {}
        t = rec.get("topic")
        if t:
            return str(t).strip()

        first_due = filter_due_reviews_for_kg(self._kg, limit=1)
        if first_due:
            c = str(first_due[0].get("concept") or "").strip()
            if c:
                return c

        user_pct = _mastery_percent_by_concept(self._kg)
        due_map = due_priority_by_concept_for_kg(self._kg, limit=200)
        nba = self._kg.get_next_best_actions(user_pct, limit=1, due_priority=due_map)
        if nba:
            return str(nba[0].get("concept") or "").strip()

        ids = [cid for cid, c in self._kg.get_concepts().items() if isinstance(c, dict)]
        topo = self._kg.topological_sort(ids)
        return topo[0] if topo else "general"


plan_service = DynamicLearningPlan()


__all__ = ["DynamicLearningPlan", "plan_service"]
