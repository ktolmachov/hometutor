"""Tests for app.term_cards (flashcards from saved konspekt «Важные термины»)."""

from __future__ import annotations

from pathlib import Path

from app.term_cards import parse_term_cards, term_cards_from_documents


class TestParseTermCards:
    def test_extracts_term_and_definition_from_em_dash_bullets(self):
        text = (
            "- **LLM** — большая языковая модель, генерирующая текст.\n"
            "- **Harness** — обвязка вокруг LLM: инструменты, память, stop rules.\n"
        )
        cards = parse_term_cards(text)
        assert cards == [
            {"front": "LLM", "back": "большая языковая модель, генерирующая текст."},
            {"front": "Harness", "back": "обвязка вокруг LLM: инструменты, память, stop rules."},
        ]

    def test_accepts_star_bullet_and_different_dash_variants(self):
        text = (
            "* **Agent** – система с reasoning.\n"
            "- **Tool** - функция, вызываемая моделью.\n"
        )
        cards = parse_term_cards(text)
        fronts = [c["front"] for c in cards]
        assert fronts == ["Agent", "Tool"]

    def test_term_with_slash_is_captured_verbatim(self):
        text = "- **Environment \\ среда** — пространство, где агент работает.\n"
        cards = parse_term_cards(text)
        assert cards[0]["front"] == "Environment \\ среда"

    def test_dedups_by_term_case_insensitively_keeps_first(self):
        text = (
            "- **LLM** — первое определение.\n"
            "- **llm** — второе определение, должно быть отброшено.\n"
        )
        cards = parse_term_cards(text)
        assert len(cards) == 1
        assert cards[0]["back"] == "первое определение."

    def test_non_term_lines_are_ignored(self):
        text = (
            "Обычный текст без формата термина.\n"
            "- Просто пункт списка без жирного термина.\n"
            "- **Без определения**\n"
        )
        assert parse_term_cards(text) == []

    def test_empty_text_returns_empty_list(self):
        assert parse_term_cards("") == []


class TestTermCardsFromDocuments:
    def _write_konspekt(self, tmp_path: Path, name: str, terms_block: str) -> Path:
        p = tmp_path / name
        p.write_text(
            "# Конспект\n\n## 🧠 Важные термины и концепции\n\n" + terms_block,
            encoding="utf-8",
        )
        return p

    def test_collects_cards_with_source_tag(self, tmp_path: Path):
        md = self._write_konspekt(
            tmp_path, "lecture.md", "- **RAG** — retrieval-augmented generation.\n"
        )
        cards, source_docs = term_cards_from_documents([str(md)])
        assert cards == [
            {"front": "RAG", "back": "retrieval-augmented generation.", "tags": "источник:lecture.md"}
        ]
        assert source_docs == ["lecture.md"]

    def test_dedups_terms_across_documents_keeps_first_document(self, tmp_path: Path):
        md_a = self._write_konspekt(tmp_path, "a.md", "- **Harness** — определение A.\n")
        md_b = self._write_konspekt(tmp_path, "b.md", "- **Harness** — определение B.\n")
        cards, source_docs = term_cards_from_documents([str(md_a), str(md_b)])
        assert len(cards) == 1
        assert cards[0]["back"] == "определение A."
        # b.md не добавил ни одной НОВОЙ карточки — не входит в source_docs.
        assert source_docs == ["a.md"]

    def test_document_without_terms_role_is_skipped(self, tmp_path: Path):
        p = tmp_path / "no_terms.md"
        p.write_text("# Конспект\n\n## 🔹 Тема\n\nТело без терминов.\n", encoding="utf-8")
        cards, source_docs = term_cards_from_documents([str(p)])
        assert cards == [] and source_docs == []

    def test_missing_file_is_silently_skipped(self, tmp_path: Path):
        cards, source_docs = term_cards_from_documents([str(tmp_path / "ghost.md")])
        assert cards == [] and source_docs == []

    def test_empty_paths_returns_empty(self):
        assert term_cards_from_documents([]) == ([], [])
