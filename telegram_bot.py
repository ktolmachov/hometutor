"""
Точка входа Telegram-бота (aiogram). Запускать рядом с API/Streamlit на той же машине.

Требуется в .env: TELEGRAM_BOT_TOKEN=...
Опционально: TELEGRAM_DAILY_REMINDER_CHAT_ID, TELEGRAM_DAILY_REMINDER_HOUR
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app.config import get_settings
from app.telegram_handlers import router
from app.telegram_notifications import start_notifications


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    s = get_settings()
    token = (s.telegram_bot_token or "").strip()
    if not token:
        print("Set TELEGRAM_BOT_TOKEN in .env", file=sys.stderr)
        raise SystemExit(2)
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=None))
    dp = Dispatcher()
    dp.include_router(router)
    start_notifications(bot)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
