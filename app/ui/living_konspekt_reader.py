"""Режим чтения Живого конспекта: собранный документ читается ЗДЕСЬ, а не только в vault.

До этого корзина показывала превью в 400 символов, а полный текст жил только в
сохранённом файле — «живой» конспект нельзя было прочитать живьём. Reader рендерит
сборку прямо во вкладке: главные мысли лекций → разделы по порядку (полный текст +
медиа-панель с таймкодами) → «Проверь себя».

Медиа-рендер приходит DI-параметром (``media_renderer``): reader не импортирует
``living_konspekt_view`` (view импортирует reader — без цикла), а тесты передают
заглушку и проверяют чистую сборку.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

import streamlit as st

MediaRenderer = Callable[[dict[str, Any]], None]


def reader_blocks(rows: list[dict[str, Any]]) -> list[Mapping[str, Any]]:
    """Чистая модель чтения: [{kind: heading|meta|body, ...}] по разделам корзины.

    Отделена от Streamlit: тесты проверяют порядок/содержимое без runtime.
    """
    blocks: list[Mapping[str, Any]] = []
    for row in rows:
        heading = str(row.get("heading_text") or "Без названия")
        source = Path(str(row.get("konspekt_md_abs") or "")).name
        blocks.append({"kind": "heading", "text": heading})
        blocks.append({"kind": "meta", "text": f"{source} · строки {row.get('line_start')}-{row.get('line_end')}"})
        blocks.append({"kind": "body", "text": str(row.get("text") or ""), "row": row})
    return blocks


def render_reader(rows: list[dict[str, Any]], *, media_renderer: MediaRenderer | None = None) -> None:
    """Отрендерить собранный конспект как документ для чтения."""
    if not rows:
        st.info("Разделов пока нет — добавьте их во вкладке «🧩 Разделы».")
        return

    from app.ui.living_konspekt_view import _check_questions_block, _lecture_main_ideas

    for doc_name, idea in _lecture_main_ideas(rows):
        st.markdown(f"> **Главная мысль ({doc_name}):** {idea}")

    for block in reader_blocks(rows):
        if block["kind"] == "heading":
            st.markdown(f"## {block['text']}")
        elif block["kind"] == "meta":
            st.caption(block["text"])
        else:
            st.markdown(block["text"])
            if media_renderer is not None:
                media_renderer(block["row"])
            st.divider()

    questions = _check_questions_block(rows)
    if questions:
        st.markdown(questions)
