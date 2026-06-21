"""
Обработчики Telegram-бота (aiogram): те же сервисы, что API/Streamlit, без отдельного backend.

Ограничения: один процесс = один локальный пользователь; нет облачной привязки аккаунтов.
"""

from __future__ import annotations

import asyncio
import logging
import re
from types import SimpleNamespace
from typing import Any

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message

from app import api_services as services
from app.gamification_service import record_quiz_activity
from app.guardrails import InputGuardrailError
from app.input_validation import validate_llm_input_text
from app.learning_plan_service import plan_service
from app.quiz_service import generate_scoped_quiz

logger = logging.getLogger(__name__)

router = Router(name="telegram")

# chat_id -> активная сессия scoped quiz
_QUIZ_SESSIONS: dict[int, dict[str, Any]] = {}

# E9.5 / US-10.3: честное сравнение второго клиента со Streamlit (текст /help).
TELEGRAM_HELP_TEXT = (
    "home-rag в Telegram — упрощённый клиент к тому же локальному API и SQLite, что и Streamlit.\n\n"
    "В боте: /ask и /tutor (в т.ч. /continue), квиз /quiz, экспорт /export, привязка /link, сброс /cancel; "
    "одна сессия tg-* на чат (как session_id в API).\n\n"
    "Только в Streamlit: вкладки «Темы», synthesis и learning plan в полном виде, карточки источников с "
    "маршрутом retrieval и подсказками доверия, дашборды прогресса и adaptive plan в привычном UI.\n\n"
    "Подробности: doc/user_guide.md (раздел «Telegram и Streamlit»)."
)


def telegram_session_id(chat_id: int) -> str:
    return f"tg-{int(chat_id)}"


def parse_quiz_scope_arg(arg: str) -> tuple[str, str] | None:
    raw = (arg or "").strip()
    if not raw:
        return None
    low = raw.lower()
    if low.startswith("document:"):
        return "document", raw.split(":", 1)[1].strip()
    if low.startswith("topic:"):
        return "topic", raw.split(":", 1)[1].strip()
    return None


def _parse_command_tail(text: str) -> str:
    parts = (text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _chunk_text(text: str, limit: int = 3900) -> list[str]:
    t = (text or "").strip()
    if not t:
        return ["(пустой ответ)"]
    return [t[i : i + limit] for i in range(0, len(t), limit)]


def _run_ask(*, question: str, query_mode: str | None, session_id: str | None) -> dict[str, Any]:
    ns = SimpleNamespace(
        question=question,
        query_mode=query_mode,
        session_id=session_id,
        homework_mode=False,
        study_mode=False,
        homework_level=None,
        folder=None,
        folder_rel=None,
        file_name=None,
        relative_path=None,
        topic=None,
        followup_context=None,
    )
    validated = services.prepare_ask_request(ns)
    return services.answer_question(validated.question, validated.options)


class _InQuizFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.chat.id in _QUIZ_SESSIONS


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(
        "home-rag: локальный RAG + tutor. Кратко — /help\n"
        "Команды: /ask, /tutor, /continue, /quiz, /export, /link, /cancel. Сессия tg-*; один SQLite с Streamlit."
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(TELEGRAM_HELP_TEXT)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message) -> None:
    _QUIZ_SESSIONS.pop(message.chat.id, None)
    await message.answer("Квиз сброшен.")


@router.message(Command("ask"))
async def cmd_ask(message: Message) -> None:
    q = _parse_command_tail(message.text or "")
    if not q:
        await message.answer("Использование: /ask <вопрос>")
        return
    sid = telegram_session_id(message.chat.id)
    try:
        result = await asyncio.to_thread(_run_ask, question=q, query_mode=None, session_id=sid)
    except InputGuardrailError as e:
        await message.answer(f"Ввод отклонён: {e}")
        return
    except Exception as e:
        logger.exception("telegram ask failed")
        await message.answer(f"Ошибка: {e}")
        return
    ans = str((result or {}).get("answer") or "")
    for part in _chunk_text(ans):
        await message.answer(part)


@router.message(Command("tutor"))
async def cmd_tutor(message: Message) -> None:
    q = _parse_command_tail(message.text or "")
    if not q:
        await message.answer("Использование: /tutor <вопрос или тема>")
        return
    sid = telegram_session_id(message.chat.id)
    try:
        result = await asyncio.to_thread(_run_ask, question=q, query_mode="tutor", session_id=sid)
    except InputGuardrailError as e:
        await message.answer(f"Ввод отклонён: {e}")
        return
    except Exception as e:
        logger.exception("telegram tutor failed")
        await message.answer(f"Ошибка: {e}")
        return
    ans = str((result or {}).get("answer") or "")
    for part in _chunk_text(ans):
        await message.answer(part)


@router.message(Command("continue"))
async def cmd_continue(message: Message) -> None:
    try:
        nxt = await asyncio.to_thread(plan_service.get_smart_resume)
    except Exception as e:
        logger.warning("get_smart_resume: %s", e)
        nxt = "general"
    await message.answer(
        f"Следующий шаг (эвристика / граф): {nxt}\n\n"
        f"Продолжить квизом: /quiz topic:{nxt}"
    )


@router.message(Command("quiz"))
async def cmd_quiz(message: Message) -> None:
    arg = _parse_command_tail(message.text or "")
    parsed = parse_quiz_scope_arg(arg)
    if not parsed:
        await message.answer('Укажите область: /quiz document:path/to.md или /quiz topic:Имя темы')
        return
    scope, ident = parsed
    try:
        ident = validate_llm_input_text(ident, field_name="identifier", required=True, max_chars=512) or ""
    except InputGuardrailError as e:
        await message.answer(f"Input rejected: {e}")
        return
    await message.answer("Генерирую квиз…")
    try:
        quiz = await asyncio.to_thread(generate_scoped_quiz, scope, ident)
    except Exception as e:
        logger.exception("scoped quiz failed")
        await message.answer(f"Ошибка квиза: {e}")
        return
    if not quiz.get("success"):
        await message.answer(quiz.get("error") or "Не удалось сгенерировать квиз.")
        return
    qs = list(quiz.get("questions") or [])
    if not qs:
        await message.answer("Пустой квиз.")
        return
    _QUIZ_SESSIONS[message.chat.id] = {
        "questions": qs,
        "idx": 0,
        "correct": 0,
        "scope": scope,
    }
    mot = (quiz.get("motivational_message") or "").strip()
    if mot:
        await message.answer(mot[:3900])
    await _send_quiz_question(message, qs[0], 1, len(qs))


async def _send_quiz_question(message: Message, q: dict[str, Any], n: int, total: int) -> None:
    lines = [f"Вопрос {n}/{total}", "", (q.get("question") or "").strip(), ""]
    opts = q.get("options") or []
    for i, o in enumerate(opts):
        lines.append(f"{i + 1}. {o}")
    lines.append("")
    lines.append("Ответьте цифрой 1–4. /cancel — выйти.")
    await message.answer("\n".join(lines)[:3900])


@router.message(F.text, _InQuizFilter())
async def quiz_answer(message: Message) -> None:
    raw = (message.text or "").strip()
    m = re.match(r"^([1-4])$", raw)
    if not m:
        await message.answer("Ожидается цифра 1–4 или /cancel.")
        return
    choice = int(m.group(1)) - 1
    sess = _QUIZ_SESSIONS.get(message.chat.id)
    if not sess:
        return
    qs: list[dict[str, Any]] = sess["questions"]
    idx: int = sess["idx"]
    if idx >= len(qs):
        _QUIZ_SESSIONS.pop(message.chat.id, None)
        return
    q = qs[idx]
    correct_i = int(q.get("correct_index") or 0)
    if choice == correct_i:
        sess["correct"] = int(sess.get("correct") or 0) + 1
    sess["idx"] = idx + 1
    if sess["idx"] >= len(qs):
        total = len(qs)
        ok = int(sess["correct"])
        score = ok / max(1, total)
        try:
            gam = await asyncio.to_thread(
                record_quiz_activity,
                score_0_1=score,
                scope="scoped",
            )
        except Exception as e:
            logger.warning("record_quiz_activity: %s", e)
            gam = {}
        _QUIZ_SESSIONS.pop(message.chat.id, None)
        xp = gam.get("xp_gained", "—")
        await message.answer(f"Готово: {ok}/{total}. +{xp} XP. Уровень: {gam.get('level_title', '—')}")
        return
    await _send_quiz_question(message, qs[sess["idx"]], sess["idx"] + 1, len(qs))


@router.message(Command("export"))
async def cmd_export(message: Message) -> None:
    arg = (_parse_command_tail(message.text or "") or "").lower()
    if "anki" in arg:
        await message.answer(
            "Anki: полноценные колоды — из веб-UI (синтез / тьютор). "
            "Снимок прогресса: GET /sync/export на локальном API."
        )
        return
    if "notion" in arg:
        await message.answer(
            "Отдельного Notion-экспорта нет; используйте Markdown из UI или JSON через /sync/export."
        )
        return
    from app.sync_service import export_bundle_to_dict

    try:
        bundle = await asyncio.to_thread(export_bundle_to_dict)
    except Exception as e:
        await message.answer(f"Ошибка экспорта: {e}")
        return
    import json

    preview = json.dumps(bundle, ensure_ascii=False)[:3500]
    await message.answer(
        f"Фрагмент JSON (обрезано):\n```\n{preview}\n```\n\nПолный объём: GET /sync/export"
    )


@router.message(Command("link"))
async def cmd_link(message: Message) -> None:
    await message.answer(
        "Локальный режим: один файл user_state.db на машине — бот и Streamlit уже используют одни и те же данные.\n"
        "Перенос на другое устройство: GET /sync/export → POST /sync/import.\n"
        "Подробности: GET /sync/telegram на API."
    )


@router.message(F.voice)
async def handle_voice(message: Message) -> None:
    await message.answer(
        "Голос: Telegram отдаёт OGG/Opus; текущий VoiceService ориентирован на WAV/микрофон в Streamlit. "
        "Используйте текст или добавьте конвертацию (ffmpeg/pydub) / Whisper API."
    )


__all__ = [
    "parse_quiz_scope_arg",
    "router",
    "telegram_session_id",
]
