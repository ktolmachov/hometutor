"""Короткий TTL-кэш для частых GET flashcards (due count, список колод).

Streamlit перезапускает скрипт на каждый rerun; без кэша одни и те же
запросы дублируются десятки раз за сессию повторения.

Иерархия запросов:
  flashcards_bootstrap()  — 1 HTTP-запрос → {due_count, decks} (TTL 5 s)
  flashcards_due_count()  — для параметризованных запросов с deck_id/tags (TTL 3 s)
  flashcards_decks_list() — резервный прямой запрос к /decks (TTL 5 s)

Компоненты, которым нужны оба поля одновременно (flashcards_ui + flashcards_review_view),
используют flashcards_bootstrap() — один HTTP-запрос на пару, а не два.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.ui_client import fetch_json

FlashDueKey = tuple[tuple[str, str], ...]


def due_count_cache_key(params: dict[str, Any] | None) -> FlashDueKey:
    if not params:
        return ()
    items: list[tuple[str, str]] = []
    for k in sorted(params.keys()):
        v = params[k]
        if v is None or v == "":
            continue
        items.append((str(k), str(v)))
    return tuple(items)


@st.cache_data(show_spinner=False, ttl=30)
def flashcards_bootstrap(_singleton: str = "v1") -> dict[str, Any]:
    """Single HTTP call → {due_count, decks}. Shared cache across components per render cycle."""
    _ = _singleton
    r = fetch_json("GET", "/flashcards/bootstrap", timeout=30)
    return {"due_count": int(r.get("due_count") or 0), "decks": list(r.get("decks") or [])}


@st.cache_data(show_spinner=False, ttl=30)
def flashcards_due_count(_scope_key: FlashDueKey) -> int:
    """Parameterised due count (deck_id / tags filter). Use flashcards_bootstrap() for unscoped."""
    q = dict(_scope_key) if _scope_key else {}
    r = fetch_json("GET", "/flashcards/due/count", timeout=30, params=q or None)
    return int(r.get("count") or 0)


@st.cache_data(show_spinner=False, ttl=30)
def flashcards_decks_list(_singleton: str = "v1") -> list[dict[str, Any]]:
    """Direct /decks call. Prefer flashcards_bootstrap() when due_count is also needed."""
    _ = _singleton
    r = fetch_json("GET", "/flashcards/decks", timeout=30)
    return list(r.get("decks") or [])


def invalidate_flashcards_due_counts_only() -> None:
    """После POST /flashcards/review — счётчики due меняются, список колод нет."""
    flashcards_due_count.clear()
    flashcards_bootstrap.clear()


def invalidate_flashcards_read_cache() -> None:
    """Полный сброс: создание/удаление колоды, recovery, импорт из quiz."""
    flashcards_due_count.clear()
    flashcards_decks_list.clear()
    flashcards_bootstrap.clear()


__all__ = [
    "due_count_cache_key",
    "flashcards_bootstrap",
    "flashcards_decks_list",
    "flashcards_due_count",
    "invalidate_flashcards_due_counts_only",
    "invalidate_flashcards_read_cache",
]
