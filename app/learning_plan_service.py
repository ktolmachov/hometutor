"""
Публичный фасад учебного плана: генерация шагов и coach-план
(``app/learning_plan_generation``), адаптивные снимки и next-step после quiz
(``app/learning_plan_adaptive``).

Наружу сохраняется прежний импорт ``app.learning_plan_service``; внутреннее разбиение —
AR-2026-05-02-003 / P5D.
"""

from __future__ import annotations

from app.adaptive_plan import (
    ADAPTIVE_DAILY_PLAN_KV_KEY,
    AdaptiveDailyPlan,
    get_adaptive_daily_plan_history,
)
from app.learning_plan_adaptive import (
    attach_confidence_dip_metadata,
    get_adaptive_daily_plan_for_orchestrator,
    get_recommended_next_step_after_micro_quiz,
    get_saved_adaptive_daily_plan,
)
from app.learning_plan_generation import DynamicLearningPlan, plan_service

__all__ = [
    "ADAPTIVE_DAILY_PLAN_KV_KEY",
    "AdaptiveDailyPlan",
    "attach_confidence_dip_metadata",
    "DynamicLearningPlan",
    "get_adaptive_daily_plan_for_orchestrator",
    "get_adaptive_daily_plan_history",
    "get_recommended_next_step_after_micro_quiz",
    "get_saved_adaptive_daily_plan",
    "plan_service",
]
