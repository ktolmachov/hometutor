"""Баннер offline / недоступности LLM."""
from __future__ import annotations

import streamlit as st


def _missing_required_env() -> list[str]:
    """Возвращает список критичных env, которые реально отсутствуют."""
    try:
        from app.config import get_settings

        settings = get_settings()
    except Exception:  # noqa: BLE001 - config load is best-effort here
        return []

    missing: list[str] = []
    if not (getattr(settings, "openai_api_key", "") or "").strip():
        missing.append("OPENAI_API_KEY")
    return missing


def render_offline_banner() -> None:
    """Индикатор OFFLINE_MODE и (опционально) probe к LLM base URL."""
    try:
        from app.config import get_settings

        is_e2e_offline = bool(get_settings().home_rag_e2e_offline)
    except Exception:  # noqa: BLE001 - config load is best-effort here
        is_e2e_offline = False

    missing_env = _missing_required_env()
    if missing_env and not is_e2e_offline:
        st.warning(
            "Не заданы обязательные переменные окружения: **"
            + "**, **".join(missing_env)
            + "**. Откройте `.env.example`, добавьте значения в `.env` и перезапустите приложение."
        )

    try:
        from app.offline_service import get_offline_status

        stt = get_offline_status()
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return
    if stt.get("offline_mode"):
        st.warning(
            "Режим offline (OFFLINE_MODE): ядро всё ещё использует OpenAI-compatible API из настроек; "
            "полный локальный Ollama в provider не подключён — см. app/offline_service.py."
        )
    elif stt.get("llm_reachable") is False:
        st.error("LLM endpoint недоступен (проверка lmstudio_api_base). Проверьте сеть и ключ.")
