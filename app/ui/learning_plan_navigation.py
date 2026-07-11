"""Inline navigation for tabular learning plans."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import streamlit as st

from app import user_state
from app.living_konspekt_source_resolver import SourceSectionCandidate
from app.living_konspekt_video_citations import video_citation_for_candidate
from app.obsidian_export import obsidian_uri, resolve_source, vscode_uri
from app.section_index import IndexedSection, best_section_for, build_section_index


def render_learning_plan_table(
    plan_md: str,
    *,
    learning_plan: dict[str, Any],
    topic_id: str | None = None,
    key_prefix: str = "learning_plan_nav",
) -> bool:
    rows = learning_plan_display_rows(plan_md, topic_id=topic_id)
    if not rows:
        return False

    st.caption("Статус: ✓ пройдено · ▶ текущий шаг · □ впереди. Материалы открываются прямо из строки.")
    for row in rows:
        with st.container(border=True):
            top = st.columns([0.5, 3.0, 1.2, 1.0])
            with top[0]:
                st.markdown(f"**{row['index']}**")
                st.caption(str(row["status"]))
            with top[1]:
                st.markdown(f"**{row['title']}**")
                if row.get("documents"):
                    st.caption(str(row["documents"]))
            with top[2]:
                st.caption(f"Зависимости: {row.get('dependencies') or '—'}")
            with top[3]:
                st.caption(f"~{row.get('hours') or '—'} ч")

            detail = st.columns([1.2, 1.2, 1.1])
            with detail[0]:
                st.caption("Ключевые концепции")
                st.write(row.get("key_concepts") or "—")
            with detail[1]:
                st.caption("Практика")
                st.write(row.get("practice") or "—")
            with detail[2]:
                st.caption("Проверка результата")
                st.write(row.get("check") or "—")

            links = row.get("links") if isinstance(row.get("links"), dict) else {}
            link_cols = st.columns(4)
            with link_cols[0]:
                if links.get("obsidian"):
                    st.link_button("Obsidian", str(links["obsidian"]), width="stretch")
                else:
                    st.caption(row.get("materials_note") or "Нет точного раздела")
            with link_cols[1]:
                if links.get("vscode"):
                    st.link_button("VS Code", str(links["vscode"]), width="stretch")
                elif links.get("vscode_doc"):
                    st.link_button("Документ", str(links["vscode_doc"]), width="stretch")
            with link_cols[2]:
                if links.get("video_url"):
                    st.link_button(f"Видео {links.get('video_label')}", str(links["video_url"]), width="stretch")
                elif links.get("video_label"):
                    st.caption(f"Видео {links['video_label']}: локальный файл")
            with link_cols[3]:
                if st.button("Сделать текущим", key=f"{key_prefix}_mark_{row['zero_index']}", width="stretch"):
                    _save_current_step_from_row(row, learning_plan=learning_plan, topic_id=topic_id)
                    st.rerun()
    return True


def enriched_learning_plan_markdown(
    plan_md: str,
    *,
    learning_plan: dict[str, Any],
    topic_id: str | None = None,
) -> str:
    steps = user_state.learning_plan_table_steps_from_markdown(plan_md)
    if not steps:
        return plan_md

    display_rows = learning_plan_display_rows(plan_md, topic_id=topic_id)
    rows: list[list[str]] = []
    for row in display_rows:
        links = row.get("links") if isinstance(row.get("links"), dict) else {}
        rows.append(
            [
                _escape_cell(str(row["index"])),
                _escape_cell(str(row["status"])),
                _escape_cell(str(row["title"])),
                _escape_cell(str(row.get("documents") or "")),
                _escape_cell(str(row.get("key_concepts") or "")),
                _escape_cell(str(row.get("practice") or "")),
                _escape_cell(str(row.get("check") or "")),
                _materials_cell_from_row(row, links),
                _escape_cell(str(row.get("dependencies") or "")),
                _escape_cell(str(row.get("hours") or "")),
            ]
        )

    table = _markdown_table(
        [
            "#",
            "Статус",
            "Тема",
            "Документ(ы)",
            "Ключевые концепции",
            "Практика",
            "Проверка результата",
            "Материалы",
            "Зависимости",
            "Время (ч)",
        ],
        rows,
    )
    return _replace_learning_plan_table(plan_md, table)


def learning_plan_display_rows(plan_md: str, *, topic_id: str | None = None) -> list[dict[str, Any]]:
    steps = user_state.learning_plan_table_steps_from_markdown(plan_md)
    if not steps:
        return []
    current_step = _current_plan_step_index(topic_id)
    rows: list[dict[str, Any]] = []
    for idx, step in enumerate(steps):
        section = _best_section_for_step(step)
        fallback_doc = _first_existing_source_path(step.documents)
        links = _links_for_section(section, fallback_doc=fallback_doc)
        rows.append(
            {
                "zero_index": idx,
                "index": step.index or str(idx + 1),
                "status": _status_label(idx, current_step),
                "title": step.title,
                "documents": step.documents,
                "key_concepts": step.key_concepts,
                "practice": step.practice,
                "check": step.check,
                "dependencies": step.dependencies,
                "hours": step.hours,
                "section": section,
                "links": links,
                "materials_note": "Откройте документ; подготовьте конспект для точного раздела",
            }
        )
    return rows


def _current_plan_step_index(topic_id: str | None) -> int | None:
    if not topic_id:
        return None
    try:
        status = user_state.get_reading_status(
            "learning_plan",
            user_state.learning_plan_resource_id(topic_id),
        )
    except Exception:  # noqa: BLE001 - navigation badges must not block plan rendering
        return None
    if not status or status.get("step_index") is None:
        return None
    try:
        return max(0, int(status["step_index"]))
    except (TypeError, ValueError):
        return None


def _status_label(index: int, current_step: int | None) -> str:
    if current_step is None:
        return "□"
    if index < current_step:
        return "✓"
    if index == current_step:
        return "▶"
    return "□"


def _best_section_for_step(step: user_state.LearningPlanMarkdownStep) -> IndexedSection | None:
    docs = _document_paths_from_cell(step.documents)
    query = "\n".join(
        part
        for part in (step.title, step.key_concepts, step.practice, step.check)
        if str(part or "").strip()
    )
    for rel in docs:
        try:
            sections = build_section_index(rel)
        except Exception:  # noqa: BLE001 - missing/bad document degrades to no inline links
            sections = []
        match = best_section_for(sections, query)
        if isinstance(match, IndexedSection):
            return match
    return None


def _document_paths_from_cell(cell: str) -> list[str]:
    text = str(cell or "")
    bracketed = re.findall(r"\[([^\]]+)\]", text)
    candidates = bracketed or re.split(r"[,;]", text)
    out: list[str] = []
    for raw in candidates:
        value = raw.strip().strip("`").strip()
        if not value:
            continue
        if value not in out:
            out.append(value)
    return out


def _materials_cell_from_row(row: dict[str, Any], links: dict[str, Any]) -> str:
    section = row.get("section")
    if not isinstance(section, IndexedSection):
        if links.get("vscode_doc"):
            return f"[Документ]({links['vscode_doc']}) · подготовьте конспект для точного раздела"
        return str(row.get("materials_note") or "Нет точного раздела")
    bits = []
    if links.get("obsidian"):
        bits.append(f"[Obsidian]({links['obsidian']})")
    if links.get("vscode"):
        bits.append(f"[VS Code]({links['vscode']})")
    if links.get("video_url"):
        bits.append(f"[Видео {links.get('video_label')}]({links['video_url']})")
    elif links.get("video_label"):
        bits.append(f"Видео {links['video_label']}: локальный файл")
    return f"{_escape_cell(section.heading_text)}: " + " · ".join(bits)


def _links_for_section(section: IndexedSection | None, *, fallback_doc: Path | None = None) -> dict[str, Any]:
    if section is None:
        return {"vscode_doc": vscode_uri(fallback_doc)} if fallback_doc is not None else {}
    links: dict[str, Any] = {
        "obsidian": obsidian_uri(Path(section.konspekt_md_abs), heading_text=section.heading_text),
        "vscode": vscode_uri(Path(section.konspekt_md_abs), line=int(section.line_start)),
    }
    citation = video_citation_for_candidate(
        SourceSectionCandidate(section=section, score=0.0, reason="learning plan row")
    )
    if citation.status == "available" and citation.citation is not None:
        links["video_label"] = citation.citation.timestamp_label
        if citation.citation.url:
            links["video_url"] = citation.citation.url
    return links


def _save_current_step_from_row(
    row: dict[str, Any],
    *,
    learning_plan: dict[str, Any],
    topic_id: str | None,
) -> None:
    if not topic_id:
        return
    steps_count = max(1, len(user_state.learning_plan_table_steps_from_markdown(str(learning_plan.get("plan") or ""))))
    idx = int(row.get("zero_index") or 0)
    label = str(row.get("title") or "")
    user_state.upsert_reading_status(
        resource_type="learning_plan",
        resource_id=user_state.learning_plan_resource_id(topic_id),
        step_index=idx,
        step_label=label[:500],
        progress=(idx + 1) / float(steps_count),
        display_title=f"План по теме «{learning_plan.get('topic') or topic_id}»",
    )


def _first_existing_source_path(documents_cell: str) -> Path | None:
    for rel in _document_paths_from_cell(documents_cell):
        try:
            resolved = resolve_source(rel)
        except Exception:  # noqa: BLE001 - bad source path degrades to no fallback link
            resolved = None
        if resolved is not None:
            return resolved
    return None


def _replace_learning_plan_table(plan_md: str, table_md: str) -> str:
    lines = (plan_md or "").splitlines()
    for idx, line in enumerate(lines[:-1]):
        if "|" not in line:
            continue
        next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
        if "|" not in next_line or "---" not in next_line:
            continue
        end = idx + 2
        while end < len(lines) and "|" in lines[end]:
            end += 1
        return "\n".join([*lines[:idx], table_md, *lines[end:]])
    return plan_md


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    out.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(out)


def _escape_cell(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "; ", str(value or ""), flags=re.IGNORECASE)
    text = text.replace("\n", " ")
    text = text.replace("|", "\\|")
    return re.sub(r"\s+", " ", text).strip()


__all__ = [
    "enriched_learning_plan_markdown",
    "learning_plan_display_rows",
    "render_learning_plan_table",
]
