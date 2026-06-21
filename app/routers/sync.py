"""Локальный экспорт/импорт снимка прогресса (без облака)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from app.sync_service import export_bundle_to_dict, import_bundle_from_dict

router = APIRouter(tags=["sync"])


@router.get("/sync/export")
def sync_export() -> dict[str, Any]:
    """Полный JSON для сохранения и переноса на другое устройство."""
    return export_bundle_to_dict()


@router.post("/sync/import")
def sync_import(bundle: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Восстановление из JSON (перезаписывает локальные таблицы user_state)."""
    return import_bundle_from_dict(bundle)


@router.get("/sync/telegram")
def sync_telegram_info() -> dict[str, Any]:
    """
    Справка по связке Telegram-бота с локальным инстансом.

    Полноценная синхронизация «облако ↔ веб» не заявлена: бот на той же машине
    использует тот же ``user_state.db``, что и Streamlit.
    """
    return {
        "mode": "local_single_user",
        "message": (
            "Бот и веб на одной машине делят один SQLite (user_state.db). "
            "Перенос на другое устройство: GET /sync/export и POST /sync/import."
        ),
        "export_path": "/sync/export",
        "import_path": "/sync/import",
    }


__all__ = ["router"]
