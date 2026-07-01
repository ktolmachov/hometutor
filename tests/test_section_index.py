"""Tests for app.section_index (Section Anchor Index) + obsidian_export URI helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.section_index import (
    IndexedSection,
    best_section_for,
    main_idea_section,
    parse_sections,
    row_to_section,
    section_to_row,
    _cached_parse_sections,
    _tokenize_ru_en,
)

KONSPEKT_MD = """---
source: "docs/lecture.txt"
source_sha256: abc123
generated: 2026-01-01
type: konspekt
tags: [конспект, lecture]
---

# 📝 Конспект: Тест

*Интро абзац.*

## 📑 Оглавление
- [Главная мысль](#главная-мысль)
- [Ключевые темы](#ключевые-темы)

## 🎯 Главная мысль

Суть лекции в двух словах про агентов ИИ.

## 📌 Ключевые темы

### 🔹 Тема первая

Текст первой темы про агентов и инструменты.

### 🔹 Тема первая

Дублирующийся заголовок, второй текст.

## 🏁 Итоги и выводы

Финальные выводы.
"""


@pytest.fixture
def konspekt_path(tmp_path: Path) -> Path:
    p = tmp_path / "lecture.md"
    p.write_text(KONSPEKT_MD, encoding="utf-8")
    return p


def _by_heading(sections, heading_text: str, occurrence: int = 0):
    matches = [s for s in sections if s.heading_text == heading_text]
    return matches[occurrence]


class TestParseSections:
    def test_frontmatter_offset_shifts_line_numbers(self, konspekt_path: Path):
        sections = parse_sections(konspekt_path)
        title = _by_heading(sections, "📝 Конспект: Тест")
        # Line 9 in the raw file (1-indexed): 7 frontmatter lines incl. closing '---' + blank + H1.
        assert title.line_start == 9
        assert title.level == 1

    def test_h2_includes_nested_h3_body(self, konspekt_path: Path):
        sections = parse_sections(konspekt_path)
        topics = _by_heading(sections, "📌 Ключевые темы")
        assert "### 🔹 Тема первая" in topics.text
        assert "Текст первой темы про агентов и инструменты." in topics.text
        assert "Дублирующийся заголовок, второй текст." in topics.text

    def test_h3_body_excludes_sibling_and_parent_boundary(self, konspekt_path: Path):
        sections = parse_sections(konspekt_path)
        first_topic = _by_heading(sections, "🔹 Тема первая", occurrence=0)
        assert first_topic.text == "Текст первой темы про агентов и инструменты."
        assert "Дублирующийся" not in first_topic.text

    def test_duplicate_headings_get_distinct_slugs_and_lines(self, konspekt_path: Path):
        sections = parse_sections(konspekt_path)
        first = _by_heading(sections, "🔹 Тема первая", occurrence=0)
        second = _by_heading(sections, "🔹 Тема первая", occurrence=1)
        assert first.slug != second.slug
        assert first.line_start != second.line_start
        assert first.slug == "тема-первая"
        assert second.slug == "тема-первая-1"

    def test_slug_strips_emoji_and_punctuation(self, konspekt_path: Path):
        sections = parse_sections(konspekt_path)
        main_idea = _by_heading(sections, "🎯 Главная мысль")
        assert main_idea.slug == "главная-мысль"

    def test_no_frontmatter_offset_zero(self, tmp_path: Path):
        p = tmp_path / "plain.md"
        p.write_text("# Заголовок\n\nТело.\n", encoding="utf-8")
        sections = parse_sections(p)
        assert sections[0].line_start == 1

    def test_heading_like_line_inside_code_fence_is_not_a_section_boundary(self, tmp_path: Path):
        """Findings: '# comment' в примере кода не должен обрезать содержащую H2-секцию."""
        p = tmp_path / "code.md"
        p.write_text(
            "## Пример кода\n\n"
            "Текст до примера.\n\n"
            "```python\n"
            "# это комментарий, а не заголовок\n"
            "def f():\n"
            "    pass\n"
            "```\n\n"
            "Текст после примера.\n\n"
            "## Следующий раздел\n\nТело следующего.\n",
            encoding="utf-8",
        )
        sections = parse_sections(p)
        assert [s.heading_text for s in sections] == ["Пример кода", "Следующий раздел"]
        example = sections[0]
        assert "# это комментарий" in example.text
        assert "def f():" in example.text
        assert "Текст после примера." in example.text


class TestCachedParseSections:
    """Кэш — по content-hash, не по (mtime, size): restore/copy с тем же timestamp+размером
    не должен отдавать устаревшие line_start/текст (см. Findings P3)."""

    def test_content_change_with_preserved_stat_invalidates_cache(self, tmp_path: Path):
        p = tmp_path / "note.md"
        p.write_text("# Заголовок\n\nПервый текст.\n", encoding="utf-8")
        st_before = p.stat()

        first = _cached_parse_sections(p)
        assert first[0].text == "Первый текст."

        new_content = "# Заголовок\n\nВторой текст.\n"
        assert len(new_content) == len(p.read_text(encoding="utf-8"))  # тот же size
        p.write_text(new_content, encoding="utf-8")
        import os

        os.utime(p, ns=(st_before.st_atime_ns, st_before.st_mtime_ns))  # тот же mtime

        second = _cached_parse_sections(p)
        assert second[0].text == "Второй текст."

    def test_unchanged_content_hits_cache(self, tmp_path: Path):
        p = tmp_path / "note.md"
        p.write_text("# Заголовок\n\nТекст.\n", encoding="utf-8")
        first = _cached_parse_sections(p)
        second = _cached_parse_sections(p)
        assert first is second


class TestMainIdeaSection:
    def test_finds_main_idea_heading_by_normalized_text(self, konspekt_path: Path):
        sections = parse_sections(konspekt_path)
        section = main_idea_section(sections)
        assert section is not None
        assert section.heading_text == "🎯 Главная мысль"

    def test_falls_back_to_first_content_h2_when_no_main_idea_heading(self, tmp_path: Path):
        p = tmp_path / "no_main_idea.md"
        p.write_text(
            "# Заголовок\n\n## 📑 Оглавление\n- x\n\n## Первый раздел\n\nТекст.\n",
            encoding="utf-8",
        )
        sections = parse_sections(p)
        section = main_idea_section(sections)
        assert section is not None
        assert section.heading_text == "Первый раздел"


class TestBestSectionFor:
    def test_heading_match_outweighs_body_match(self, konspekt_path: Path):
        sections = parse_sections(konspekt_path)
        best = best_section_for(sections, "ключевые темы")
        assert best is not None
        assert best.heading_text == "📌 Ключевые темы"

    def test_body_only_overlap_still_resolves_uniquely(self, konspekt_path: Path):
        sections = parse_sections(konspekt_path)
        best = best_section_for(sections, "суть агентов")
        assert best is not None
        assert best.heading_text == "🎯 Главная мысль"

    def test_skips_toc_and_title_for_ranking(self, konspekt_path: Path):
        sections = parse_sections(konspekt_path)
        # TOC literally contains the words "главная мысль" as a link label — if TOC
        # ranking-noise filtering did not work, it could out-score the real H2 section.
        best = best_section_for(sections, "главная мысль")
        assert best is not None
        assert best.heading_text == "🎯 Главная мысль"

    def test_empty_query_returns_first_non_noise_candidate(self, konspekt_path: Path):
        sections = parse_sections(konspekt_path)
        best = best_section_for(sections, "")
        assert best is not None
        assert best.level != 1

    def test_no_sections_returns_none(self):
        assert best_section_for([], "что угодно") is None

    def test_zero_overlap_with_nonempty_query_returns_none(self, konspekt_path: Path):
        """Findings: нулевой overlap не должен маскироваться под уверенный матч (candidates[0])."""
        sections = parse_sections(konspekt_path)
        best = best_section_for(sections, "совершенно несвязанные слова которых точно нигде нет")
        assert best is None


class TestTokenizeRuEn:
    def test_filters_ru_en_stopwords(self):
        tokens = _tokenize_ru_en("Это тема про агентов и the model")
        assert tokens == {"тема", "агентов", "model"}


class TestSectionRowRoundtrip:
    def test_section_to_row_and_back(self, konspekt_path: Path, tmp_path: Path):
        parsed = parse_sections(konspekt_path)[0]
        section = IndexedSection(
            heading_text=parsed.heading_text,
            slug=parsed.slug,
            level=parsed.level,
            line_start=parsed.line_start,
            line_end=parsed.line_end,
            text=parsed.text,
            source_abs=tmp_path / "lecture.txt",
            konspekt_md_abs=konspekt_path,
            concept="agents",
        )
        row = section_to_row(section)
        assert row["source_abs"] == str(tmp_path / "lecture.txt")
        assert isinstance(row["line_start"], int)
        restored = row_to_section(row)
        assert restored == section


class TestObsidianUriHeading:
    @pytest.fixture(autouse=True)
    def _no_vault_name(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            "app.obsidian_export.get_settings",
            lambda: SimpleNamespace(obsidian_vault_name=None),
        )

    def test_heading_anchor_uses_encoded_hash(self, tmp_path: Path):
        from app.obsidian_export import obsidian_uri

        target = tmp_path / "lecture.md"
        uri = obsidian_uri(target, heading_text="🎯 Главная мысль")
        assert uri.startswith("obsidian://open?path=")
        assert "%23" in uri
        assert "#" not in uri.split("%23", 1)[0]  # no raw '#' before the encoded one

    def test_no_heading_keeps_legacy_uri(self, tmp_path: Path):
        from app.obsidian_export import obsidian_uri

        target = tmp_path / "lecture.md"
        uri = obsidian_uri(target)
        assert "%23" not in uri


class TestVscodeUri:
    def test_encodes_spaces_and_cyrillic_and_appends_line(self):
        from app.obsidian_export import vscode_uri

        target = Path("D:/Projects/hometutor/data/ии агенты/файл.md")
        uri = vscode_uri(target, line=42)
        assert uri.startswith("vscode://file/D:/Projects/hometutor/data/")
        assert " " not in uri
        assert uri.endswith(":42")

    def test_no_line_omits_suffix(self):
        from app.obsidian_export import vscode_uri

        uri = vscode_uri(Path("D:/data/note.md"))
        assert uri == "vscode://file/D:/data/note.md"
