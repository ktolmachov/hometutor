"""Smoke-рендер «Живого конспекта» через ``streamlit.testing.v1.AppTest``.

Регрессионный тест на Findings: ``st.link_button(..., key=...)`` кидал ``TypeError``
в Streamlit 1.55 (у ``link_button`` нет параметра ``key``) — юнит-тесты на чистые
хелперы (add/remove/stitch) этого не ловили, потому что не рендерили сам view.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from app.section_index import IndexedSection, section_to_row


def _app() -> None:
    from app.ui.living_konspekt_view import render_living_konspekt_view

    render_living_konspekt_view()


def _row(heading: str = "Тема", line_start: int = 10) -> dict:
    section = IndexedSection(
        heading_text=heading,
        slug="tema",
        level=2,
        line_start=line_start,
        line_end=line_start + 3,
        text="Текст раздела для сборки и промпта.",
        source_abs=Path("D:/corpus/lecture.txt"),
        konspekt_md_abs=Path("D:/vault/lecture.md"),
    )
    return section_to_row(section)


@pytest.fixture(autouse=True)
def _no_vault_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """URI-хелперы не требуют реального vault/файла на диске — фиксируем settings."""
    import app.obsidian_export as obsidian_export

    monkeypatch.setattr(
        obsidian_export, "get_settings", lambda: SimpleNamespace(obsidian_vault_name=None)
    )


@pytest.fixture(autouse=True)
def _isolated_kv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Гидрация/авто-персист корзины не должны трогать реальный user_state.db."""
    import app.user_state_core as user_state_core

    monkeypatch.setattr(user_state_core, "get_kv", lambda key, default=None: default)
    monkeypatch.setattr(user_state_core, "set_kv", lambda key, value: None)


class TestRenderLivingKonspektViewSmoke:
    def test_empty_workbench_renders_without_exception(self):
        at = AppTest.from_function(_app)
        at.run()
        assert not at.exception

    def test_single_section_renders_without_exception(self):
        """Ровно сценарий из Findings: раздел в корзине → «📄 Открыть»/«🖥 VS Code»."""
        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row()]
        at.run()
        assert not at.exception
        link_urls = [b.url for b in at.get("link_button")]
        assert any("obsidian://" in url for url in link_urls)
        assert any("vscode://" in url for url in link_urls)

    def test_duplicate_headings_show_warning_caption(self):
        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row(line_start=10), _row(line_start=20)]
        at.run()
        assert not at.exception
        captions = [c.value for c in at.caption]
        assert any("повторяющихся заголовков" in c for c in captions)
