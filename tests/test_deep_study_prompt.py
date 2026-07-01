"""Tests for app.deep_study_prompt (copy-paste prompt builder, no LLM calls)."""

from __future__ import annotations

from app.deep_study_prompt import build_deep_study_prompt
from app.section_index import ParsedSection

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
