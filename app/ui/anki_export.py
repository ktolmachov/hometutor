"""Экспорт конспекта synthesis в Anki TSV/APKG."""
from __future__ import annotations

from typing import Any

from app.export_utils import anki_apkg_from_pairs, anki_field_safe


def synthesis_sections_for_anki(synthesis: dict[str, Any], fallback_title: str) -> list[tuple[str, str]]:
    topic = str(synthesis.get("topic") or fallback_title or "Synthesis").strip()
    summary = str(synthesis.get("summary") or "").strip()
    if not summary:
        return []

    lines = summary.splitlines()
    sections: list[tuple[str, str]] = []
    cur_title = "Общий конспект"
    cur_lines: list[str] = []
    for line in lines:
        raw = line.strip()
        if raw.startswith("#"):
            if cur_lines:
                body = "\n".join(cur_lines).strip()
                if body:
                    sections.append((cur_title, body))
                cur_lines = []
            cur_title = raw.lstrip("#").strip() or "Раздел"
        else:
            cur_lines.append(line)
    if cur_lines:
        body = "\n".join(cur_lines).strip()
        if body:
            sections.append((cur_title, body))

    if not sections:
        paras = [p.strip() for p in summary.split("\n\n") if p.strip()]
        for i, para in enumerate(paras[:8], 1):
            sections.append((f"Ключевая мысль {i}", para))

    pairs: list[tuple[str, str]] = []
    for title, body in sections[:12]:
        pairs.append((f"{topic}: {title}", body[:1600]))

    sources = synthesis.get("sources") or []
    if isinstance(sources, list):
        for src in sources[:8]:
            if not isinstance(src, dict):
                continue
            path = str(src.get("relative_path") or src.get("file_name") or "").strip()
            if not path:
                continue
            score = src.get("score")
            page = src.get("page")
            meta: list[str] = []
            if page is not None:
                meta.append(f"page={page}")
            if score is not None:
                meta.append(f"score={score}")
            back = "Источник для повторения"
            if meta:
                back += f" ({', '.join(meta)})"
            pairs.append((f"{topic}: источник {path}", back))
    return pairs


def anki_tsv_from_pairs(pairs: list[tuple[str, str]]) -> str:
    lines = ["front\tback"]
    for front, back in pairs:
        f = anki_field_safe(front)
        b = anki_field_safe(back)
        if f and b:
            lines.append(f"{f}\t{b}")
    return "\n".join(lines)
