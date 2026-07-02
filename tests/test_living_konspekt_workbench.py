"""Tests for the «Живой конспект» workbench (add/dedup/remove, stitch, persist)."""

from __future__ import annotations

from pathlib import Path

from dataclasses import replace

from app.section_index import IndexedSection, section_to_row
from app.ui.living_konspekt_view import (
    WORKBENCH_SECTIONS_KEY,
    _collect_concept_context,
    _stitch_verbatim,
    add_section_to_workbench,
    get_workbench_rows,
    remove_section_from_workbench,
)
from app.user_state_research import normalize_research_payload
from app.ui.sidebar import apply_research_payload

MD_A = Path("D:/vault/lecture-a.md")
MD_B = Path("D:/vault/lecture-b.md")


def _section(md: Path, line_start: int, heading: str = "Раздел", text: str = "Текст.") -> IndexedSection:
    return IndexedSection(
        heading_text=heading,
        slug="razdel",
        level=2,
        line_start=line_start,
        line_end=line_start + 3,
        text=text,
        source_abs=Path("D:/corpus/lecture-a.txt"),
        konspekt_md_abs=md,
    )


class TestAddDedupRemove:
    def test_add_new_section_returns_true_and_stores_row(self):
        state: dict = {}
        section = _section(MD_A, 10)
        added = add_section_to_workbench(section, state)
        assert added is True
        rows = get_workbench_rows(state)
        assert len(rows) == 1
        assert rows[0]["konspekt_md_abs"] == str(MD_A)
        assert rows[0]["line_start"] == 10

    def test_add_duplicate_by_md_and_line_start_is_noop(self):
        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10, heading="First"), state)
        added_again = add_section_to_workbench(_section(MD_A, 10, heading="Different heading text"), state)
        assert added_again is False
        assert len(get_workbench_rows(state)) == 1

    def test_same_line_start_different_file_is_not_a_duplicate(self):
        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10), state)
        added = add_section_to_workbench(_section(MD_B, 10), state)
        assert added is True
        assert len(get_workbench_rows(state)) == 2

    def test_remove_deletes_only_matching_row(self):
        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10), state)
        add_section_to_workbench(_section(MD_A, 20), state)
        remove_section_from_workbench(str(MD_A), 10, state)
        rows = get_workbench_rows(state)
        assert len(rows) == 1
        assert rows[0]["line_start"] == 20

    def test_defaults_to_streamlit_session_state(self, monkeypatch):
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {})
        section = _section(MD_A, 30)
        assert add_section_to_workbench(section) is True
        assert st.session_state[WORKBENCH_SECTIONS_KEY][0]["line_start"] == 30


class TestStitchVerbatim:
    def test_includes_heading_source_and_verbatim_text(self):
        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10, heading="Тема A", text="Дословный текст A."), state)
        add_section_to_workbench(_section(MD_B, 5, heading="Тема B", text="Дословный текст B."), state)
        stitched = _stitch_verbatim(get_workbench_rows(state))
        assert "## Тема A" in stitched
        assert "Дословный текст A." in stitched
        assert "lecture-a.md:10" in stitched
        assert "## Тема B" in stitched
        assert "Дословный текст B." in stitched
        assert "lecture-b.md:5" in stitched

    def test_appends_sources_footer(self):
        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10, heading="Тема A"), state)
        stitched = _stitch_verbatim(get_workbench_rows(state))
        assert "## Источники" in stitched
        assert "lecture-a.md:10-13 — «Тема A»" in stitched

    def test_prepends_lecture_main_idea_when_konspekt_exists(self, tmp_path: Path):
        md = tmp_path / "lecture.md"
        md.write_text(
            "# Конспект\n\n## 🎯 Главная мысль\n\nАгент — система вокруг LLM.\n\n"
            "Второй абзац мысли, который в шапку не идёт.\n\n## 🔹 Тема\n\nТело темы.\n",
            encoding="utf-8",
        )
        state: dict = {}
        add_section_to_workbench(_section(md, 11, heading="🔹 Тема", text="Тело темы."), state)
        stitched = _stitch_verbatim(get_workbench_rows(state))
        assert "> **Главная мысль исходной лекции (lecture.md):** Агент — система вокруг LLM." in stitched
        assert "Второй абзац мысли" not in stitched  # только первый абзац — это шапка, не копия

    def test_main_idea_falls_back_to_first_content_h2_without_role_heading(self, tmp_path: Path):
        """Конспект без раздела «Главная мысль» → шапка из первой содержательной H2."""
        md = tmp_path / "no_role.md"
        md.write_text(
            "# Конспект\n\n## 📑 Оглавление\n- x\n\n## Первый раздел\n\nСодержательный абзац раздела.\n",
            encoding="utf-8",
        )
        state: dict = {}
        add_section_to_workbench(_section(md, 6, heading="Первый раздел", text="Содержательный абзац раздела."), state)
        stitched = _stitch_verbatim(get_workbench_rows(state))
        assert "> **Главная мысль исходной лекции (no_role.md):** Содержательный абзац раздела." in stitched

    def test_missing_konspekt_files_keep_stitching_working(self):
        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10, heading="Тема A"), state)
        stitched = _stitch_verbatim(get_workbench_rows(state))
        assert "Главная мысль исходной лекции" not in stitched  # файла нет — шапки нет
        assert "## Тема A" in stitched


class TestPersistRoundtrip:
    def test_normalize_includes_workbench_rows(self):
        rows = [
            {
                "source_abs": str(Path("D:/corpus/a.txt")),
                "konspekt_md_abs": str(MD_A),
                "heading_text": "Тема",
                "slug": "tema",
                "level": 2,
                "line_start": 10,
                "line_end": 13,
                "text": "Текст.",
                "concept": None,
            }
        ]
        payload = normalize_research_payload(
            current_view="Живой конспект",
            active_topic_id=None,
            last_studied_document=None,
            last_answer=None,
            last_synthesis=None,
            last_learning_plan=None,
            history=[],
            question_draft="",
            topic_document_selections={},
            workbench_sections=rows,
        )
        assert payload["workbench_sections"] == rows

    def test_normalize_defaults_to_empty_list(self):
        payload = normalize_research_payload(
            current_view="Быстрый ответ",
            active_topic_id=None,
            last_studied_document=None,
            last_answer=None,
            last_synthesis=None,
            last_learning_plan=None,
            history=[],
            question_draft="",
            topic_document_selections={},
        )
        assert payload["workbench_sections"] == []

    def test_apply_restores_workbench_sections_into_session_state(self, monkeypatch):
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {"current_view": "x"})
        rows = [{"konspekt_md_abs": str(MD_A), "line_start": 10, "heading_text": "Тема"}]
        apply_research_payload({"workbench_sections": rows})
        assert st.session_state[WORKBENCH_SECTIONS_KEY] == rows

    def test_apply_clears_workbench_when_absent_from_payload(self, monkeypatch):
        import streamlit as st

        monkeypatch.setattr(st, "session_state", {WORKBENCH_SECTIONS_KEY: [{"stale": True}]})
        apply_research_payload({"current_view": "x"})
        assert st.session_state[WORKBENCH_SECTIONS_KEY] == []


def _row(section: IndexedSection) -> dict:
    return section_to_row(section)


class _FakeKnowledgeGraph:
    """Минимальный double KnowledgeGraphReader для теста агрегации концепт-контекста."""

    def __init__(self, concepts: dict[str, dict]) -> None:
        self._concepts = concepts

    def get_concepts(self) -> dict[str, dict]:
        return dict(self._concepts)

    def get_prerequisites(self, concept_id: str) -> list[str]:
        return list(self._concepts.get(concept_id, {}).get("prerequisites") or [])


class TestCollectConceptContext:
    """См. Findings P2: deep-study prompt должен получать prerequisites/related_concepts
    концепта(ов), к которым привязаны разделы корзины (см. dashboards_graph.py:152)."""

    def _patch_kg(self, monkeypatch, concepts: dict[str, dict]) -> None:
        import app.knowledge_service as knowledge_service

        monkeypatch.setattr(
            knowledge_service, "get_active_knowledge_graph", lambda: _FakeKnowledgeGraph(concepts)
        )

    def test_aggregates_prereqs_and_related_from_single_concept(self, monkeypatch):
        self._patch_kg(
            monkeypatch,
            {
                "Агенты ИИ": {
                    "prerequisites": ["LLM основы"],
                    "related_concepts": ["RAG"],
                },
            },
        )
        row = replace(_section(MD_A, 10), concept="Агенты ИИ")
        prereqs, related = _collect_concept_context([_row(row)])
        assert prereqs == ["LLM основы"]
        assert related == ["RAG"]

    def test_dedups_and_excludes_concepts_already_in_workbench(self, monkeypatch):
        self._patch_kg(
            monkeypatch,
            {
                "A": {"prerequisites": ["B", "Общий"], "related_concepts": ["C"]},
                "B": {"prerequisites": ["Общий"], "related_concepts": ["C"]},
            },
        )
        rows = [
            _row(replace(_section(MD_A, 10), concept="A")),
            _row(replace(_section(MD_B, 5), concept="B")),
        ]
        prereqs, related = _collect_concept_context(rows)
        # "B" — сам концепт корзины (не показываем его как "недостающий prereq"); "Общий" дедупнут.
        assert prereqs == ["Общий"]
        assert related == ["C"]

    def test_no_concept_on_rows_returns_empty_without_touching_graph(self, monkeypatch):
        def _boom():
            raise AssertionError("get_active_knowledge_graph must not be called when no concept is set")

        import app.knowledge_service as knowledge_service

        monkeypatch.setattr(knowledge_service, "get_active_knowledge_graph", _boom)
        prereqs, related = _collect_concept_context([_row(_section(MD_A, 10))])
        assert prereqs == []
        assert related == []

    def test_graph_lookup_failure_degrades_to_empty_context(self, monkeypatch):
        import app.knowledge_service as knowledge_service

        def _raise():
            raise RuntimeError("no active generation")

        monkeypatch.setattr(knowledge_service, "get_active_knowledge_graph", _raise)
        row = replace(_section(MD_A, 10), concept="Агенты ИИ")
        prereqs, related = _collect_concept_context([_row(row)])
        assert prereqs == []
        assert related == []
