"""Scoped quiz adapter for Living Konspekt workbench rows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.quiz_parse import _MAX_CONTEXT_CHARS
from app.quiz_scoped import generate_scoped_quiz_from_content

_MAX_ROW_CHARS = 1800


def build_living_konspekt_quiz_context(rows: list[dict[str, Any]]) -> str:
    """Build bounded quiz context strictly from selected workbench row texts."""
    blocks: list[str] = []
    remaining = _MAX_CONTEXT_CHARS
    for idx, row in enumerate(rows, start=1):
        text = str(row.get("own_text") or row.get("text") or "").strip()
        if not text:
            continue
        heading = str(row.get("heading_text") or f"Фрагмент {idx}").strip()
        source = _row_source_ref(row)
        body = text[:_MAX_ROW_CHARS].strip()
        block = f"[{idx}] {heading}\nИсточник: {source}\n{body}"
        if len(block) + 2 > remaining:
            if remaining < 240:
                break
            block = block[:remaining].rstrip()
        blocks.append(block)
        remaining -= len(block) + 2
        if remaining <= 0:
            break
    return "\n\n".join(blocks)


def generate_living_konspekt_quiz(
    rows: list[dict[str, Any]],
    *,
    title: str,
    goal: dict[str, Any] | None = None,
    num_questions: int = 6,
    difficulty: str = "adaptive",
    learning_mode: str | None = None,
) -> dict[str, Any]:
    """Generate a quiz from current workbench rows without document/topic retrieval."""
    context = build_living_konspekt_quiz_context(rows)
    goal_text = str((goal or {}).get("text") or "").strip()
    title_norm = (title or "Живой конспект").strip() or "Живой конспект"
    extra = "—"
    if goal_text:
        extra = f"Цель конспекта: {goal_text}"
    payload = generate_scoped_quiz_from_content(
        scope="living_konspekt",
        identifier=title_norm,
        title=title_norm,
        content=context,
        subgraph={
            "topic_name": title_norm,
            "key_concepts": _concepts_from_rows(rows),
            "documents": _source_refs_from_rows(rows),
        },
        adaptive_level=_adaptive_level_from_difficulty(difficulty),
        num_questions=num_questions,
        learning_mode=learning_mode,
        extra_context=extra,
    )
    if payload.get("success"):
        payload["scope"] = "living_konspekt"
        payload["identifier"] = title_norm
        payload["source_count"] = len([row for row in rows if isinstance(row, dict)])
    return payload


def _adaptive_level_from_difficulty(difficulty: str) -> str:
    raw = (difficulty or "adaptive").strip().lower()
    if raw in {"recognition", "recall", "transfer"}:
        return raw
    return "recall"


def _row_source_ref(row: dict[str, Any]) -> str:
    label = str(row.get("konspekt_md_label") or "").strip()
    md_abs = str(row.get("konspekt_md_abs") or "").strip()
    if md_abs:
        label = Path(md_abs).name
    if not label:
        label = str(row.get("source_label") or "неизвестный конспект").strip()
    start = row.get("line_start")
    end = row.get("line_end")
    if start and end:
        return f"{label}:{start}-{end}"
    if start:
        return f"{label}:{start}"
    return label


def _source_refs_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(_row_source_ref(row) for row in rows if isinstance(row, dict)))


def _concepts_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    values = [str(row.get("concept") or "").strip() for row in rows if isinstance(row, dict)]
    return list(dict.fromkeys(value for value in values if value))


__all__ = [
    "build_living_konspekt_quiz_context",
    "generate_living_konspekt_quiz",
]
