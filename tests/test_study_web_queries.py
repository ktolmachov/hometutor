"""Tests for app.study_web_queries (pure URL construction, no network)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus

from app.study_web_queries import (
    build_query_from_rows,
    build_query_terms,
    build_web_search_links,
    harvest_links_from_rows,
)


class TestBuildQueryTerms:
    def test_dedups_case_insensitive_preserving_order(self):
        terms = build_query_terms(
            heading_texts=["Агенты ИИ", "агенты ии"],
            key_concepts=["RAG", "агенты ии"],
        )
        assert terms == "Агенты ИИ RAG"

    def test_strips_whitespace_and_empty_values(self):
        terms = build_query_terms(heading_texts=["  Тема  ", "", "  "], key_concepts=None)
        assert terms == "Тема"

    def test_empty_inputs_return_empty_string(self):
        assert build_query_terms() == ""


class TestBuildWebSearchLinks:
    def test_empty_query_returns_no_links(self):
        assert build_web_search_links("") == []
        assert build_web_search_links("   ") == []

    def test_returns_all_engines_with_encoded_query(self):
        links = build_web_search_links("агенты ИИ")
        labels = [label for label, _ in links]
        assert labels == ["Google", "Google Scholar", "arXiv", "Perplexity", "YouTube"]
        encoded = quote_plus("агенты ИИ")
        for _, url in links:
            assert encoded in url

    def test_spaces_are_url_encoded(self):
        links = build_web_search_links("rag retrieval")
        for _, url in links:
            assert " " not in url
            assert "rag+retrieval" in url


class TestBuildQueryFromRows:
    def test_concepts_lead_then_top_heading_tokens(self):
        rows = [
            {"concept": "AI-агент", "heading_text": "ReAct и планирование"},
            {"concept": "AI-агент", "heading_text": "ReAct без ограничителей"},
            {"concept": None, "heading_text": "Планирование шагов"},
        ]
        query = build_query_from_rows(rows)
        # Концепт впереди; "react" — самый частотный токен заголовков (2 раза).
        assert query.startswith("AI-агент")
        assert "react" in query

    def test_heading_terms_are_capped(self):
        rows = [{"concept": None, "heading_text": f"Уникальное слово{i} заголовка{i}"} for i in range(9)]
        query = build_query_from_rows(rows, max_heading_terms=5)
        assert len(query.split()) == 5

    def test_tokens_duplicating_concepts_are_skipped(self):
        rows = [{"concept": "harness", "heading_text": "Harness как упряжка"}]
        query = build_query_from_rows(rows)
        assert query.lower().split().count("harness") == 1

    def test_empty_rows_return_empty_string(self):
        assert build_query_from_rows([]) == ""

    def test_tie_order_is_deterministic_and_follows_text_order(self):
        """Токены с равной частотой идут в порядке появления в заголовках (не set-итерация)."""
        rows = [{"concept": None, "heading_text": "Гамма альфа бета"}]
        for _ in range(5):
            assert build_query_from_rows(rows) == "гамма альфа бета"


class TestHarvestLinksFromRows:
    def test_extracts_and_dedups_links_from_row_texts(self):
        rows = [
            {"text": "См. [ReAct paper](https://arxiv.org/abs/2210.03629) и ещё раз "
                     "[дубль](https://arxiv.org/abs/2210.03629)."},
            {"text": "Обзор: [survey](https://example.com/survey)."},
        ]
        links = harvest_links_from_rows(rows)
        assert links == [
            ("ReAct paper", "https://arxiv.org/abs/2210.03629"),
            ("survey", "https://example.com/survey"),
        ]

    def test_pulls_external_links_section_from_konspekt(self, tmp_path: Path):
        md = tmp_path / "konspekt.md"
        md.write_text(
            "# Конспект\n\n## 🔹 Тема\n\nТело темы без ссылок.\n\n"
            "## 🌐 Дополнительные материалы для глубокого изучения\n\n"
            "- [Курс лектора](https://example.com/course)\n",
            encoding="utf-8",
        )
        rows = [{"text": "Тело темы без ссылок.", "konspekt_md_abs": str(md)}]
        links = harvest_links_from_rows(rows)
        assert ("Курс лектора", "https://example.com/course") in links

    def test_missing_konspekt_file_is_silently_skipped(self, tmp_path: Path):
        rows = [{"text": "без ссылок", "konspekt_md_abs": str(tmp_path / "ghost.md")}]
        assert harvest_links_from_rows(rows) == []
