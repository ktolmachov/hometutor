"""Smoke-рендер ``_render_card_section_links`` через ``streamlit.testing.v1.AppTest``.

Регрессионный тест на Findings: ``st.link_button(..., key=...)`` кидал ``TypeError`` в
Streamlit 1.55 — ``try/except`` в функции закрывает только поиск секции (до вызова
``best_section_for``), сами кнопки рисуются вне try/except, поэтому карточка ронялась
целиком, если секция находилась.
"""

from __future__ import annotations

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
    import app.section_index as section_index
    import app.ui.flashcards_review_view as review_view

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
