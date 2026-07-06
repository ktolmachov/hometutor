"""Вкладка «Дальше» Живого конспекта: проверка актуальности и deep-study промпт.

Вынесено из ``living_konspekt_view`` (файл был в size-budget списке нарушителей):
web-ссылки лектора, поисковые запросы по разделам корзины и промпт для внешних LLM.
Всё локально; облако — только по явному клику пользователя по ссылке.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.deep_study_prompt import build_deep_study_prompt
from app.section_index import row_to_section
from app.study_web_queries import (
    build_query_from_rows,
    build_query_terms,
    build_web_search_links,
    harvest_links_from_rows,
)

_EXTERNAL_LLM_TARGETS = (
    ("ChatGPT", "https://chatgpt.com/"),
    ("Claude", "https://claude.ai/new"),
    ("Gemini", "https://gemini.google.com/app"),
)


def render_web_queries_panel(rows: list[dict[str, Any]]) -> None:
    st.markdown("### 🌐 Проверить актуальность · источники")

    # «Источник этих знаний» без сети: ссылки, которые лектор сам приложил к материалу.
    lecture_links = harvest_links_from_rows(rows)
    if lecture_links:
        st.markdown("**🔗 Ссылки из лекции**")
        for label, url in lecture_links[:8]:
            st.markdown(f"- [{label}]({url})")

    query = build_query_from_rows(rows)
    if not query:
        # Разделы без концепта и с пустыми заголовками — фолбэк на свалку заголовков.
        heading_texts = [str(row.get("heading_text") or "") for row in rows]
        key_concepts = [str(row.get("concept") or "") for row in rows if row.get("concept")]
        query = build_query_terms(heading_texts=heading_texts, key_concepts=key_concepts)
    links = build_web_search_links(query)
    if not links:
        st.caption("Добавьте разделы, чтобы сформировать поисковый запрос.")
        return
    st.caption(f"Запрос: «{query}»")
    link_cols = st.columns(len(links))
    for col, (label, url) in zip(link_cols, links):
        with col:
            st.link_button(label, url, width="stretch")


def _collect_concept_context(rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Prerequisites/related_concepts для всех уникальных концептов, привязанных к разделам корзины.

    Раздел получает ``concept`` только когда его добавили из графа
    (``_render_document_section_workbench_buttons`` в ``dashboards_graph.py``); разделы из
    Flashcards приходят без концепта — тогда контекст пуст, и это ожидаемо (нет графовой
    привязки, откуда брать prerequisites).
    """
    concept_ids = sorted({str(row.get("concept") or "").strip() for row in rows if row.get("concept")})
    if not concept_ids:
        return [], []
    try:
        from app.knowledge_service import get_active_knowledge_graph

        kg = get_active_knowledge_graph()
        all_concepts = kg.get_concepts()
    except Exception:  # noqa: BLE001 - контекст концепта опционален для промпта
        return [], []

    prereqs: list[str] = []
    related: list[str] = []
    for cid in concept_ids:
        prereqs.extend(str(p) for p in kg.get_prerequisites(cid))
        info = all_concepts.get(cid) or {}
        related.extend(str(r) for r in (info.get("related_concepts") or []))

    exclude = set(concept_ids)
    prereqs_dedup = list(dict.fromkeys(p for p in prereqs if p and p not in exclude))
    related_dedup = list(dict.fromkeys(r for r in related if r and r not in exclude))
    return prereqs_dedup, related_dedup


def graph_lens_items(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    prerequisites, related = _collect_concept_context(rows)
    items = [{"kind": "missing", "label": value} for value in prerequisites[:5]]
    items.extend({"kind": "nearby", "label": value} for value in related[:5])
    return items


def render_graph_lens_panel(rows: list[dict[str, Any]]) -> None:
    items = graph_lens_items(rows)
    if not items:
        return
    st.markdown("### 🕸 Граф-линза")
    st.caption("Что граф видит рядом с собранными фрагментами: недостающие prerequisites и соседние темы.")
    missing = [item["label"] for item in items if item["kind"] == "missing"]
    nearby = [item["label"] for item in items if item["kind"] == "nearby"]
    if missing:
        st.markdown("**Стоит добавить/повторить:** " + ", ".join(missing))
    if nearby:
        st.markdown("**Рядом по графу:** " + ", ".join(nearby))


def render_deep_study_panel(rows: list[dict[str, Any]]) -> None:
    st.markdown("### 🧠 Промпт для глубокого изучения")
    topic = str(st.session_state.get("living_konspekt_title") or "Рабочий конспект")
    sections = [row_to_section(row) for row in rows]
    prerequisites, related_concepts = _collect_concept_context(rows)
    prompt_text = build_deep_study_prompt(
        topic=topic,
        sections=sections,
        prerequisites=prerequisites,
        related_concepts=related_concepts,
    )
    st.code(prompt_text, language="markdown")
    prompt_cols = st.columns(len(_EXTERNAL_LLM_TARGETS))
    for col, (label, url) in zip(prompt_cols, _EXTERNAL_LLM_TARGETS):
        with col:
            st.link_button(label, url, width="stretch")
