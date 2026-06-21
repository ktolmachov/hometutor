"""Дашборд освоения концептов (quiz + spaced repetition + граф)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from app.config import get_settings
from app.analytics_service import get_advanced_analytics
from app.learning_plan_service import plan_service
from app.offline_service import get_offline_status
from app.visualization_service import dashboard

router = APIRouter(tags=["dashboard"])


def _load_e2e_payload(name: str) -> dict:
    pkg = Path(__file__).resolve().parents[1] / "offline_payloads" / name
    if not pkg.exists():
        pkg = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "fixtures" / "offline_payloads" / name
    return json.loads(pkg.read_text(encoding="utf-8"))


@router.get("/dashboard/mastery")
def get_mastery_dashboard():
    """Сводка Progress: quiz_mastery, due SM-2, mastery_vector, weekly_goals, gamification, prerequisite_graph.

    Поля — см. ``MasteryDashboard.get_mastery_data`` в ``app/visualization_service.py``.
    """
    if get_settings().home_rag_e2e_offline:
        return _load_e2e_payload("scenario_07.json")
    return dashboard.get_mastery_data()


@router.get("/dashboard/coach_plan")
def get_coach_plan(days: int = 7):
    """Персональный план AI Coach (слабые места, NBA, эвристики времени)."""
    if get_settings().home_rag_e2e_offline:
        return _load_e2e_payload("scenario_09.json")
    d = max(1, min(14, int(days)))
    return plan_service.generate_personalized_plan(days=d, user_progress=True)


@router.get("/dashboard/adaptive_daily_plan")
def get_adaptive_daily_plan():
    """План на сегодня (19.5). Сначала снимок из KV за сегодня (UTC); иначе пересчёт и сохранение."""
    from datetime import datetime, timezone

    from app.learning_plan_service import AdaptiveDailyPlan, get_saved_adaptive_daily_plan

    if get_settings().home_rag_e2e_offline:
        return _load_e2e_payload("scenario_09.json")
    today = datetime.now(timezone.utc).date().isoformat()
    saved = get_saved_adaptive_daily_plan()
    if saved and str(saved.get("date") or "") == today:
        return saved
    return AdaptiveDailyPlan("local").build_adaptive_daily_plan()


@router.get("/dashboard/analytics")
def get_dashboard_analytics():
    """Heatmap quiz, эвристическая кривая забывания, ROI по времени, рекомендации."""
    return get_advanced_analytics()


@router.get("/dashboard/offline_status")
def get_offline_dashboard_status():
    """Флаг offline_mode и (опционально) probe до LLM base URL для индикатора в UI/клиентах."""
    return get_offline_status()


__all__ = ["router"]
