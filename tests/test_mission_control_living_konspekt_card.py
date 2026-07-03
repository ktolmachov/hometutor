"""Tests for the «Живой конспект» resume card stats on Mission Control."""

from __future__ import annotations

from app.ui.mission_control import build_living_konspekt_card_stats


class TestBuildLivingKonspektCardStats:
    def test_counts_sections_documents_and_concepts(self):
        rows = [
            {"konspekt_md_abs": "D:/vault/a.md", "concept": "AI-агент", "heading_text": "Тема 1"},
            {"konspekt_md_abs": "D:/vault/a.md", "concept": "harness", "heading_text": "Тема 2"},
            {"konspekt_md_abs": "D:/vault/b.md", "concept": "AI-агент", "heading_text": "Тема 3"},
        ]
        stats = build_living_konspekt_card_stats(rows)
        assert stats["sections"] == 3
        assert stats["documents"] == 2
        assert stats["concepts"] == 2  # дедуп: AI-агент один раз

    def test_recent_headings_are_last_two_newest_first(self):
        rows = [
            {"heading_text": "Первый"},
            {"heading_text": "Второй"},
            {"heading_text": "Третий"},
        ]
        stats = build_living_konspekt_card_stats(rows)
        assert stats["recent_headings"] == ["Третий", "Второй"]

    def test_rows_without_concepts_and_headings_degrade(self):
        rows = [{"konspekt_md_abs": "D:/vault/a.md", "concept": None, "heading_text": ""}]
        stats = build_living_konspekt_card_stats(rows)
        assert stats["concepts"] == 0
        assert stats["recent_headings"] == []
