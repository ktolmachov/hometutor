"""Tests for the «Живой конспект» workbench (add/dedup/remove, stitch, persist)."""

from __future__ import annotations

from pathlib import Path

from app.section_index import IndexedSection
from app.ui.living_konspekt_view import (
    WORKBENCH_SECTIONS_KEY,
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
