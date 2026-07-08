"""Tests for «➕ Собрать всё по концепту» (dashboards_graph → living-konspekt workbench).

Секции считаются server-side (контракт плана: не ферим из JS); helper собирает лучшую
секцию каждого related-документа концепта в корзину одним действием.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.section_index import IndexedSection
from app.ui.dashboards_graph import (
    _alias_duplicate_suspects,
    _collect_concept_sections_to_workbench,
    _concept_evidence_ledger,
    _graph_quality_audit,
)

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
    import app.obsidian_export as obsidian_export

    index_by_path = {
        "docs/a.md": [_section(MD_A, "Агенты", 5)],
        "docs/b.md": [_section(MD_B, "Harness", 12)],
        "docs/no_konspekt.txt": [],
    }
    monkeypatch.setattr(section_index, "build_section_index", lambda path: index_by_path.get(str(path), []))
    monkeypatch.setattr(section_index, "best_section_for", lambda sections, query: sections[0] if sections else None)
    monkeypatch.setattr(obsidian_export, "obsidian_uri", lambda md, heading_text=None: "obsidian://stub")
    monkeypatch.setattr(obsidian_export, "vscode_uri", lambda md, line=None: "vscode://stub")


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


class TestConceptEvidenceLedger:
    def test_ledger_uses_description_aliases_docs_and_sections(self, _stub_section_lookup):
        ledger = _concept_evidence_ledger(
            "ai-agent",
            {
                "label": "AI Agent",
                "description": "Система вокруг LLM, которая планирует и вызывает tools.",
                "aliases": ["агент", "LLM agent"],
            },
            ["llm-call"],
            ["doc-id-1"],
            {
                "doc-id-1": {
                    "relative_path": "docs/a.md",
                    "summary": "Урок объясняет агентность.",
                    "key_concepts": ["агенты"],
                }
            },
        )

        kinds = [item["kind"] for item in ledger]
        assert kinds[:3] == ["description", "aliases", "prerequisites"]
        doc_item = next(item for item in ledger if item["kind"] == "document")
        assert doc_item["title"] == "docs/a.md"
        assert doc_item["sections"][0]["heading"] == "Агенты"
        assert doc_item["sections"][0]["line_start"] == 5
        assert doc_item["sections"][0]["obs_uri"] == "obsidian://stub"
        assert doc_item["sections"][0]["vscode_uri"] == "vscode://stub"

    def test_alias_duplicate_suspects_surface_close_aliases_only(self):
        concepts = {
            "llm-call": {
                "label": "LLM call",
                "aliases": ["вызов LLM", "model call"],
            },
            "model-call": {
                "label": "Model call",
                "aliases": ["LLM вызов"],
            },
            "retrieval": {
                "label": "Retrieval",
                "aliases": ["поиск контекста"],
            },
        }

        suspects = _alias_duplicate_suspects("llm-call", concepts)

        assert [item["concept_id"] for item in suspects] == ["model-call"]
        assert suspects[0]["score"] >= 0.74


class TestGraphQualityAudit:
    def test_audit_counts_duplicates_missing_sections_docs_and_relation_evidence(self):
        concepts = {
            "llm-call": {
                "label": "LLM call",
                "aliases": ["model call"],
                "description": "Вызов модели.",
            },
            "model-call": {
                "label": "Model call",
                "aliases": ["LLM вызов"],
                "description": "Похожий термин.",
            },
            "orphan": {"label": "Orphan"},
            "with-doc-no-section": {
                "label": "With doc",
                "description": "Документ есть, но секций нет.",
            },
        }
        payload = {
            "nodes": [
                {
                    "id": "llm-call",
                    "desc": "Вызов модели.",
                    "related": [{"path": "a.md", "sections": [{"heading": "LLM call"}]}],
                },
                {
                    "id": "model-call",
                    "desc": "Похожий термин.",
                    "related": [{"path": "b.md", "sections": [{"heading": "Model call"}]}],
                },
                {"id": "orphan", "desc": "", "related": []},
                {
                    "id": "with-doc-no-section",
                    "desc": "Документ есть.",
                    "related": [{"path": "c.md", "sections": []}],
                },
            ],
            "health": {"score": 100, "orphans": ["orphan"]},
        }
        typed_relations = [
            {
                "source_concept_id": "llm-call",
                "target_concept_id": "model-call",
                "relation_type": "related",
            },
            {
                "source_concept_id": "llm-call",
                "target_concept_id": "with-doc-no-section",
                "relation_type": "uses",
                "evidence_doc_id": "doc-1",
            },
            {
                "source_concept_id": "model-call",
                "target_concept_id": "with-doc-no-section",
                "relation_type": "uses",
                "evidence_doc_id": "doc-1",
                "evidence_chunk_id": "chunk-1",
            },
        ]

        audit = _graph_quality_audit(concepts, payload, typed_relations)

        assert audit["score"] < 100
        counters = audit["counters"]
        assert counters["duplicates"] == 1
        assert counters["no_docs"] == 1
        assert counters["no_sections"] == 1
        assert counters["no_description"] == 1
        assert counters["relations_without_evidence"] == 2
        titles = [item["title"] for item in audit["findings"]]
        assert any("Возможный дубль" in title for title in titles)
        assert any("Нет точных разделов" in title for title in titles)

    def test_audit_separates_test_artifacts_and_lesson_anchor_pairs(self):
        concepts = {
            "lesson:course-lecture-md": {
                "label": "Lecture",
                "level": "lesson",
                "related_documents": ["course/lecture.md"],
            },
            "lesson:course-lecture-txt": {
                "label": "Lecture",
                "level": "lesson",
                "related_documents": ["course/lecture.txt"],
            },
            "lesson:test-fixture-lecture-md": {
                "label": "lecture",
                "level": "lesson",
                "related_documents": ["_test_fixture/lecture.md"],
            },
            "course-lecture": {
                "label": "Lecture",
                "description": "Semantic concept with a lesson-like title.",
            },
            "ai-agent": {"label": "AI Agent", "aliases": ["LLM agent"], "description": "Агент."},
            "llm-agent": {"label": "LLM Agent", "aliases": ["AI Agent"], "description": "Агент."},
        }
        payload = {
            "nodes": [
                {"id": cid, "desc": raw.get("description", raw.get("label")), "related": [{"sections": [{"heading": "H"}]}]}
                for cid, raw in concepts.items()
            ],
            "health": {"score": 100, "orphans": []},
        }

        audit = _graph_quality_audit(concepts, payload, [])

        counters = audit["counters"]
        assert counters["test_artifacts"] == 1
        assert counters["duplicates"] == 1
        titles = [item["title"] for item in audit["findings"]]
        assert any("Тестовые артефакты" in title for title in titles)
        assert any("ai-agent ↔ llm-agent" in title for title in titles)
        assert not any("course-lecture-md ↔ lesson:course-lecture-txt" in title for title in titles)
        assert not any("course-lecture" in title and "lesson:" in title for title in titles)
