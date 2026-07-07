"""Вкладка «Дальше» Живого конспекта: проверка актуальности и deep-study промпт.

Вынесено из ``living_konspekt_view`` (файл был в size-budget списке нарушителей):
web-ссылки лектора, поисковые запросы по разделам корзины и промпт для внешних LLM.
Всё локально; облако — только по явному клику пользователя по ссылке.
"""

from __future__ import annotations

from pathlib import Path
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


def video_semantic_moments(rows: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    """Смысловые блоки видео, пересекающиеся с разделами корзины.

    Узлы смыслов видео для граф-линзы: детерминированная сегментация лекции
    (``semantic_blocks`` sidecar-а) даёт границы тем и ключевые слова — линза
    показывает, о чём лектор говорит в окрестности собранных фрагментов,
    с точным таймкодом. Всё локально, без LLM.
    """
    from app.media_sidecar import load_media_sidecar_for_konspekt
    from app.ui.living_konspekt_media import _media_section_for_row

    moments: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    for row in rows:
        md_abs = str(row.get("konspekt_md_abs") or "")
        if not md_abs:
            continue
        try:
            sidecar = load_media_sidecar_for_konspekt(Path(md_abs))
        except Exception:  # noqa: BLE001 - линза опциональна, деградирует молча
            continue
        if sidecar is None or not sidecar.semantic_blocks:
            continue
        media_section = _media_section_for_row(sidecar, row)
        if media_section is None or media_section.t_start is None:
            continue
        t_lo = media_section.t_start
        t_hi = media_section.t_end if media_section.t_end is not None else t_lo + 60.0
        for block in sidecar.semantic_blocks:
            if block.t_end <= t_lo or block.t_start >= t_hi:
                continue
            key = (md_abs, block.t_start)
            if key in seen:
                continue
            seen.add(key)
            moments.append(
                {
                    "t_start": block.t_start,
                    "t_end": block.t_end,
                    "label": block.label or ", ".join(block.keywords[:3]),
                    "keywords": list(block.keywords),
                    "heading": str(row.get("heading_text") or ""),
                    "source": Path(md_abs).name,
                }
            )
            if len(moments) >= limit:
                return moments
    return moments


def _fmt_moment_ts(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def render_graph_lens_panel(rows: list[dict[str, Any]]) -> None:
    items = graph_lens_items(rows)
    moments = video_semantic_moments(rows)
    if not items and not moments:
        return
    st.markdown("### 🕸 Граф-линза")
    st.caption("Что граф видит рядом с собранными фрагментами: недостающие prerequisites, соседние темы и смыслы видео.")
    missing = [item["label"] for item in items if item["kind"] == "missing"]
    nearby = [item["label"] for item in items if item["kind"] == "nearby"]
    if missing:
        st.markdown("**Стоит добавить/повторить:** " + ", ".join(missing))
    if nearby:
        st.markdown("**Рядом по графу:** " + ", ".join(nearby))
    if moments:
        st.markdown("**🎬 Смыслы видео рядом с фрагментами:**")
        for moment in moments:
            label = moment["label"] or "тема без названия"
            st.markdown(
                f"- `{_fmt_moment_ts(moment['t_start'])}–{_fmt_moment_ts(moment['t_end'])}` "
                f"{label} · _{moment['heading'][:48]}_"
            )


def course_coverage_summary(rows: list[dict[str, Any]], active_scope: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(active_scope, dict) or not active_scope.get("active"):
        return None
    source_paths = [
        str(path).strip().replace("\\", "/")
        for path in active_scope.get("source_paths") or []
        if str(path).strip()
    ]
    if not source_paths:
        return None
    covered_sources = {_row_source_rel(row) for row in rows if isinstance(row, dict)}
    covered_sources.discard("")
    covered = [path for path in source_paths if path in covered_sources]
    missing = [path for path in source_paths if path not in covered_sources]
    return {
        "title": str(active_scope.get("title") or active_scope.get("folder_rel") or "Активный курс"),
        "covered": len(covered),
        "total": len(source_paths),
        "ratio": len(covered) / len(source_paths),
        "covered_paths": covered,
        "missing_paths": missing,
    }


def render_course_coverage_panel(rows: list[dict[str, Any]]) -> None:
    try:
        from app.ui.study_scope import get_active_scope

        summary = course_coverage_summary(rows, get_active_scope())
    except Exception:  # noqa: BLE001 - coverage map is optional and must degrade quietly
        summary = None
    if not summary:
        return
    pct = round(float(summary["ratio"]) * 100)
    st.markdown("### 🗺 Покрытие курса")
    st.caption(f"{summary['title']}: в сборке {summary['covered']} из {summary['total']} документов ({pct}%).")
    st.progress(float(summary["ratio"]))
    missing = list(summary.get("missing_paths") or [])
    if missing:
        labels = ", ".join(Path(path).name for path in missing[:5])
        suffix = "…" if len(missing) > 5 else ""
        st.caption(f"Ещё не представлены: {labels}{suffix}")
    else:
        st.success("Все документы активного курса представлены в текущем Живом конспекте.")


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


def _row_source_rel(row: dict[str, Any]) -> str:
    rel = str(row.get("source_rel") or "").strip().replace("\\", "/")
    if rel:
        return rel
    source_abs = str(row.get("source_abs") or "").strip()
    if not source_abs:
        return ""
    try:
        from app.path_safety import data_relative_from_path

        return data_relative_from_path(source_abs).replace("\\", "/")
    except ValueError:
        return ""
