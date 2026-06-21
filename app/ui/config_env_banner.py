"""US-1.3: читаемое предупреждение о недостающих критичных env (без падения UI)."""
from __future__ import annotations

import streamlit as st


def render_config_env_banner() -> None:
    try:
        from app.config import get_settings

        s = get_settings()
        is_e2e_offline = bool(s.home_rag_e2e_offline)

        missing: list[str] = []
        if not (s.openai_api_key or "").strip():
            missing.append("OPENAI_API_KEY")
        if missing and not is_e2e_offline:
            st.warning(
                "Не заданы переменные окружения: **"
                + "**, **".join(missing)
                + "** — укажите их в `.env` (ориентир: `.env.example`). "
                "Без ключа запросы к LLM/embeddings при обращении к API завершатся ошибкой."
            )
    except Exception as exc:
        st.warning(f"Не удалось прочитать настройки из окружения: {exc}")
