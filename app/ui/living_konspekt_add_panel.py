"""Панель «Добавить разделы» Живого конспекта: вход в фичу ИЗНУТРИ.

До этой панели корзина наполнялась только снаружи (Knowledge Graph, Flashcards),
а пустой «Живой конспект» был тупиком. Здесь два пути:

* обзор: выбрать конспект из ``DATA_DIR`` → список разделов → «➕»;
* поиск: строка запроса → релевантные разделы по всем конспектам
  (``section_index.top_sections_for``, локально, без LLM).

Чистые функции (``discover_konspekt_documents``, ``search_sections_across``)
отделены от рендера — тестируются без Streamlit runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from app.section_index import IndexedSection, parse_sections, top_sections_for

_MAX_DOCUMENTS = 50
_SEARCH_DOCUMENTS = 20
_SEARCH_RESULTS = 8
_PER_DOC_RESULTS = 3
_MIN_SECTION_LEVEL = 2
_NOISE_HEADINGS = {"оглавление", "содержание", "toc"}


@dataclass(frozen=True)
class WorkbenchDocument:
    md_abs: Path
    title: str
    mtime: float


def discover_konspekt_documents(data_dir: Path, *, limit: int = _MAX_DOCUMENTS) -> list[WorkbenchDocument]:
    """Markdown-документы DATA_DIR (без ``users/``), свежие сверху.

    Недоступный каталог → пустой список: панель молчит, корзина работает.
    """
    if not data_dir.is_dir():
        return []
    docs: list[WorkbenchDocument] = []
    for path in data_dir.rglob("*.md"):
        if "users" in path.relative_to(data_dir).parts:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        docs.append(WorkbenchDocument(md_abs=path, title=path.stem, mtime=mtime))
    docs.sort(key=lambda d: -d.mtime)
    return docs[:limit]


def _normalized_heading(heading: str) -> str:
    return heading.strip().lower().strip("📑#:- ")


def _content_sections(sections: list[IndexedSection]) -> list[IndexedSection]:
    return [
        s
        for s in sections
        if s.level >= _MIN_SECTION_LEVEL
        and (s.own_text or s.text).strip()
        and _normalized_heading(s.heading_text) not in _NOISE_HEADINGS
    ]


def sections_of_document(md_abs: Path) -> list[IndexedSection]:
    """Содержательные разделы одного документа (H2+, непустые); ошибки → []."""
    try:
        sections = [
            IndexedSection(
                heading_text=section.heading_text,
                slug=section.slug,
                level=section.level,
                line_start=section.line_start,
                line_end=section.line_end,
                text=section.text,
                own_text=section.own_text,
                source_abs=md_abs,
                konspekt_md_abs=md_abs,
            )
            for section in parse_sections(md_abs)
        ]
        return _content_sections(sections)
    except (OSError, ValueError):
        return []


def search_sections_across(
    documents: list[WorkbenchDocument],
    query: str,
    *,
    max_documents: int = _SEARCH_DOCUMENTS,
    max_results: int = _SEARCH_RESULTS,
) -> list[IndexedSection]:
    """Релевантные разделы по нескольким конспектам (детерминированно, без LLM).

    Порядок: свежие документы раньше, внутри документа — по релевантности
    (``top_sections_for``). Пустой запрос → [].
    """
    if not query.strip():
        return []
    found: list[IndexedSection] = []
    for doc in documents[:max_documents]:
        sections = sections_of_document(doc.md_abs)
        if not sections:
            continue
        for section in top_sections_for(sections, query, k=_PER_DOC_RESULTS):
            found.append(section)
            if len(found) >= max_results:
                return found
    return found


# ── Рендер ──────────────────────────────────────────────────────────────


def _data_dir() -> Path:
    from app.path_safety import resolve_data_relative_path

    return resolve_data_relative_path(".")


def _document_label(doc: WorkbenchDocument, data_dir: Path) -> str:
    try:
        rel = doc.md_abs.relative_to(data_dir)
    except ValueError:
        rel = doc.md_abs
    return str(rel)


def _add_button(section: IndexedSection, key: str) -> None:
    from app.ui.living_konspekt_view import add_section_to_workbench

    if st.button("➕", key=key, help="Добавить раздел в конспект"):
        added = add_section_to_workbench(section)
        st.toast(
            f"Добавлено: «{section.heading_text}»" if added else "Уже в конспекте",
            icon="📚",
        )
        st.rerun()


def _render_section_pick_row(section: IndexedSection, key: str) -> None:
    cols = st.columns([6, 1])
    with cols[0]:
        st.markdown(f"**{section.heading_text}**")
        st.caption(
            f"{Path(str(section.konspekt_md_abs)).name} · строки {section.line_start}-{section.line_end}"
        )
        preview = (section.own_text or section.text).strip()
        if preview:
            st.caption(preview[:180] + ("…" if len(preview) > 180 else ""))
    with cols[1]:
        _add_button(section, key)


def render_add_sections_panel(*, expanded: bool = False) -> None:
    """Обзор документов + локальный поиск разделов → «➕ в конспект»."""
    data_dir = _data_dir()
    documents = discover_konspekt_documents(data_dir)
    with st.expander("📥 Добавить разделы", expanded=expanded):
        if not documents:
            st.caption("В data/ нет markdown-конспектов — проиндексируйте материалы.")
            return

        query = st.text_input(
            "Поиск раздела по всем конспектам",
            key="wb_add_search_query",
            placeholder="например: температура и семплирование",
        )
        if query.strip():
            results = search_sections_across(documents, query)
            if not results:
                st.caption("Ничего не найдено — попробуйте другие термины.")
            for i, section in enumerate(results):
                _render_section_pick_row(section, key=f"wb_add_search_{i}")
            st.divider()

        doc = st.selectbox(
            "Или откройте конспект целиком",
            documents,
            format_func=lambda item: _document_label(item, data_dir),
            key="wb_add_doc_pick",
        )
        sections = sections_of_document(doc.md_abs)
        if not sections:
            st.caption("В документе нет содержательных разделов (H2+).")
            return
        st.caption(f"{len(sections)} раздел(ов) — добавляйте нужные или весь документ разом.")
        if st.button("➕ Добавить все разделы документа", key="wb_add_doc_all"):
            from app.ui.living_konspekt_view import add_section_to_workbench

            added = sum(1 for s in sections if add_section_to_workbench(s))
            st.toast(f"Добавлено разделов: {added} (из {len(sections)})", icon="📚")
            st.rerun()
        for i, section in enumerate(sections[:40]):
            _render_section_pick_row(section, key=f"wb_add_doc_{i}")
