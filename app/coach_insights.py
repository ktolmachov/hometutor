"""Короткие текстовые подсказки AI Coach для learning plan (без LLM)."""

from __future__ import annotations

from typing import Any


def generate_ai_coach_message(plan: dict[str, Any]) -> str:
    """Одна строка-мотивация по структуре ``generate_personalized_plan``."""
    daily = plan.get("daily_plan") or []
    if not isinstance(daily, list) or not daily:
        return "Добавьте концепты в граф и пройдите quiz — план станет персональным."

    first = daily[0] if isinstance(daily[0], dict) else {}
    concept = str(first.get("concept") or first.get("topic") or "").strip()
    gain = first.get("mastery_gain")
    minutes = first.get("minutes")

    parts: list[str] = []
    if concept:
        parts.append(f"Сегодня логично сфокусироваться на «{concept}».")
    if isinstance(gain, (int, float)) and isinstance(minutes, (int, float)):
        parts.append(f"Оценка: около {int(minutes)} мин и до ~{int(gain)}% к освоению по теме шага.")
    elif isinstance(minutes, (int, float)):
        parts.append(f"Заложи около {int(minutes)} мин на этот шаг.")

    streak = (plan.get("gamification") or {}).get("daily_streak")
    if isinstance(streak, int) and streak > 0:
        parts.append(f"Стрик {streak} дн. — короткая сессия сегодня поможет его сохранить.")

    return " ".join(parts) if parts else "Продолжай по плану — следующий шаг уже в daily_plan."


def generate_retention_insight(plan: dict[str, Any]) -> str:
    """Пояснение к блоку retention forecast (эвристика, не «медицинский» прогноз)."""
    rf = plan.get("retention_forecast") or {}
    if not isinstance(rf, dict):
        return ""
    risk = rf.get("forgetting_risk_7d")
    if isinstance(risk, (int, float)) and risk > 0.35:
        return (
            "Несколько концептов с низким уровнем quiz: без повторения за неделю "
            "они могут «ослабнуть» в очереди — полезны короткие интервальные повторы."
        )
    return "Повторения по SM-2 и interleaved quiz помогают удерживать материал в долгой памяти."


__all__ = ["generate_ai_coach_message", "generate_retention_insight"]
