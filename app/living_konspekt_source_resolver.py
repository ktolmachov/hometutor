"""Resolve retrieval source chunks into Living Konspekt sections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.knowledge_text import tokenize_filtered
from app.section_index import IndexedSection, _ranked_by_overlap, _ranking_candidates, build_section_index

MIN_AUTO_SCORE = 3.0
AMBIGUITY_MARGIN = 1.0
MAX_CANDIDATES = 3


@dataclass(frozen=True)
class SourceSectionCandidate:
    section: IndexedSection
    score: float
    reason: str


@dataclass(frozen=True)
class SourceSectionResolution:
    status: str  # "single" | "choose" | "unavailable"
    candidates: tuple[SourceSectionCandidate, ...]
    message: str

    @property
    def single(self) -> SourceSectionCandidate | None:
        return self.candidates[0] if self.status == "single" and self.candidates else None


def resolve_source_section(
    source: dict[str, Any],
    *,
    min_auto_score: float = MIN_AUTO_SCORE,
    ambiguity_margin: float = AMBIGUITY_MARGIN,
    max_candidates: int = MAX_CANDIDATES,
) -> SourceSectionResolution:
    """Resolve a retrieval source card to one or more candidate konspekt sections."""
    rel = str(source.get("relative_path") or source.get("file_name") or "").strip()
    if not rel:
        return SourceSectionResolution("unavailable", (), "У источника нет относительного пути.")

    sections = build_section_index(rel)
    if not sections:
        return SourceSectionResolution(
            "unavailable",
            (),
            "Для источника нет подготовленного markdown-конспекта.",
        )

    query_text = _source_query_text(source)
    candidates = _rank_candidates(sections, query_text, source)[:max(1, max_candidates)]
    if not candidates:
        return SourceSectionResolution(
            "choose",
            tuple(_line_or_first_candidates(sections, source, max_candidates=max_candidates)),
            "Не удалось уверенно сопоставить фрагмент с разделом — выберите вручную.",
        )

    top = candidates[0]
    if _is_ambiguous(candidates, sections, min_auto_score=min_auto_score, ambiguity_margin=ambiguity_margin):
        return SourceSectionResolution(
            "choose",
            tuple(candidates),
            "Есть несколько похожих разделов или низкая уверенность — выберите нужный.",
        )
    return SourceSectionResolution("single", (top,), "Фрагмент сопоставлен с разделом.")


def _source_query_text(source: dict[str, Any]) -> str:
    parts = [
        str(source.get("text") or ""),
        str(source.get("title") or ""),
        str(source.get("file_name") or ""),
        str(source.get("relative_path") or ""),
    ]
    return "\n".join(part for part in parts if part.strip())


def _rank_candidates(
    sections: list[IndexedSection],
    query_text: str,
    source: dict[str, Any],
) -> list[SourceSectionCandidate]:
    query_tokens = tokenize_filtered(query_text)
    ranked = _ranked_by_overlap(_ranking_candidates(sections), query_tokens) if query_tokens else []
    out: list[SourceSectionCandidate] = []
    for section, score in ranked:
        if not isinstance(section, IndexedSection):
            continue
        boost = 4.0 if _source_lines_overlap_section(source, section) else 0.0
        reason = "строки источника попадают в раздел" if boost else "лексическое совпадение"
        out.append(SourceSectionCandidate(section=section, score=float(score) + boost, reason=reason))
    out.sort(key=lambda item: (-item.score, -item.section.level, item.section.line_start))
    return _dedup_candidates(out)


def _line_or_first_candidates(
    sections: list[IndexedSection],
    source: dict[str, Any],
    *,
    max_candidates: int,
) -> list[SourceSectionCandidate]:
    line_matches = [
        SourceSectionCandidate(section=section, score=4.0, reason="строки источника попадают в раздел")
        for section in sections
        if _source_lines_overlap_section(source, section)
    ]
    if line_matches:
        return _dedup_candidates(line_matches)[:max_candidates]
    fallback_sections = [section for section in _ranking_candidates(sections) if isinstance(section, IndexedSection)]
    return [
        SourceSectionCandidate(section=section, score=0.0, reason="ручной выбор")
        for section in fallback_sections[:max_candidates]
    ]


def _source_lines_overlap_section(source: dict[str, Any], section: IndexedSection) -> bool:
    try:
        src_start = int(source.get("line_start") or 0)
        src_end = int(source.get("line_end") or src_start or 0)
    except (TypeError, ValueError):
        return False
    if src_start <= 0:
        return False
    return int(section.line_start) <= src_end and src_start <= int(section.line_end)


def _is_ambiguous(
    candidates: list[SourceSectionCandidate],
    sections: list[IndexedSection],
    *,
    min_auto_score: float,
    ambiguity_margin: float,
) -> bool:
    if not candidates:
        return True
    top = candidates[0]
    if top.score < min_auto_score:
        return True
    if len(candidates) > 1 and candidates[1].score >= top.score - ambiguity_margin:
        return True
    heading = top.section.heading_text
    return sum(1 for section in sections if section.heading_text == heading) > 1


def _dedup_candidates(candidates: list[SourceSectionCandidate]) -> list[SourceSectionCandidate]:
    seen: set[tuple[str, int]] = set()
    out: list[SourceSectionCandidate] = []
    for candidate in candidates:
        key = (str(candidate.section.konspekt_md_abs), int(candidate.section.line_start))
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


__all__ = [
    "SourceSectionCandidate",
    "SourceSectionResolution",
    "resolve_source_section",
]
