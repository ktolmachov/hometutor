"""
Опциональные напоминания по расписанию (APScheduler): один chat_id из настроек.

Мультипользовательский broadcast без таблицы пользователей не поддерживается (KISS).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import get_settings

if TYPE_CHECKING:
    from aiogram import Bot

logger = logging.getLogger(__name__)

_scheduler = None


def start_notifications(bot: "Bot") -> None:
    global _scheduler
    s = get_settings()
    raw = (s.telegram_daily_reminder_chat_id or "").strip()
    if not raw:
        logger.info("telegram_daily_reminder_chat_id not set — daily job disabled")
        return
    try:
        chat_id = int(raw)
    except ValueError:
        logger.warning("telegram_daily_reminder_chat_id must be an integer")
        return

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
    except ImportError:
        logger.warning("apscheduler not installed — daily reminders disabled")
        return

    hour = int(s.telegram_daily_reminder_hour)

    async def daily_reminder() -> None:
        from app.learning_plan_service import plan_service

        try:
            plan = plan_service.generate_personalized_plan(user_progress=True)
            dp = plan.get("daily_plan") or []
            if dp:
                d0 = dp[0]
                line = str(d0.get("concept") or d0.get("topic") or "").strip() or "см. план в UI"
            else:
                line = "откройте веб-приложение для персонального плана"
            await bot.send_message(chat_id, f"Сегодня: {line}")
        except Exception as e:
            logger.warning("daily_reminder failed: %s", e)

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(daily_reminder, "cron", hour=hour, minute=0)
    _scheduler.start()
    logger.info("telegram daily reminder scheduled at %s:00 for chat %s", hour, chat_id)


__all__ = ["start_notifications"]
