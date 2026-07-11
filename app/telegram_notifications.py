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


def _safe_due_flashcards() -> int:
    try:
        from app.user_state import count_due_flashcards

        return int(count_due_flashcards())
    except Exception:  # noqa: BLE001
        return 0


def _safe_due_reviews() -> int:
    try:
        from app.spaced_repetition import count_due_reviews

        return int(count_due_reviews())
    except Exception:  # noqa: BLE001
        return 0


def _daily_topic_line() -> str | None:
    """Primary topic for today from the canonical cross-channel source.

    Returns ``"Сегодня: {topic}"`` from the saved adaptive daily plan, or
    ``None`` when no plan for today exists (the caller falls back to a
    generic message).
    """
    from app.learning_plan_service import get_today_primary_learning_item

    item = get_today_primary_learning_item()
    if item:
        topic = str(item.get("topic") or "").strip()
        if topic:
            return f"Сегодня: {topic}"
    return None


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
        try:
            parts: list[str] = []

            topic_line = _daily_topic_line()
            if topic_line:
                parts.append(topic_line)

            due_cards = _safe_due_flashcards()
            due_concepts = _safe_due_reviews()
            if due_cards > 0 or due_concepts > 0:
                from app.flashcard_service import estimate_flashcard_due_clear_minutes

                effort = estimate_flashcard_due_clear_minutes(due_cards) if due_cards > 0 else 0
                pieces: list[str] = []
                if due_cards > 0:
                    pieces.append(f"{due_cards} карточек")
                if due_concepts > 0:
                    pieces.append(f"{due_concepts} концептов")
                line = "К повторению: " + ", ".join(pieces)
                if effort > 0:
                    line += f" · около {effort} мин"
                parts.append(line)

            if not parts:
                parts.append("Откройте приложение для персонального плана")

            ui_url = s.streamlit_ui_url.rstrip("/")
            parts.append(ui_url)

            await bot.send_message(chat_id, "\n".join(parts))
        except Exception as e:
            logger.warning("daily_reminder failed: %s", e)

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(daily_reminder, "cron", hour=hour, minute=0)
    _scheduler.start()
    logger.info("telegram daily reminder scheduled at %s:00 for chat %s", hour, chat_id)


__all__ = ["start_notifications"]
