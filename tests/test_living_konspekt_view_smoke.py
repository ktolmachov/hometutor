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


def _row(heading: str = "Тема", line_start: int = 10, konspekt_md_abs: Path | None = None) -> dict:
    section = IndexedSection(
        heading_text=heading,
        slug="tema",
        level=2,
        line_start=line_start,
        line_end=line_start + 3,
        text="Текст раздела для сборки и промпта.",
        source_abs=Path("D:/corpus/lecture.txt"),
        konspekt_md_abs=konspekt_md_abs or Path("D:/vault/lecture.md"),
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
    """Гидрация/авто-персист/аналитика/память не должны трогать реальный user_state.db."""
    import app.ui_events as ui_events
    import app.user_state as user_state
    import app.user_state_core as user_state_core

    monkeypatch.setattr(user_state_core, "get_kv", lambda key, default=None: default)
    monkeypatch.setattr(user_state_core, "set_kv", lambda key, value: None)
    monkeypatch.setattr(ui_events, "track_event", lambda name, payload=None: None)
    monkeypatch.setattr(user_state, "count_due_flashcards", lambda **kwargs: 0)


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


class TestMemoryPanelSmoke:
    """«🧠 Память конспекта» — due-карточки по source:-тегу конспектов корзины."""

    def test_silent_when_no_due_cards(self):
        """Фикстура _isolated_kv отдаёт due=0 — панель не рисуется (ноль шума)."""
        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row()]
        at.run()
        assert not at.exception
        assert not any("Память конспекта" in str(md.value) for md in at.markdown)

    def test_shows_due_and_review_button(self, monkeypatch):
        import app.user_state as user_state

        monkeypatch.setattr(user_state, "count_due_flashcards", lambda **kwargs: 3)
        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row()]
        at.run()
        assert not at.exception
        assert any("Память конспекта" in str(md.value) for md in at.markdown)
        assert any(b.label == "🔁 Повторить" for b in at.button)

    def test_review_click_scopes_queue_by_source_tag(self, monkeypatch):
        import app.user_state as user_state

        monkeypatch.setattr(user_state, "count_due_flashcards", lambda **kwargs: 3)
        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row()]
        at.session_state["flashcards_review_session_deck_id"] = 123
        at.session_state["flashcards_review_deck_sync_pending"] = 123
        at.session_state["flashcards_review_session_scope_signature"] = "deck=123|tags=old"
        at.run()
        review_buttons = [b for b in at.button if b.label == "🔁 Повторить"]
        review_buttons[0].click().run()
        assert not at.exception
        # Тег-скоуп review — штатный ключ text_input в review-секции Flashcards.
        assert str(at.session_state["flashcards_review_session_tags_text"]).startswith("source:")
        assert at.session_state["flashcards_review_session_deck_id"] is None
        assert at.session_state["flashcards_review_deck_sync_pending"] is None
        assert "flashcards_review_session_scope_signature" not in at.session_state
        assert at.session_state["flashcards_section_pending"] == "review"
        assert at.session_state["_pending_current_view"] == "Flashcards"


class TestTermCardsPanelSmoke:
    """«🃏 Карточки из терминов лекции» — без нового LLM-вызова, через preview Flashcards."""

    def _konspekt_with_terms(self, tmp_path: Path) -> Path:
        p = tmp_path / "lecture.md"
        p.write_text(
            "# Конспект\n\n## 🧠 Важные термины и концепции\n\n"
            "- **LLM** — большая языковая модель.\n"
            "- **Harness** — обвязка вокруг LLM.\n",
            encoding="utf-8",
        )
        return p

    def _konspekt_with_five_terms(self, tmp_path: Path) -> Path:
        p = tmp_path / "lecture5.md"
        p.write_text(
            "# Конспект\n\n## 🧠 Важные термины и концепции\n\n"
            "- **LLM** — большая языковая модель.\n"
            "- **Harness** — обвязка вокруг LLM.\n"
            "- **Agent** — система вокруг модели и инструментов.\n"
            "- **Tool** — функция, доступная агенту.\n"
            "- **Context** — данные, доступные модели при ответе.\n",
            encoding="utf-8",
        )
        return p

    def test_degrades_to_caption_without_terms_role(self):
        """Существующая фикстура на несуществующем пути — карточек нет, но панель не падает."""
        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row()]
        at.run()
        assert not at.exception
        captions = [c.value for c in at.caption]
        assert any("карточки собрать не из чего" in c for c in captions)

    def test_less_than_five_terms_shows_minimum_caption_without_button(self, tmp_path: Path):
        md = self._konspekt_with_terms(tmp_path)
        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row(konspekt_md_abs=md)]
        at.run()
        assert not at.exception
        captions = [c.value for c in at.caption]
        assert any("минимум 5 карточек" in c for c in captions)
        buttons = [b.label for b in at.button]
        assert "🃏 Создать карточки из терминов" not in buttons

    def test_shows_button_when_terms_extractable_and_saveable(self, tmp_path: Path):
        md = self._konspekt_with_five_terms(tmp_path)
        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row(konspekt_md_abs=md)]
        at.run()
        assert not at.exception
        buttons = [b.label for b in at.button]
        assert "🃏 Создать карточки из терминов" in buttons

    def test_click_populates_flashcards_preview_and_navigates(self, tmp_path: Path):
        md = self._konspekt_with_five_terms(tmp_path)
        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row(konspekt_md_abs=md)]
        at.session_state["fc_deck_name"] = "Старое имя"
        at.session_state["prev_f_0"] = "Старый front"
        at.run()
        at.button(key="wb_term_cards_btn").click().run()
        assert not at.exception
        # Отложенный переход: current_view — ключ уже инстанцированного st.selectbox в
        # main.py, прямая запись после него кидает StreamlitAPIException, поэтому кнопка
        # пишет PENDING_CURRENT_VIEW_KEY — main.py применит его на следующем прогоне.
        assert at.session_state["_pending_current_view"] == "Flashcards"
        assert at.session_state["flashcards_section_pending"] == "create"
        assert at.session_state["fc_deck_name"] == "Термины — lecture5.md"
        assert "prev_f_0" not in at.session_state
        cards = at.session_state["fc_preview_cards"]
        assert {"front": "LLM", "back": "большая языковая модель.", "tags": f"source:{md}"} in cards
        assert len(cards) == 5
