"""Tests for app.section_index (Section Anchor Index) + obsidian_export URI helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.section_index import (
    IndexedSection,
    best_section_for,
    heading_repeats_in_document,
    main_idea_section,
    parse_sections,
    row_to_section,
    section_role,
    section_to_row,
    sections_by_role,
    top_sections_for,
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


# Формат урока_1: обзорный H2 «Ключевые темы» с интро + точные H3-подтемы.
# Полное тело родителя включает тела всех детей — без own_text-скоринга родитель
# набирал score >= любого ребёнка и deep-link вёл в пол-документа.
LECTURE_LIKE_MD = """# Конспект

## 🎯 Главная мысль

Агент — это система вокруг модели, а не разовый вызов.

## 📌 Ключевые темы

Краткое интро раздела о темах лекции.

### 🔹 ReAct: думать и действовать по шагу

ReAct выбирает следующий шаг после каждого наблюдения, подход хорош для исследования.

### 🔹 Plan-Execute: сначала план

Планировщик строит план, исполнитель идёт по шагам, при ошибке нужен replan.

## ⚠️ Ошибки и антипаттерны

ReAct без ограничителей превращается в бесконечный цикл и расход бюджета.
"""


@pytest.fixture
def lecture_like_path(tmp_path: Path) -> Path:
    p = tmp_path / "lecture_like.md"
    p.write_text(LECTURE_LIKE_MD, encoding="utf-8")
    return p


class TestOwnText:
    def test_parent_own_text_is_intro_without_children_bodies(self, lecture_like_path: Path):
        sections = parse_sections(lecture_like_path)
        parent = _by_heading(sections, "📌 Ключевые темы")
        assert parent.own_text == "Краткое интро раздела о темах лекции."
        assert "ReAct" not in parent.own_text
        # Полное тело (для сшивки/синтеза) по-прежнему включает детей.
        assert "ReAct выбирает следующий шаг" in parent.text

    def test_leaf_own_text_equals_full_text(self, lecture_like_path: Path):
        sections = parse_sections(lecture_like_path)
        leaf = _by_heading(sections, "🔹 ReAct: думать и действовать по шагу")
        assert leaf.own_text == leaf.text

    def test_section_row_roundtrip_preserves_own_text(self, lecture_like_path: Path, tmp_path: Path):
        parsed = _by_heading(parse_sections(lecture_like_path), "📌 Ключевые темы")
        section = IndexedSection(
            heading_text=parsed.heading_text,
            slug=parsed.slug,
            level=parsed.level,
            line_start=parsed.line_start,
            line_end=parsed.line_end,
            text=parsed.text,
            own_text=parsed.own_text,
            source_abs=tmp_path / "lecture.txt",
            konspekt_md_abs=lecture_like_path,
        )
        restored = row_to_section(section_to_row(section))
        assert restored.own_text == parsed.own_text

    def test_legacy_row_without_own_text_falls_back_to_empty(self):
        restored = row_to_section({"heading_text": "x", "text": "тело", "level": 2, "line_start": 1, "line_end": 2})
        assert restored.own_text == ""


class TestParentChildPrecision:
    def test_query_about_subtopic_returns_h3_not_parent_h2(self, lecture_like_path: Path):
        """Золотой кейс урока_1: «ReAct» должен вести в точный H3, а не в «Ключевые темы»."""
        sections = parse_sections(lecture_like_path)
        best = best_section_for(sections, "ReAct исследование следующий шаг наблюдения")
        assert best is not None
        assert best.heading_text == "🔹 ReAct: думать и действовать по шагу"

    def test_deeper_level_wins_score_tie(self, tmp_path: Path):
        """При равном скоре лист точнее обзорного родителя."""
        p = tmp_path / "tie.md"
        p.write_text(
            "## Обзор ReAct\n\nИнтро обзора без ключевого слова тут.\n\n"
            "### Детали ReAct\n\nПодробности детали здесь совсем про другое.\n",
            encoding="utf-8",
        )
        sections = parse_sections(p)
        ranked = top_sections_for(sections, "ReAct", k=2)
        # Оба матчат только заголовком (score 3 = 3) — глубже уровень, выше место.
        assert [s.heading_text for s in ranked] == ["Детали ReAct", "Обзор ReAct"]


class TestTopSectionsFor:
    def test_returns_only_overlapping_sections_in_score_order(self, lecture_like_path: Path):
        sections = parse_sections(lecture_like_path)
        ranked = top_sections_for(sections, "ReAct ограничителей бюджета цикл бесконечный", k=3)
        headings = [s.heading_text for s in ranked]
        # «Ошибки»: 5 совпадений тела (react/ограничителей/цикл/бюджета/бесконечный) = 5;
        # H3 ReAct: заголовок (3) + тело (1) = 4 — вторым.
        assert headings[0] == "⚠️ Ошибки и антипаттерны"
        assert "🔹 ReAct: думать и действовать по шагу" in headings
        assert "🎯 Главная мысль" not in headings  # нулевой overlap — не показываем

    def test_k_limits_result_count(self, lecture_like_path: Path):
        sections = parse_sections(lecture_like_path)
        assert len(top_sections_for(sections, "ReAct план шаг", k=1)) == 1

    def test_empty_query_returns_empty(self, lecture_like_path: Path):
        sections = parse_sections(lecture_like_path)
        assert top_sections_for(sections, "") == []

    def test_empty_sections_returns_empty(self):
        assert top_sections_for([], "что-то") == []


# Богатый шаблон (hometutor-studio, как урок_1): роли сверх локального минимума.
RICH_KONSPEKT_MD = """# Конспект

## 🎯 Главная мысль

Мысль лекции.

## ⚠️ Ошибки, риски и антипаттерны

ReAct без stop-controller — бесконечный цикл.

## ❓ Контрольные вопросы

Чем workflow отличается от агента?

## 🌐 Дополнительные материалы для глубокого изучения

- [ReAct paper](https://arxiv.org/abs/2210.03629)

## 🧾 Мини-шпаргалка

Agent = LLM + tools + memory + loop.

## 🏁 Итоги и выводы

Выводы лекции.
"""


class TestSectionRole:
    def _sections(self, tmp_path: Path):
        p = tmp_path / "rich.md"
        p.write_text(RICH_KONSPEKT_MD, encoding="utf-8")
        return parse_sections(p)

    def test_rich_template_headings_map_to_roles(self, tmp_path: Path):
        roles = {s.heading_text: section_role(s) for s in self._sections(tmp_path)}
        assert roles["🎯 Главная мысль"] == "main_idea"
        assert roles["⚠️ Ошибки, риски и антипаттерны"] == "pitfalls"
        assert roles["❓ Контрольные вопросы"] == "check_questions"
        assert roles["🌐 Дополнительные материалы для глубокого изучения"] == "external_links"
        assert roles["🧾 Мини-шпаргалка"] == "cheatsheet"
        assert roles["🏁 Итоги и выводы"] == "summary"

    def test_unknown_heading_has_no_role(self, konspekt_path: Path):
        sections = parse_sections(konspekt_path)
        assert section_role(_by_heading(sections, "🔹 Тема первая")) is None

    def test_sections_by_role_collects_first_per_role(self, tmp_path: Path):
        by_role = sections_by_role(self._sections(tmp_path))
        assert by_role["pitfalls"].text == "ReAct без stop-controller — бесконечный цикл."
        assert by_role["check_questions"].text == "Чем workflow отличается от агента?"

    def test_minimal_template_degrades_to_subset(self, konspekt_path: Path):
        """Локальный шаблон конспекта не содержит богатых ролей — их просто нет в dict."""
        by_role = sections_by_role(parse_sections(konspekt_path))
        assert "main_idea" in by_role and "summary" in by_role
        assert "pitfalls" not in by_role
        assert "check_questions" not in by_role


class TestHeadingRepeatsInDocument:
    def test_true_for_duplicated_heading(self, konspekt_path: Path):
        assert heading_repeats_in_document(konspekt_path, "🔹 Тема первая") is True

    def test_false_for_unique_heading(self, konspekt_path: Path):
        assert heading_repeats_in_document(konspekt_path, "🎯 Главная мысль") is False

    def test_false_for_missing_file(self, tmp_path: Path):
        assert heading_repeats_in_document(tmp_path / "nope.md", "Заголовок") is False


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
