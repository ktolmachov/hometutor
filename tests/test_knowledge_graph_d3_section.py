"""Tests for app.ui.knowledge_graph_d3._document_sections (top-k + per-render cache).

Plan (crispy-popping-alpaca.md, Компонент 2): "build_section_index строится один раз на
md-path за render — build_kg_payload мемоизирует индекс по path". Related documents are
often shared by many concept nodes, so without this cache the same md-file gets re-resolved/
re-read/re-hashed once per concept in a single graph render.

v3: payload carries up to 3 sections per document (концепт часто разобран в нескольких
местах конспекта), so the helper returns a list instead of a single best section.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.section_index import IndexedSection
from app.ui.knowledge_graph_d3 import _document_sections, _load_html_template, build_kg_html

MD = Path("D:/vault/lecture.md")


def _fake_sections() -> list[IndexedSection]:
    return [
        IndexedSection(
            heading_text="Раздел про агентов",
            slug="razdel-pro-agentov",
            level=2,
            line_start=5,
            line_end=10,
            text="Текст про агентов ИИ.",
            source_abs=Path("D:/corpus/lecture.txt"),
            konspekt_md_abs=MD,
        ),
        IndexedSection(
            heading_text="Антипаттерны агентов",
            slug="antipatterny-agentov",
            level=2,
            line_start=11,
            line_end=20,
            text="Ошибки и риски при построении агентов без ограничителей.",
            source_abs=Path("D:/corpus/lecture.txt"),
            konspekt_md_abs=MD,
        ),
        IndexedSection(
            heading_text="Совсем другая тема",
            slug="sovsem-drugaya-tema",
            level=2,
            line_start=21,
            line_end=30,
            text="Никакого пересечения со словами запроса здесь нет вообще.",
            source_abs=Path("D:/corpus/lecture.txt"),
            konspekt_md_abs=MD,
        ),
    ]


@pytest.fixture(autouse=True)
def _stub_uri_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """URI-хелперы не важны для этого теста — фиксируем их, чтобы не трогать vault/settings."""
    import app.obsidian_export as obsidian_export

    monkeypatch.setattr(obsidian_export, "obsidian_uri", lambda md, heading_text=None: "obsidian://stub")
    monkeypatch.setattr(obsidian_export, "vscode_uri", lambda md, line=None: "vscode://stub")


class TestDocumentSectionsCache:
    def test_shared_index_cache_calls_build_section_index_once_per_path(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[str] = []

        def fake_build_section_index(path: str) -> list[IndexedSection]:
            calls.append(path)
            return _fake_sections()

        import app.section_index as section_index

        monkeypatch.setattr(section_index, "build_section_index", fake_build_section_index)

        cache: dict[str, list] = {}
        first = _document_sections(str(MD), "агентов", index_cache=cache)
        second = _document_sections(str(MD), "текст про агентов и решения", index_cache=cache)

        assert calls == [str(MD)]  # второй вызов взял индекс из cache, не пересчитал
        assert first and first[0]["heading_text"] == "Раздел про агентов"
        assert second and second[0]["heading_text"] == "Раздел про агентов"

    def test_without_cache_each_call_rebuilds(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[str] = []

        def fake_build_section_index(path: str) -> list[IndexedSection]:
            calls.append(path)
            return _fake_sections()

        import app.section_index as section_index

        monkeypatch.setattr(section_index, "build_section_index", fake_build_section_index)

        _document_sections(str(MD), "агенты")
        _document_sections(str(MD), "агенты")

        assert calls == [str(MD), str(MD)]

    def test_empty_index_is_cached_as_empty_result(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[str] = []

        def fake_build_section_index(path: str) -> list[IndexedSection]:
            calls.append(path)
            return []

        import app.section_index as section_index

        monkeypatch.setattr(section_index, "build_section_index", fake_build_section_index)

        cache: dict[str, list] = {}
        first = _document_sections(str(MD), "агенты", index_cache=cache)
        second = _document_sections(str(MD), "агенты", index_cache=cache)

        assert first == [] and second == []
        assert calls == [str(MD)]


class TestDocumentSectionsTopK:
    def test_returns_only_overlapping_sections_in_score_order(self, monkeypatch: pytest.MonkeyPatch):
        import app.section_index as section_index

        monkeypatch.setattr(section_index, "build_section_index", lambda path: _fake_sections())

        result = _document_sections(str(MD), "агентов риски ограничителей")

        headings = [item["heading_text"] for item in result]
        # «Совсем другая тема» не пересекается с запросом — её нет; порядок по скору.
        assert "Совсем другая тема" not in headings
        assert headings[0] == "Антипаттерны агентов"  # 3 совпадения против 1
        assert "Раздел про агентов" in headings

    def test_each_entry_carries_deep_links(self, monkeypatch: pytest.MonkeyPatch):
        import app.section_index as section_index

        monkeypatch.setattr(section_index, "build_section_index", lambda path: _fake_sections())

        result = _document_sections(str(MD), "агентов")
        assert result
        for item in result:
            assert item["obs_uri"] == "obsidian://stub"
            assert item["vscode_uri"] == "vscode://stub"
            assert isinstance(item["line_start"], int)


class TestKnowledgeGraphTemplateFallback:
    def test_missing_html_template_returns_diagnostic_page(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        import app.ui.knowledge_graph_d3 as kg_d3

        _load_html_template.cache_clear()
        monkeypatch.setattr(kg_d3, "_HTML_TEMPLATE_PATH", tmp_path / "missing.html")

        html = _load_html_template()

        assert "Knowledge Graph не смог загрузить HTML-шаблон" in html
        assert "knowledge_graph_d3_template.html" in html
        _load_html_template.cache_clear()


class TestKnowledgeGraphSelectionBridge:
    def test_build_kg_html_returns_complete_export_document(self):
        html = build_kg_html(
            {
                "nodes": [{"id": "llm-agent", "label": "LLM Agent", "level": "beginner"}],
                "edges": [],
                "levels": {},
                "stats": {"total": 1},
                "weekly_plan": [],
                "health": {},
                "cluster_labels": {},
                "decay_vector": {},
                "mastery_history": [],
                "compiler_health": None,
            }
        )

        assert html.strip().startswith("<!DOCTYPE html>")
        assert '<svg id="svg"></svg>' in html
        for placeholder in [
            "__D3_TAG__",
            "__NODES__",
            "__EDGES__",
            "__LEVELS__",
            "__STATS__",
            "__WEEKLY_PLAN__",
            "__HEALTH__",
            "__CLUSTER_LABELS__",
            "__DECAY_VECTOR__",
            "__MASTERY_HISTORY__",
            "__COMPILER_HEALTH__",
        ]:
            assert placeholder not in html

    def test_export_uses_server_generated_obsidian_links_for_document_actions(self):
        html = build_kg_html(
            {
                "nodes": [
                    {
                        "id": "llm-agent",
                        "label": "LLM Agent",
                        "level": "beginner",
                        "related": [
                            {
                                "src_abs": "D:/corpus/lecture.txt",
                                "md_abs": "D:/vault/lecture.md",
                                "obs_uri": "obsidian://stub",
                                "sections": [],
                            }
                        ],
                    }
                ],
                "edges": [],
                "levels": {},
                "stats": {"total": 1},
                "weekly_plan": [],
                "health": {},
                "cluster_labels": {},
                "decay_vector": {},
                "mastery_history": [],
                "compiler_health": None,
            }
        )

        assert '"obs_uri": "obsidian://stub"' in html
        assert 'href="${_escHtml(r.obs_uri)}"' in html
        assert 'href="${_obsidianUri(r.src_abs)}"' not in html

    def test_node_click_bridge_posts_component_value_and_keeps_url_fallback(self):
        html = build_kg_html(
            {
                "nodes": [],
                "edges": [],
                "levels": {},
                "stats": {},
                "weekly_plan": [],
                "health": {},
                "cluster_labels": {},
                "decay_vector": {},
                "mastery_history": [],
                "compiler_health": None,
            }
        )

        assert "_kgBridgeConceptToStreamlit" in html
        assert "window.parent.__kgSetConcept" in html
        assert "_kgInSrcdoc" in html
        assert "hometutor:kg-select" in html
        assert "concept:conceptId" in html
        assert "pu.searchParams.set('_kgc',conceptId)" in html
        assert "window.top.location.assign(pu.toString())" in html

    def test_renderer_returns_selected_concept_from_component(self, monkeypatch: pytest.MonkeyPatch):
        import app.ui.knowledge_graph_d3 as kg_d3

        captured: dict[str, object] = {}

        def fake_component():
            def _call(**kwargs):
                captured.update(kwargs)
                return "llm-agent"

            return _call

        monkeypatch.setattr(kg_d3, "_kg_d3_component", fake_component)

        payload = kg_d3.render_d3_knowledge_graph(
            {
                "llm-agent": {
                    "label": "LLM Agent",
                    "level": "beginner",
                    "description": "Agent concept.",
                }
            },
            height=500,
        )

        assert payload["selected_concept"] == "llm-agent"
        assert captured["height"] == 500
        assert "LLM Agent" in str(captured["html"])
