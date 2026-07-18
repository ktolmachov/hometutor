"""Smoke-рендер ``_render_card_section_links`` через ``streamlit.testing.v1.AppTest``.

Регрессионный тест на Findings: ``st.link_button(..., key=...)`` кидал ``TypeError`` в
Streamlit 1.55 — ``try/except`` в функции закрывает только поиск секции (до вызова
``best_section_for``), сами кнопки рисуются вне try/except, поэтому карточка ронялась
целиком, если секция находилась.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.section_index import IndexedSection


def _fake_sections() -> list[IndexedSection]:
    return [
        IndexedSection(
            heading_text="Агент ИИ",
            slug="agent-ii",
            level=2,
            line_start=5,
            line_end=10,
            text="Агент ИИ — программа, которая принимает решения на основе окружения.",
            source_abs=Path("D:/corpus/lecture.txt"),
            konspekt_md_abs=Path("D:/vault/lecture.md"),
        )
    ]


def _app() -> None:
    from app.ui.flashcards_review_view import _render_card_section_links

    card = {
        "id": 1,
        "front": "Что такое агент ИИ?",
        "back": "Агент ИИ — программа, которая принимает решения на основе окружения.",
        "source": "docs/lecture.txt",
    }
    _render_card_section_links(card, idx=0)


@pytest.fixture(autouse=True)
def _stub_lookups(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.obsidian_export as obsidian_export
    import app.section_index as section_index
    import app.ui.flashcards_review_view as review_view

    monkeypatch.setattr(obsidian_export, "obsidian_uri_if_available", lambda path, heading_text=None: "obsidian://open")
    monkeypatch.setattr(review_view, "source_path_from_card", lambda card: "docs/lecture.txt")
    monkeypatch.setattr(section_index, "build_section_index", lambda path: _fake_sections())


class TestRenderCardSectionLinksSmoke:
    def test_renders_without_exception_when_section_found(self):
        at = AppTest.from_function(_app)
        at.run()
        assert not at.exception
        link_urls = [b.url for b in at.get("link_button")]
        assert any("obsidian://" in url for url in link_urls)
        assert any("vscode://" in url for url in link_urls)

    def test_renders_four_columns_when_video_found(self, monkeypatch: pytest.MonkeyPatch):
        from app.living_konspekt_video_citations import SourceVideoCitation, SourceVideoCitationResolution
        import app.living_konspekt_video_citations as video_citations

        citation = SourceVideoCitation(
            heading="Агент ИИ",
            video_title="Введение в ИИ",
            timestamp_label="10:20",
            start_seconds=620,
            end_seconds=None,
            url="https://youtube.com/watch?v=123&t=620s",
            source_label="lecture.md",
        )
        resolution = SourceVideoCitationResolution("available", citation, "Видео-цитата готова.")

        monkeypatch.setattr(
            video_citations,
            "video_citation_for_candidate",
            lambda candidate: resolution,
        )

        at = AppTest.from_function(_app)
        at.run()
        assert not at.exception

        link_buttons = at.get("link_button")
        link_urls = [b.url for b in link_buttons]
        link_labels = [b.label for b in link_buttons]

        assert any("obsidian://" in url for url in link_urls)
        assert any("vscode://" in url for url in link_urls)
        assert any("youtube.com" in url for url in link_urls)
        assert any("10:20" in label for label in link_labels)

    def test_source_actions_live_inside_explanation_tab_not_between_card_and_tabs(self):
        import app.ui.flashcards_review_view as review_view

        panel_src = inspect.getsource(review_view._render_inline_explanation_panel)
        assert 'st.tabs(["Источник", "Тьютор", "Промпт"])' in panel_src
        assert "_render_inline_source_tab(card, idx)" in panel_src
        assert "_ensure_inline_tutor_session(card, idx) if explanation_active else None" in panel_src

        active_src = inspect.getsource(review_view._render_active_review_card)
        card_pos = active_src.find("components.html(")
        bridge_pos = active_src.find("_render_review_rating_bridge(")
        panel_pos = active_src.find("_render_inline_explanation_panel(card, idx)")
        floating_pos = active_src.find("_render_card_section_links(")
        assert card_pos >= 0
        assert bridge_pos > card_pos
        assert panel_pos > bridge_pos
        assert floating_pos == -1 or floating_pos > bridge_pos
