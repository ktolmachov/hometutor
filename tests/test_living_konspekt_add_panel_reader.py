"""Tests for the in-view Living Konspekt add panel and reader model."""

from __future__ import annotations

from pathlib import Path

from app.section_index import IndexedSection, section_to_row
from app.ui.living_konspekt_add_panel import (
    discover_konspekt_documents,
    search_sections_across,
    sections_of_document,
)
from app.ui.living_konspekt_reader import reader_blocks


def _write_md(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _section(md_abs: Path, line_start: int, heading: str, text: str) -> IndexedSection:
    return IndexedSection(
        heading_text=heading,
        slug=heading.lower().replace(" ", "-"),
        level=2,
        line_start=line_start,
        line_end=line_start + 2,
        text=text,
        own_text=text,
        source_abs=md_abs,
        konspekt_md_abs=md_abs,
    )


class TestDiscoverKonspektDocuments:
    def test_discovers_markdown_documents_and_skips_user_state(self, tmp_path: Path):
        _write_md(tmp_path / "lesson-a.md", "# A\n\n## Тема\n\nТекст.")
        _write_md(tmp_path / "users" / "u1" / "private.md", "# Private")
        (tmp_path / "note.txt").write_text("skip", encoding="utf-8")

        docs = discover_konspekt_documents(tmp_path)

        assert [doc.title for doc in docs] == ["lesson-a"]
        assert docs[0].md_abs == tmp_path / "lesson-a.md"

    def test_missing_data_dir_returns_empty(self, tmp_path: Path):
        assert discover_konspekt_documents(tmp_path / "missing") == []


class TestAddPanelSectionSearch:
    def test_sections_of_document_returns_content_h2_sections(self, tmp_path: Path):
        md = _write_md(
            tmp_path / "lesson.md",
            "# Lesson\n\n## 📑 Оглавление\n\n- A\n\n## Семплирование\n\nТемпература управляет случайностью.\n",
        )

        sections = sections_of_document(md)

        assert [section.heading_text for section in sections] == ["Семплирование"]

    def test_search_sections_across_returns_relevant_sections(self, tmp_path: Path):
        md = _write_md(
            tmp_path / "lesson.md",
            "# Lesson\n\n## Семплирование\n\nТемпература, top-p и вероятность токенов.\n\n"
            "## Архитектура\n\nКомпоненты приложения.\n",
        )
        docs = discover_konspekt_documents(tmp_path)

        results = search_sections_across(docs, "температура вероятность")

        assert results
        assert results[0].konspekt_md_abs == md
        assert results[0].heading_text == "Семплирование"

    def test_empty_query_returns_empty_without_reading_documents(self, tmp_path: Path):
        md = _write_md(tmp_path / "lesson.md", "# Lesson\n\n## A\n\nТекст.")
        docs = discover_konspekt_documents(tmp_path)

        assert docs[0].md_abs == md
        assert search_sections_across(docs, "   ") == []


class TestReaderBlocks:
    def test_reader_blocks_keep_workbench_order_and_full_text(self, tmp_path: Path):
        rows = [
            section_to_row(_section(tmp_path / "a.md", 10, "A", "Полный текст A.")),
            section_to_row(_section(tmp_path / "b.md", 20, "B", "Полный текст B.")),
        ]

        blocks = reader_blocks(rows)

        assert [block["kind"] for block in blocks] == ["heading", "meta", "body", "heading", "meta", "body"]
        assert blocks[0]["text"] == "A"
        assert blocks[2]["text"] == "Полный текст A."
        assert blocks[3]["text"] == "B"
        assert blocks[5]["text"] == "Полный текст B."
