"""Tests for «➕ Собрать всё по концепту» (dashboards_graph → living-konspekt workbench).

Секции считаются server-side (контракт плана: не ферим из JS); helper собирает лучшую
секцию каждого related-документа концепта в корзину одним действием.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.section_index import IndexedSection
from app.ui.dashboards_graph import _collect_concept_sections_to_workbench

MD_A = Path("D:/vault/lecture_a.md")
MD_B = Path("D:/vault/lecture_b.md")


def _section(md: Path, heading: str, line_start: int) -> IndexedSection:
    return IndexedSection(
        heading_text=heading,
        slug=heading.lower(),
        level=2,
        line_start=line_start,
        line_end=line_start + 5,
        text=f"Тело раздела «{heading}» про агентов.",
        source_abs=Path("D:/corpus/lecture.txt"),
        konspekt_md_abs=md,
    )


@pytest.fixture()
def _stub_section_lookup(monkeypatch: pytest.MonkeyPatch):
    import app.section_index as section_index

    index_by_path = {
        "docs/a.md": [_section(MD_A, "Агенты", 5)],
        "docs/b.md": [_section(MD_B, "Harness", 12)],
        "docs/no_konspekt.txt": [],
    }
    monkeypatch.setattr(section_index, "build_section_index", lambda path: index_by_path.get(str(path), []))
    monkeypatch.setattr(section_index, "best_section_for", lambda sections, query: sections[0] if sections else None)


class TestCollectConceptSections:
    def test_adds_best_section_per_document_with_concept(self, _stub_section_lookup):
        state: dict = {}
        added, duplicates = _collect_concept_sections_to_workbench(
            concept="AI-агент",
            related_docs=["docs/a.md", "docs/b.md", "docs/no_konspekt.txt"],
            doc_index={},
            base_query="агенты harness",
            state=state,
        )
        rows = state["workbench_sections"]
        assert (added, duplicates) == (2, 0)
        assert [row["heading_text"] for row in rows] == ["Агенты", "Harness"]
        assert all(row["concept"] == "AI-агент" for row in rows)

    def test_second_run_reports_duplicates_not_new_rows(self, _stub_section_lookup):
        state: dict = {}
        _collect_concept_sections_to_workbench(
            concept="AI-агент",
            related_docs=["docs/a.md", "docs/b.md"],
            doc_index={},
            base_query="агенты",
            state=state,
        )
        added, duplicates = _collect_concept_sections_to_workbench(
            concept="AI-агент",
            related_docs=["docs/a.md", "docs/b.md"],
            doc_index={},
            base_query="агенты",
            state=state,
        )
        assert (added, duplicates) == (0, 2)
        assert len(state["workbench_sections"]) == 2

    def test_doc_index_meta_path_and_key_concepts_feed_the_query(self, monkeypatch: pytest.MonkeyPatch):
        import app.section_index as section_index

        seen: dict[str, str] = {}

        def fake_build(path: str):
            seen["path"] = str(path)
            return [_section(MD_A, "Агенты", 5)]

        def fake_best(sections, query):
            seen["query"] = query
            return sections[0]

        monkeypatch.setattr(section_index, "build_section_index", fake_build)
        monkeypatch.setattr(section_index, "best_section_for", fake_best)

        state: dict = {}
        _collect_concept_sections_to_workbench(
            concept="AI-агент",
            related_docs=["doc-id-1"],
            doc_index={"doc-id-1": {"relative_path": "docs/a.md", "key_concepts": ["harness", "ReAct"]}},
            base_query="агенты",
            state=state,
        )
        assert seen["path"] == "docs/a.md"
        assert "harness" in seen["query"] and "ReAct" in seen["query"]

    def test_lookup_failure_on_one_doc_does_not_break_others(self, monkeypatch: pytest.MonkeyPatch):
        import app.section_index as section_index

        def fake_build(path: str):
            if "broken" in str(path):
                raise OSError("boom")
            return [_section(MD_A, "Агенты", 5)]

        monkeypatch.setattr(section_index, "build_section_index", fake_build)
        monkeypatch.setattr(section_index, "best_section_for", lambda sections, query: sections[0])

        state: dict = {}
        added, duplicates = _collect_concept_sections_to_workbench(
            concept="AI-агент",
            related_docs=["docs/broken.md", "docs/a.md"],
            doc_index={},
            base_query="агенты",
            state=state,
        )
        assert (added, duplicates) == (1, 0)
