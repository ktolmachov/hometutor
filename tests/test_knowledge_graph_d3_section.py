"""Tests for app.ui.knowledge_graph_d3._document_section (per-render section-index cache).

Plan (crispy-popping-alpaca.md, Компонент 2): "build_section_index строится один раз на
md-path за render — build_kg_payload мемоизирует индекс по path". Related documents are
often shared by many concept nodes, so without this cache the same md-file gets re-resolved/
re-read/re-hashed once per concept in a single graph render.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.section_index import IndexedSection
from app.ui.knowledge_graph_d3 import _document_section

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
        )
    ]


@pytest.fixture(autouse=True)
def _stub_uri_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """URI-хелперы не важны для этого теста — фиксируем их, чтобы не трогать vault/settings."""
    import app.obsidian_export as obsidian_export

    monkeypatch.setattr(obsidian_export, "obsidian_uri", lambda md, heading_text=None: "obsidian://stub")
    monkeypatch.setattr(obsidian_export, "vscode_uri", lambda md, line=None: "vscode://stub")


class TestDocumentSectionCache:
    def test_shared_index_cache_calls_build_section_index_once_per_path(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[str] = []

        def fake_build_section_index(path: str) -> list[IndexedSection]:
            calls.append(path)
            return _fake_sections()

        import app.section_index as section_index

        monkeypatch.setattr(section_index, "build_section_index", fake_build_section_index)

        cache: dict[str, list] = {}
        first = _document_section(str(MD), "агенты", index_cache=cache)
        second = _document_section(str(MD), "другой запрос про инструменты", index_cache=cache)

        assert calls == [str(MD)]  # второй вызов взял индекс из cache, не пересчитал
        assert first is not None and first["heading_text"] == "Раздел про агентов"
        assert second is not None and second["heading_text"] == "Раздел про агентов"

    def test_without_cache_each_call_rebuilds(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[str] = []

        def fake_build_section_index(path: str) -> list[IndexedSection]:
            calls.append(path)
            return _fake_sections()

        import app.section_index as section_index

        monkeypatch.setattr(section_index, "build_section_index", fake_build_section_index)

        _document_section(str(MD), "агенты")
        _document_section(str(MD), "агенты")

        assert calls == [str(MD), str(MD)]

    def test_empty_index_is_cached_as_none_result(self, monkeypatch: pytest.MonkeyPatch):
        calls: list[str] = []

        def fake_build_section_index(path: str) -> list[IndexedSection]:
            calls.append(path)
            return []

        import app.section_index as section_index

        monkeypatch.setattr(section_index, "build_section_index", fake_build_section_index)

        cache: dict[str, list] = {}
        first = _document_section(str(MD), "агенты", index_cache=cache)
        second = _document_section(str(MD), "агенты", index_cache=cache)

        assert first is None and second is None
        assert calls == [str(MD)]
