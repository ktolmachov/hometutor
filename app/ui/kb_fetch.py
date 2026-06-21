"""Тонкие GET к KB из UI (без кэша st.cache_data — подсказки зависят от вопроса)."""
from __future__ import annotations

from app.ui_client import fetch_json


def fetch_kb_suggestions(question: str, source_paths: list[str]):
    try:
        sources_param = ",".join(source_paths) if source_paths else ""
        return fetch_json("GET", "/kb/suggestions", timeout=10, params={"question": question, "sources": sources_param})
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return None


def fetch_kb_search(query: str):
    try:
        return fetch_json("GET", "/kb/search", timeout=10, params={"q": query})
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        return None
