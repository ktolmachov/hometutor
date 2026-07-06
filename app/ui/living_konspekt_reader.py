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
SaveNote = Callable[[str, str], None]
MarkRead = Callable[[str], None]
TOC_THRESHOLD = 8


def _reader_anchor(index: int) -> str:
    return f"lk-reader-{index + 1}"


def reader_toc(rows: list[dict[str, Any]], *, threshold: int = TOC_THRESHOLD) -> list[Mapping[str, Any]]:
    """Оглавление reader-а для длинных сборок."""
    if len(rows) < threshold:
        return []
    items: list[Mapping[str, Any]] = []
    for index, row in enumerate(rows):
        heading = str(row.get("heading_text") or "Без названия")
        source = Path(str(row.get("konspekt_md_abs") or "")).name
        items.append({"label": heading, "source": source, "anchor": _reader_anchor(index)})
    return items


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


def render_reader(
    rows: list[dict[str, Any]],
    *,
    media_renderer: MediaRenderer | None = None,
    save_note: SaveNote | None = None,
    mark_read: MarkRead | None = None,
) -> None:
    """Отрендерить собранный конспект как документ для чтения."""
    if not rows:
        st.info("Разделов пока нет — добавьте их во вкладке «🧩 Разделы».")
        return

    from app.ui.living_konspekt_view import _check_questions_block, _lecture_main_ideas

    for doc_name, idea in _lecture_main_ideas(rows):
        st.markdown(f"> **Главная мысль ({doc_name}):** {idea}")

    toc = reader_toc(rows)
    if toc:
        st.markdown("### Оглавление")
        toc_lines = [
            f"- [{item['label']}](#{item['anchor']})"
            + (f" · {item['source']}" if item.get("source") else "")
            for item in toc
        ]
        st.markdown("\n".join(toc_lines))
        st.divider()

    section_index = 0
    for block in reader_blocks(rows):
        if block["kind"] == "heading":
            st.markdown(f"<span id='{_reader_anchor(section_index)}'></span>", unsafe_allow_html=True)
            st.markdown(f"## {block['text']}")
            section_index += 1
        elif block["kind"] == "meta":
            st.caption(block["text"])
        else:
            st.markdown(block["text"])
            if media_renderer is not None:
                media_renderer(block["row"])
            row = block["row"]
            row_key = str(row.get("row_key") or "")
            if row_key and (save_note is not None or mark_read is not None):
                _render_section_progress_controls(row, save_note=save_note, mark_read=mark_read)
            st.divider()

    questions = _check_questions_block(rows)
    if questions:
        st.markdown(questions)


def _render_section_progress_controls(
    row: Mapping[str, Any],
    *,
    save_note: SaveNote | None,
    mark_read: MarkRead | None,
) -> None:
    row_key = str(row.get("row_key") or "")
    note_value = str(row.get("note") or "")
    read_at = str(row.get("read_at") or "")
    note_key = f"lk_reader_note_{row_key}"
    st.text_area("Моя мысль", value=note_value, key=note_key, height=90)
    cols = st.columns([1, 1, 3])
    with cols[0]:
        if st.button("Сохранить", key=f"lk_reader_save_note_{row_key}", width="stretch", disabled=save_note is None):
            save_note(row_key, str(st.session_state.get(note_key) or ""))
            st.toast("Мысль сохранена.", icon="💬")
            st.rerun()
    with cols[1]:
        if st.button("Прочитано", key=f"lk_reader_mark_read_{row_key}", width="stretch", disabled=mark_read is None):
            mark_read(row_key)
            st.toast("Фрагмент отмечен как прочитанный.", icon="✓")
            st.rerun()
    with cols[2]:
        if read_at:
            st.caption(f"Прочитано: {read_at}")
