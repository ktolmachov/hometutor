"""Learning plan state — markdown table parsing, step extraction, hours summary.

Dedicated home for learning-plan-specific state operations.
The prompt contract (LEARNING_PLAN_PROMPT in app/prompts/_impl.py) defines the canonical
8-column table:

  | # | Тема | Документ(ы) | Ключевые концепции | Практика | Проверка результата | Зависимости | Время (ч) |

The parser also handles shorter/simplified variants via column-alias matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# ──────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────


@dataclass(frozen=True)
class LearningPlanStep:
    """A single atomic step extracted from a learning-plan markdown table."""

    index: str
    title: str
    documents: str = ""
    key_concepts: str = ""
    practice: str = ""
    check: str = ""
    dependencies: str = ""
    hours: str = ""


# ──────────────────────────────────────────────
# Column alias registry
# ──────────────────────────────────────────────

_COLUMN_ALIASES: dict[str, str] = {
    "#": "index",
    "№": "index",
    "номер": "index",
    "шаг": "index",
    "тема": "title",
    "topic": "title",
    "документ": "documents",
    "документы": "documents",
    "document": "documents",
    "documents": "documents",
    "ключевые концепции": "key_concepts",
    "концепции": "key_concepts",
    "key concepts": "key_concepts",
    "практика": "practice",
    "упражнение": "practice",
    "действие": "practice",
    "practice": "practice",
    "проверка результата": "check",
    "самопроверка": "check",
    "критерий успеха": "check",
    "check": "check",
    "outcome check": "check",
    "зависимости": "dependencies",
    "prerequisites": "dependencies",
    "dependencies": "dependencies",
    "время ч": "hours",
    "время": "hours",
    "часы": "hours",
    "hours": "hours",
}


# ──────────────────────────────────────────────
# Low-level helpers
# ──────────────────────────────────────────────


def _normalize_header(value: str) -> str:
    normalized = re.sub(r"[*_`]", "", value or "").strip().lower().replace("ё", "е")
    normalized = re.sub(r"\([^)]*\)", "", normalized)
    normalized = re.sub(r"[^a-zа-я0-9#№]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _split_row(line: str) -> list[str]:
    raw = (line or "").strip()
    if "|" not in raw:
        return []
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    return [cell.strip() for cell in raw.split("|")]


def _is_separator(cells: list[str]) -> bool:
    if not cells:
        return False
    normalized = [cell.strip() for cell in cells if cell.strip()]
    return bool(normalized) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in normalized)


def _clean_cell(value: str) -> str:
    cleaned = re.sub(r"<br\s*/?>", "; ", value or "", flags=re.IGNORECASE)
    cleaned = re.sub(r"[*_`]", "", cleaned)
    cleaned = cleaned.replace("|", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _column_map(header_cells: list[str]) -> dict[int, str]:
    mapped: dict[int, str] = {}
    for idx, header in enumerate(header_cells):
        normalized = _normalize_header(header)
        key = _COLUMN_ALIASES.get(normalized)
        if key:
            mapped[idx] = key
    return mapped


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────


def parse_plan_table(plan_md: str) -> list[LearningPlanStep]:
    """Parse a markdown learning-plan table into a list of atomic steps.

    Scans lines for a header row followed by a separator row that maps
    to known column aliases.  Returns the first contiguous block of data
    rows found, or an empty list when no table is detected.

    Gracefully handles malformed tables — returns [] instead of crashing.
    """
    lines = (plan_md or "").splitlines()
    for i, line in enumerate(lines[:-1]):
        header_cells = _split_row(line)
        separator_cells = _split_row(lines[i + 1])
        col_map = _column_map(header_cells)
        if "title" not in col_map.values() or not _is_separator(separator_cells):
            continue

        steps: list[LearningPlanStep] = []
        for row_line in lines[i + 2 :]:
            row_cells = _split_row(row_line)
            if not row_cells:
                break
            if _is_separator(row_cells):
                continue
            values = {
                key: _clean_cell(row_cells[idx])
                for idx, key in col_map.items()
                if idx < len(row_cells)
            }
            title = values.get("title", "")
            if not title:
                continue
            steps.append(
                LearningPlanStep(
                    index=values.get("index", ""),
                    title=title,
                    documents=values.get("documents", ""),
                    key_concepts=values.get("key_concepts", ""),
                    practice=values.get("practice", ""),
                    check=values.get("check", ""),
                    dependencies=values.get("dependencies", ""),
                    hours=values.get("hours", ""),
                )
            )
        if steps:
            return steps
    return []


def step_to_text(step: LearningPlanStep) -> str:
    """Render a single plan step as clean text without any | characters."""
    parts = [step.title]
    if step.key_concepts:
        parts.append(f"Концепции: {step.key_concepts}")
    if step.practice:
        parts.append(f"Практика: {step.practice}")
    if step.check:
        parts.append(f"Проверка: {step.check}")
    if step.documents:
        parts.append(f"Документы: {step.documents}")
    if step.dependencies:
        parts.append(f"Зависимости: {step.dependencies}")
    if step.hours:
        parts.append(f"Время: {step.hours} ч")
    return ". ".join(parts)


def preview_card_text(step: LearningPlanStep) -> str:
    """Render a single step as a concise preview card (title + concepts + hours)."""
    parts = [step.title]
    if step.key_concepts:
        parts.append(step.key_concepts)
    elif step.documents:
        parts.append(step.documents)
    base = " — ".join(parts)
    if step.hours:
        return f"{base} (~{step.hours} ч)"
    return base


def preview_cards_from_plan_text(plan_md: str) -> list[str]:
    """Build concise preview cards from a learning-plan markdown table.

    Returns empty list when no table is detected (caller should fall back
    to a legacy heuristic).
    """
    steps = parse_plan_table(plan_md)
    if not steps:
        return []
    return [preview_card_text(step) for step in steps]


def _parse_hours(value: str) -> float | None:
    match = re.search(r"\d+(?:[.,]\d+)?", value or "")
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", "."))
    except ValueError:
        return None


def hours_summary_from_markdown(plan_md: str) -> dict[str, Any] | None:
    """Summarise hours from a plan table. Returns None when no table is detected."""
    table_steps = parse_plan_table(plan_md)
    if not table_steps:
        return None
    total = 0.0
    missing_or_invalid = 0
    for step in table_steps:
        hours = _parse_hours(step.hours)
        if hours is None:
            missing_or_invalid += 1
            continue
        total += hours
    return {
        "total_hours": round(total, 2),
        "steps_count": len(table_steps),
        "missing_or_invalid_hours": missing_or_invalid,
    }


def steps_from_markdown(plan_md: str) -> list[str]:
    """Extract human-readable step texts from a learning plan markdown.

    If a recognised markdown table is present, returns structured step
    texts (one per data row).  Otherwise falls back to legacy parsing:
    numbered-list chunks, then paragraph chunks.
    """
    raw = (plan_md or "").strip()
    if not raw:
        return []

    table_steps = parse_plan_table(raw)
    if table_steps:
        return [step_to_text(step) for step in table_steps[:40]]

    # --- legacy fallback: numbered list ---
    lines = raw.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    for line in lines:
        if re.match(r"^\s*\d+\.\s+", line) and current:
            chunks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("\n".join(current).strip())
    cleaned = [c for c in chunks if c]
    if len(cleaned) <= 1:
        paras = [p.strip() for p in raw.split("\n\n") if p.strip()]
        return paras[:20] if paras else ([raw] if raw else [])
    return cleaned[:40]
