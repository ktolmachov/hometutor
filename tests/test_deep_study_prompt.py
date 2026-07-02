"""Tests for app.deep_study_prompt (copy-paste prompt builder, no LLM calls)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.deep_study_prompt import build_deep_study_prompt
from app.section_index import IndexedSection, ParsedSection, parse_sections

TOC = ParsedSection(
    heading_text="📑 Оглавление",
    slug="oglavlenie",
    level=2,
    line_start=5,
    line_end=8,
    text="- [Главная мысль](#главная-мысль)",
)
MAIN_IDEA = ParsedSection(
    heading_text="🎯 Главная мысль",
    slug="glavnaya-mysl",
    level=2,
    line_start=10,
    line_end=13,
    text="Суть лекции про агентов ИИ и их инструменты.",
)
TOPIC_SECTION = ParsedSection(
    heading_text="🔹 Тема первая",
    slug="tema-pervaya",
    level=3,
    line_start=20,
    line_end=25,
    text="Подробности про инструменты агентов.",
)


class TestBuildDeepStudyPrompt:
    def test_main_idea_uses_dedicated_section_not_first_in_list(self):
        # TOC is first in the list — a naive "первый раздел" implementation would
        # surface TOC content as the main idea instead of the real H2.
        prompt = build_deep_study_prompt(topic="Агенты ИИ", sections=[TOC, MAIN_IDEA])
        assert "Суть лекции про агентов ИИ и их инструменты." in prompt
        assert "[Главная мысль](#главная-мысль)" not in prompt.split("## Дословные цитаты", 1)[0]

    def test_quotes_are_verbatim_with_heading_and_lines(self):
        prompt = build_deep_study_prompt(topic="Агенты ИИ", sections=[MAIN_IDEA, TOPIC_SECTION])
        assert "Подробности про инструменты агентов." in prompt
        assert "🔹 Тема первая" in prompt
        assert "20-25" in prompt

    def test_concept_context_includes_prerequisites_and_related(self):
        prompt = build_deep_study_prompt(
            topic="Агенты ИИ",
            sections=[MAIN_IDEA],
            prerequisites=["LLM основы"],
            related_concepts=["RAG"],
        )
        assert "Prerequisites: LLM основы" in prompt
        assert "Связанные концепты: RAG" in prompt

    def test_concept_context_fallback_when_no_concept_data(self):
        prompt = build_deep_study_prompt(topic="Агенты ИИ", sections=[MAIN_IDEA])
        assert "(нет данных о концепте)" in prompt

    def test_wording_prefers_workbench_fidelity_over_lecture_verbatim(self):
        prompt = build_deep_study_prompt(topic="Агенты ИИ", sections=[MAIN_IDEA])
        assert "РАБОЧЕМУ КОНСПЕКТУ" in prompt
        assert "дословности исходной лекции" in prompt

    def test_empty_topic_falls_back_to_default_label(self):
        prompt = build_deep_study_prompt(topic="", sections=[MAIN_IDEA])
        assert "## Тема\nБез темы" in prompt

    def test_no_sections_yields_placeholder_quotes(self):
        prompt = build_deep_study_prompt(topic="Агенты ИИ", sections=[])
        assert "(разделы не выбраны)" in prompt
        assert "(не найдено" in prompt

    def test_roles_placeholders_when_sections_lack_provenance(self):
        """Голые ParsedSection без konspekt_md_abs → ролям неоткуда взяться."""
        prompt = build_deep_study_prompt(topic="Агенты ИИ", sections=[MAIN_IDEA])
        assert prompt.count("(в конспекте нет)") == 2  # pitfalls + check_questions


RICH_KONSPEKT_MD = """# Конспект

## 🎯 Главная мысль

Агент — система вокруг LLM, а не разовый вызов.

## 🔹 ReAct

ReAct выбирает следующий шаг после наблюдения.

## ⚠️ Ошибки, риски и антипаттерны

ReAct без stop-controller — бесконечный цикл и расход бюджета.

## ❓ Контрольные вопросы

Чем workflow отличается от агента?
"""


@pytest.fixture
def rich_konspekt(tmp_path: Path) -> Path:
    p = tmp_path / "rich.md"
    p.write_text(RICH_KONSPEKT_MD, encoding="utf-8")
    return p


def _indexed(section: ParsedSection, md: Path) -> IndexedSection:
    return IndexedSection(
        heading_text=section.heading_text,
        slug=section.slug,
        level=section.level,
        line_start=section.line_start,
        line_end=section.line_end,
        text=section.text,
        own_text=section.own_text,
        source_abs=md.with_suffix(".txt"),
        konspekt_md_abs=md,
    )


class TestLectureSpirit:
    """«Дух лекции»: роли из ПОЛНЫХ конспектов документов выбранных секций."""

    def test_pitfalls_and_check_questions_pulled_from_document(self, rich_konspekt: Path):
        react = next(s for s in parse_sections(rich_konspekt) if "ReAct" in s.heading_text)
        prompt = build_deep_study_prompt(topic="ReAct", sections=[_indexed(react, rich_konspekt)])
        assert "ReAct без stop-controller — бесконечный цикл и расход бюджета." in prompt
        assert "Чем workflow отличается от агента?" in prompt
        assert "(в конспекте нет)" not in prompt

    def test_doc_level_main_idea_preferred_when_not_selected(self, rich_konspekt: Path):
        """В корзине только подтема — главная мысль берётся из полного конспекта,
        а не подменяется «первой содержательной H2 среди выбранных»."""
        react = next(s for s in parse_sections(rich_konspekt) if "ReAct" in s.heading_text)
        prompt = build_deep_study_prompt(topic="ReAct", sections=[_indexed(react, rich_konspekt)])
        main_idea_block = prompt.split("## Главная мысль", 1)[1].split("##", 1)[0]
        assert "Агент — система вокруг LLM, а не разовый вызов." in main_idea_block

    def test_missing_document_degrades_to_placeholders(self, tmp_path: Path):
        ghost = _indexed(MAIN_IDEA, tmp_path / "ghost.md")
        prompt = build_deep_study_prompt(topic="Агенты ИИ", sections=[ghost])
        assert prompt.count("(в конспекте нет)") == 2
