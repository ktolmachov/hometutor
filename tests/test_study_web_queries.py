"""Tests for app.study_web_queries (pure URL construction, no network)."""

from __future__ import annotations

from urllib.parse import quote_plus

from app.study_web_queries import build_query_terms, build_web_search_links


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
