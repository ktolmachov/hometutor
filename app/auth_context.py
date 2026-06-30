"""Текущий user_id запроса/rerun через contextvar.

Без зависимостей на config/db (во избежание циклов с app.user_state_db).
Используется как точка переключения per-user изоляции state-БД
(см. app/user_state_db.py::_connect) и как источник identity для роутеров/UI.

Внимание: contextvars не наследуются автоматически новым OS-потоком
(threading.Thread / ThreadPoolExecutor.submit). В местах, где tutor chat
запускает query_service в worker-потоке (app/ui/tutor_chat_session.py),
нужно явно пробросить контекст через `contextvars.copy_context().run(...)`.
"""
from __future__ import annotations

import contextvars

_current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_user_id", default=None
)


def get_current_user_id() -> str | None:
    """ID текущего пользователя или None (auth выключен / системный контекст)."""
    return _current_user_id.get()


def set_current_user_id(user_id: str | None) -> contextvars.Token:
    """Установить user_id для текущего контекста; вернуть token для reset_current_user_id."""
    return _current_user_id.set(user_id)


def reset_current_user_id(token: contextvars.Token) -> None:
    """Откатить contextvar к значению до соответствующего set_current_user_id."""
    _current_user_id.reset(token)
