"""Deep-study prompt builder — copy-paste into an external LLM (ChatGPT/Claude/Gemini).

No API calls: the app stays local-first, the user copies :data:`DEEP_STUDY_PROMPT`
(filled in below) and pastes it into whichever cloud chat they prefer.
"""

from __future__ import annotations

from typing import Iterable

from app.prompts import DEEP_STUDY_PROMPT
from app.section_index import IndexedSection, ParsedSection, main_idea_section


def _quote_block(section: ParsedSection | IndexedSection) -> str:
    source_name = getattr(section, "konspekt_md_abs", None)
    location = f"{source_name.name}:{section.line_start}-{section.line_end}" if source_name else (
        f"строки {section.line_start}-{section.line_end}"
    )
    return f"### {section.heading_text} ({location})\n{section.text}"


def build_deep_study_prompt(
    *,
    topic: str,
    sections: list[ParsedSection] | list[IndexedSection],
    prerequisites: Iterable[str] | None = None,
    related_concepts: Iterable[str] | None = None,
) -> str:
    """Собрать копируемый промпт: главная мысль (через :func:`main_idea_section`,

    НЕ первый раздел) + дословные цитаты выбранных секций (с источником/строками) +
    prerequisites/related концепта.
    """
    main_idea = main_idea_section(sections) if sections else None
    main_idea_text = (
        main_idea.text.strip()
        if main_idea and main_idea.text.strip()
        else "(не найдено — рабочий конспект не содержит раздела «Главная мысль»)"
    )

    quotes = "\n\n".join(_quote_block(section) for section in sections) or "(разделы не выбраны)"

    prereqs_list = [str(p).strip() for p in (prerequisites or []) if str(p).strip()]
    related_list = [str(r).strip() for r in (related_concepts or []) if str(r).strip()]
    concept_lines = []
    if prereqs_list:
        concept_lines.append("Prerequisites: " + ", ".join(prereqs_list))
    if related_list:
        concept_lines.append("Связанные концепты: " + ", ".join(related_list))
    concept_context = "\n".join(concept_lines) or "(нет данных о концепте)"

    return DEEP_STUDY_PROMPT.format(
        topic=(topic or "").strip() or "Без темы",
        main_idea=main_idea_text,
        quotes=quotes,
        concept_context=concept_context,
    )
