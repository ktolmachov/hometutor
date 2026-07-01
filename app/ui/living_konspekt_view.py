"""«Живой конспект» — study-поверхность над Section Anchor Index.

Корзина (:data:`WORKBENCH_SECTIONS_KEY`) живёт в ``st.session_state`` — переживает
rerun'ы, но не полный рестарт/закрытие вкладки в v1 (см. план, Компонент 3).
Кросс-рестарт-восстановление — только через ручной snapshot существующих
именованных research-сессий (``save_research_session``/``apply_research_payload``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, MutableMapping

import re

import streamlit as st

from app.deep_study_prompt import build_deep_study_prompt
from app.section_index import IndexedSection, row_to_section, section_to_row
from app.study_web_queries import build_query_terms, build_web_search_links
from app.ui.helpers import format_request_error
from app.ui.widgets import render_panel_header

WORKBENCH_SECTIONS_KEY = "workbench_sections"

_SLUG_RE = re.compile(r"[^\w\-]+", re.UNICODE)


# ── Корзина (JSON-safe rows из app.section_index) ───────────────────────
# ``state`` — опциональный DI-параметр (по умолчанию ``st.session_state``): позволяет
# юнит-тестировать add/dedup/remove на обычном dict без запуска Streamlit runtime.
def _state(state: MutableMapping[str, Any] | None) -> MutableMapping[str, Any]:
    return state if state is not None else st.session_state


def get_workbench_rows(state: MutableMapping[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = _state(state).get(WORKBENCH_SECTIONS_KEY)
    return rows if isinstance(rows, list) else []


def add_section_to_workbench(
    section: IndexedSection,
    state: MutableMapping[str, Any] | None = None,
) -> bool:
    """Добавить раздел в корзину; дедуп по ``(konspekt_md_abs, line_start)``.

    Возвращает ``True``, если раздел был новым (добавлен), ``False`` — если уже был в корзине.
    """
    target = _state(state)
    rows = get_workbench_rows(target)
    dedup_key = (str(section.konspekt_md_abs), section.line_start)
    for row in rows:
        if (str(row.get("konspekt_md_abs") or ""), row.get("line_start")) == dedup_key:
            return False
    rows.append(section_to_row(section))
    target[WORKBENCH_SECTIONS_KEY] = rows
    return True


def remove_section_from_workbench(
    konspekt_md_abs: str,
    line_start: int,
    state: MutableMapping[str, Any] | None = None,
) -> None:
    target = _state(state)
    rows = get_workbench_rows(target)
    target[WORKBENCH_SECTIONS_KEY] = [
        row
        for row in rows
        if not (
            str(row.get("konspekt_md_abs") or "") == konspekt_md_abs
            and row.get("line_start") == line_start
        )
    ]


# ── Сборка рабочего конспекта ────────────────────────────────────────────
def _stitch_verbatim(rows: list[dict[str, Any]]) -> str:
    """0-LLM склейка: заголовки-источники + якоря + дословный текст разделов."""
    parts: list[str] = []
    for row in rows:
        heading = str(row.get("heading_text") or "Без названия")
        source_name = Path(str(row.get("konspekt_md_abs") or "")).name
        location = f"{source_name}:{row.get('line_start')}"
        parts.append(f"## {heading}\n\n*Источник: {location}*\n\n{row.get('text') or ''}")
    return "\n\n---\n\n".join(parts)


def _filename_slug(title: str) -> str:
    s = title.strip().lower()
    s = _SLUG_RE.sub("-", s).strip("-")
    return s or "konspekt"


def _unique_target_path(base_dir: Path, slug: str) -> Path:
    candidate = base_dir / f"{slug}.md"
    counter = 1
    while candidate.exists():
        candidate = base_dir / f"{slug}-{counter}.md"
        counter += 1
    return candidate


def _save_living_konspekt(title: str, body_markdown: str) -> Path:
    """Сохранить в ``vault_root()/"living-konspekt"/<slug>.md`` — НЕ ``vault_target()``.

    ``vault_target()`` требует ``source_abs`` и зеркалит путь исходника; у рабочего
    конспекта нет единого исходника (это сборка из нескольких документов).
    """
    from app.obsidian_export import vault_root

    target_dir = vault_root() / "living-konspekt"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = _unique_target_path(target_dir, _filename_slug(title))
    target_path.write_text(f"# {title}\n\n{body_markdown}\n", encoding="utf-8")
    return target_path


# ── UI ────────────────────────────────────────────────────────────────────
def _render_collected_sections(rows: list[dict[str, Any]]) -> None:
    from app.obsidian_export import obsidian_uri, vscode_uri

    st.markdown("### Собранные разделы")
    for row in list(rows):
        md_abs = str(row.get("konspekt_md_abs") or "")
        line_start = row.get("line_start")
        with st.container(border=True):
            cols = st.columns([5, 1, 1])
            with cols[0]:
                st.markdown(f"**{row.get('heading_text') or '—'}**")
                st.caption(f"{Path(md_abs).name} · строки {line_start}-{row.get('line_end')}")
                st.write(str(row.get("text") or "")[:400])
            with cols[1]:
                if md_abs:
                    st.link_button(
                        "📄 Открыть",
                        obsidian_uri(Path(md_abs), heading_text=str(row.get("heading_text") or "")),
                        width="stretch",
                        key=f"wb_open_{md_abs}_{line_start}",
                    )
                    st.caption(vscode_uri(Path(md_abs), line=int(line_start) if line_start else None))
            with cols[2]:
                if st.button("🗑 Убрать", key=f"wb_remove_{md_abs}_{line_start}", width="stretch"):
                    remove_section_from_workbench(md_abs, int(line_start) if line_start else 0)
                    st.rerun()


def _render_build_panel(rows: list[dict[str, Any]]) -> None:
    st.markdown("### 📚 Собрать рабочий конспект")
    topic = st.text_input(
        "Название конспекта",
        value=st.session_state.get("living_konspekt_title") or "Рабочий конспект",
        key="living_konspekt_title",
    )
    mode = st.radio(
        "Способ сборки",
        ["Дословная сшивка (без LLM)", "LLM-синтез из разделов"],
        key="living_konspekt_mode",
        horizontal=True,
    )
    if st.button("Собрать и сохранить", key="living_konspekt_build", type="primary"):
        try:
            if mode.startswith("Дословная"):
                body = _stitch_verbatim(rows)
            else:
                from app.knowledge_synthesis import synthesize_sections  # heavy: LLM/Chroma services

                sections = [row_to_section(row) for row in rows]
                result = synthesize_sections(topic=topic, sections=sections)
                body = str(result["summary"])
            target_path = _save_living_konspekt(topic, body)
        except Exception as exc:  # noqa: BLE001 - показать пользователю причину сбора/сохранения
            st.error(f"Не удалось собрать конспект: {format_request_error(exc)}")
        else:
            st.success("✅ Сохранено в vault. Войдёт в поиск и граф после обновления индекса.")
            st.caption(f"Файл: `{target_path}`")


def _render_web_queries_panel(rows: list[dict[str, Any]]) -> None:
    st.markdown("### 🌐 Проверить актуальность · источники")
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


_EXTERNAL_LLM_TARGETS = (
    ("ChatGPT", "https://chatgpt.com/"),
    ("Claude", "https://claude.ai/new"),
    ("Gemini", "https://gemini.google.com/app"),
)


def _collect_concept_context(rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Prerequisites/related_concepts для всех уникальных концептов, привязанных к разделам корзины.

    Раздел получает ``concept`` только когда его добавили из графа
    (``_render_document_section_workbench_button`` в ``dashboards_graph.py``); разделы из
    Flashcards приходят без концепта — тогда контекст пуст, и это ожидаемо (нет графового
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


def _render_deep_study_panel(rows: list[dict[str, Any]]) -> None:
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


def render_living_konspekt_view() -> None:
    render_panel_header(
        "📚 Живой конспект",
        "Собирайте разделы лекций из графа/карточек, проверяйте актуальность и готовьте промпт "
        "для глубокого изучения — всё локально, облако только по вашей ссылке.",
    )

    rows = get_workbench_rows()
    st.caption(f"В корзине: {len(rows)} раздел(ов)")

    if not rows:
        st.info(
            "Корзина пуста. Добавляйте разделы из панели «⚡ Действия с концептом» на Knowledge Graph "
            "или кнопкой «➕ В рабочий конспект» под карточкой Flashcards."
        )
        return

    _render_collected_sections(rows)
    st.divider()
    _render_build_panel(rows)
    st.divider()
    _render_web_queries_panel(rows)
    st.divider()
    _render_deep_study_panel(rows)
