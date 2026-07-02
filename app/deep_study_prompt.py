"""Deep-study prompt builder — copy-paste into an external LLM (ChatGPT/Claude/Gemini).

No API calls: the app stays local-first, the user copies :data:`DEEP_STUDY_PROMPT`
(filled in below) and pastes it into whichever cloud chat they prefer.

«Дух лекции»: помимо выбранных секций билдер подтягивает из ПОЛНЫХ конспектов их
документов разделы-роли (главная мысль, риски/антипаттерны, контрольные вопросы) —
см. ``section_role``. Роли опциональны: локальный шаблон конспекта гарантирует не все
из них, отсутствие честно помечается «(в конспекте нет)».
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from app.prompts import DEEP_STUDY_PROMPT
from app.section_index import (
    IndexedSection,
    ParsedSection,
    main_idea_section,
    section_role,
    sections_by_role,
    _cached_parse_sections,
)

_NO_ROLE_PLACEHOLDER = "(в конспекте нет)"
_ROLE_KEYS = ("main_idea", "pitfalls", "check_questions")


def _quote_block(section: ParsedSection | IndexedSection) -> str:
    source_name = getattr(section, "konspekt_md_abs", None)
    location = f"{source_name.name}:{section.line_start}-{section.line_end}" if source_name else (
        f"строки {section.line_start}-{section.line_end}"
    )
    return f"### {section.heading_text} ({location})\n{section.text}"


def _doc_role_texts(
    sections: list[ParsedSection] | list[IndexedSection],
) -> dict[str, list[str]]:
    """Тексты разделов-ролей из полных конспектов документов выбранных секций.

    Только ``IndexedSection`` несёт провенанс (``konspekt_md_abs``); голые
    ``ParsedSection`` пропускаем — без пути к файлу роли взять неоткуда.
    """
    md_paths: list[Path] = []
    for section in sections:
        md = getattr(section, "konspekt_md_abs", None)
        if isinstance(md, Path) and md not in md_paths:
            md_paths.append(md)

    out: dict[str, list[str]] = {role: [] for role in _ROLE_KEYS}
    for md in md_paths:
        try:
            parsed = _cached_parse_sections(md)
        except OSError:
            continue
        roles = sections_by_role(parsed)
        for role in _ROLE_KEYS:
            role_section = roles.get(role)
            if role_section is not None and role_section.text.strip():
                out[role].append(role_section.text.strip())
    return out


def _resolve_main_idea_text(
    sections: list[ParsedSection] | list[IndexedSection],
    doc_main_ideas: list[str],
) -> str:
    """Главная мысль: роль среди выбранных → роль из полного конспекта → эвристика.

    Эвристика ``main_idea_section`` («первая содержательная H2 среди выбранных») —
    последний фолбэк: она возвращает хоть что-то, но это не мысль лектора.
    """
    selected = main_idea_section(sections) if sections else None
    if selected is not None and section_role(selected) == "main_idea" and selected.text.strip():
        return selected.text.strip()
    if doc_main_ideas:
        return "\n\n".join(doc_main_ideas)
    if selected is not None and selected.text.strip():
        return selected.text.strip()
    return "(не найдено — рабочий конспект не содержит раздела «Главная мысль»)"


def build_deep_study_prompt(
    *,
    topic: str,
    sections: list[ParsedSection] | list[IndexedSection],
    prerequisites: Iterable[str] | None = None,
    related_concepts: Iterable[str] | None = None,
) -> str:
    """Собрать копируемый промпт: главная мысль (роль, не «первый раздел») + дословные
    цитаты выбранных секций (с источником/строками) + prerequisites/related концепта +
    риски/антипаттерны и контрольные вопросы из полных конспектов документов.
    """
    role_texts = _doc_role_texts(sections) if sections else {role: [] for role in _ROLE_KEYS}
    main_idea_text = _resolve_main_idea_text(sections, role_texts["main_idea"])

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
        pitfalls="\n\n".join(role_texts["pitfalls"]) or _NO_ROLE_PLACEHOLDER,
        check_questions="\n\n".join(role_texts["check_questions"]) or _NO_ROLE_PLACEHOLDER,
    )
