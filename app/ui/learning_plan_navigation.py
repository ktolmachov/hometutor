"""Inline navigation for tabular learning plans."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app import user_state
from app.living_konspekt_source_resolver import SourceSectionCandidate
from app.living_konspekt_video_citations import video_citation_for_candidate
from app.obsidian_export import obsidian_uri, vscode_uri
from app.section_index import IndexedSection, best_section_for, build_section_index


def enriched_learning_plan_markdown(
    plan_md: str,
    *,
    learning_plan: dict[str, Any],
    topic_id: str | None = None,
) -> str:
    steps = user_state.learning_plan_table_steps_from_markdown(plan_md)
    if not steps:
        return plan_md

    current_step = _current_plan_step_index(topic_id)
    rows: list[list[str]] = []
    for idx, step in enumerate(steps):
        section = _best_section_for_step(step)
        rows.append(
            [
                _escape_cell(step.index or str(idx + 1)),
                _status_label(idx, current_step),
                _escape_cell(step.title),
                _escape_cell(step.documents),
                _escape_cell(step.key_concepts),
                _escape_cell(step.practice),
                _escape_cell(step.check),
                _materials_cell(section),
                _escape_cell(step.dependencies),
                _escape_cell(step.hours),
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


def _materials_cell(section: IndexedSection | None) -> str:
    if section is None:
        return "Подготовьте конспект для точных ссылок"
    bits = [
        f"[Obsidian]({obsidian_uri(Path(section.konspekt_md_abs), heading_text=section.heading_text)})",
        f"[VS Code]({vscode_uri(Path(section.konspekt_md_abs), line=int(section.line_start))})",
    ]
    citation = video_citation_for_candidate(
        SourceSectionCandidate(section=section, score=0.0, reason="learning plan row")
    )
    if citation.status == "available" and citation.citation is not None:
        c = citation.citation
        if c.url:
            bits.append(f"[Видео {c.timestamp_label}]({c.url})")
        else:
            bits.append(f"Видео {c.timestamp_label}: локальный файл")
    label = _escape_cell(section.heading_text)
    return f"{label}: " + " · ".join(bits)


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


__all__ = ["enriched_learning_plan_markdown"]
