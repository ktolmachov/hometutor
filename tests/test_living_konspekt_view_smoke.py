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

from app.config import DATA_DIR
from app.media_sidecar import GeneratedBy, MediaSection, MediaSidecar, UrlVideoSource
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
        source_abs=DATA_DIR / "_test_view_smoke" / "lecture.txt",
        konspekt_md_abs=konspekt_md_abs or DATA_DIR / "_test_view_smoke" / "lecture.md",
    )
    return section_to_row(section)


def _data_fixture_path(tmp_path: Path, name: str) -> Path:
    path = DATA_DIR / "_test_view_smoke" / tmp_path.name / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


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
    import app.ui.living_konspekt_view as living_konspekt_view
    import app.user_state as user_state
    import app.user_state_core as user_state_core

    monkeypatch.setattr(user_state_core, "get_kv", lambda key, default=None: default)
    monkeypatch.setattr(user_state_core, "set_kv", lambda key, value: None)
    monkeypatch.setattr(ui_events, "track_event", lambda name, payload=None: None)
    monkeypatch.setattr(user_state, "count_due_flashcards", lambda **kwargs: 0)
    monkeypatch.setattr(living_konspekt_view, "render_add_sections_panel", lambda *, expanded=False: None)


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

    def test_existing_artifacts_show_title_picker(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        import app.konspekt_artifact as konspekt_artifact_module
        import app.obsidian_export as obsidian_export

        target_dir = tmp_path / "living-konspekt"
        target_dir.mkdir()
        (target_dir / "course-a.md").write_text(
            konspekt_artifact_module.serialize_manifest(
                "Курс A",
                [],
                [],
                artifact_id="course-a",
            )
            + "# Course A\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(obsidian_export, "vault_root", lambda: tmp_path)

        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row()]
        at.run()
        assert not at.exception
        labels = [str(sb.label) for sb in at.get("selectbox")]
        assert any("Существующий конспект" in label for label in labels)

    def test_saved_artifacts_panel_shows_delete_button(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        import app.konspekt_artifact as konspekt_artifact_module
        import app.obsidian_export as obsidian_export

        target_dir = tmp_path / "living-konspekt"
        target_dir.mkdir()
        (target_dir / "course-a.md").write_text(
            konspekt_artifact_module.serialize_manifest(
                "Курс A",
                [],
                [],
                artifact_id="course-a",
            )
            + "# Course A\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(obsidian_export, "vault_root", lambda: tmp_path)

        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row()]
        at.run()
        assert not at.exception
        delete_buttons = [b for b in at.get("button") if "Удалить" in str(b.label)]
        assert delete_buttons
        delete_buttons[0].click().run()
        assert not (target_dir / "course-a.md").exists()
        assert not at.exception


def _media_sidecar(confidence: float = 0.82) -> MediaSidecar:
    return MediaSidecar(
        schema_version=1,
        konspekt_sha256="a" * 64,
        media_sha256=None,
        generated_by=GeneratedBy(
            tool="test",
            created_at="2026-07-05T00:00:00Z",
            asr_model="test-asr",
            alignment_version="test-align",
        ),
        video=UrlVideoSource(url="https://youtu.be/abcDEF12345", title="Видео"),
        sections=(
            MediaSection(
                section_id=f"sha256:{'b' * 64}",
                section_slug="tema",
                heading="Тема",
                line_start=10,
                line_end=13,
                t_start=75,
                t_end=120,
                confidence=confidence,
            ),
        ),
    )


def _media_sidecar_with_multiple_videos() -> MediaSidecar:
    sidecar = _media_sidecar()
    return MediaSidecar(
        schema_version=sidecar.schema_version,
        konspekt_sha256=sidecar.konspekt_sha256,
        media_sha256=sidecar.media_sha256,
        generated_by=sidecar.generated_by,
        video=sidecar.video,
        videos=(
            sidecar.video,
            UrlVideoSource(url="https://youtu.be/second12345", title="Дополнительное видео"),
        ),
        sections=sidecar.sections,
    )


class TestMediaPanelSmoke:
    def test_valid_sidecar_shows_youtube_timestamp_action(self, monkeypatch):
        import app.ui.living_konspekt_media as view

        iframe_calls: list[tuple[str, int]] = []
        monkeypatch.setattr(view.components, "iframe", lambda src, height: iframe_calls.append((src, height)))
        monkeypatch.setattr(view, "load_media_sidecar_for_konspekt", lambda path: _media_sidecar())
        monkeypatch.setattr(view, "sha256_file", lambda path: "a" * 64)

        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row()]
        at.run()

        assert not at.exception
        assert any("Материал раздела" in str(md.value) for md in at.markdown)
        link_buttons = at.get("link_button")
        assert any(button.label == "Открыть на YouTube с 1:15" for button in link_buttons)
        assert any("t=75s" in button.url for button in link_buttons)
        assert any("youtube.com/embed/abcDEF12345?start=75" in src for src, _ in iframe_calls)

    def test_multiple_sidecar_videos_show_all_actions(self, monkeypatch):
        import app.ui.living_konspekt_media as view

        iframe_calls: list[tuple[str, int]] = []
        monkeypatch.setattr(view.components, "iframe", lambda src, height: iframe_calls.append((src, height)))
        monkeypatch.setattr(view, "load_media_sidecar_for_konspekt", lambda path: _media_sidecar_with_multiple_videos())
        monkeypatch.setattr(view, "sha256_file", lambda path: "a" * 64)

        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row()]
        at.run()

        # Check all checkboxes to render the iframe players
        for cb in at.checkbox:
            if "Показать встроенный плеер" in str(cb.label):
                cb.check()
        at.run()

        assert not at.exception
        assert any("Все видео урока" in str(md.value) for md in at.markdown)
        labels = [button.label for button in at.get("link_button")]
        assert "Открыть на YouTube: Видео" in labels
        assert "Открыть на YouTube: Дополнительное видео" in labels
        assert "Открыть на YouTube с 1:15" in labels
        iframe_srcs = [src for src, _ in iframe_calls]
        assert any("youtube.com/embed/abcDEF12345" in src for src in iframe_srcs)
        assert any("youtube.com/embed/second12345" in src for src in iframe_srcs)

    def test_stale_sidecar_degrades_without_timestamp_action(self, monkeypatch):
        import app.ui.living_konspekt_media as view

        monkeypatch.setattr(view, "load_media_sidecar_for_konspekt", lambda path: _media_sidecar())
        monkeypatch.setattr(
            view,
            "current_konspekt_sha256_for_sidecar",
            lambda path, sidecar_sha: "0" * 64,
        )

        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row()]
        at.run()

        assert not at.exception
        captions = [c.value for c in at.caption]
        assert any("Таймкоды устарели" in c for c in captions)
        link_buttons = at.get("link_button")
        assert not any("с 1:15" in button.label for button in link_buttons)
        assert any("Открыть на YouTube: Видео" in button.label for button in link_buttons)

    def test_low_confidence_sidecar_degrades_without_timestamp_action(self, monkeypatch):
        import app.ui.living_konspekt_media as view

        monkeypatch.setattr(view, "load_media_sidecar_for_konspekt", lambda path: _media_sidecar(confidence=0.4))
        monkeypatch.setattr(view, "sha256_file", lambda path: "a" * 64)

        at = AppTest.from_function(_app)
        at.session_state["workbench_sections"] = [_row()]
        at.run()

        assert not at.exception
        captions = [c.value for c in at.caption]
        assert any("confidence ниже порога" in c for c in captions)
        link_buttons = at.get("link_button")
        assert not any("с 1:15" in button.label for button in link_buttons)
        assert any("Открыть на YouTube: Видео" in button.label for button in link_buttons)


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


class TestBulkDocumentSections:
    def test_adds_h2_document_sections_and_skips_toc(self, tmp_path: Path):
        import app.ui.living_konspekt_view as view

        md = tmp_path / "lesson.md"
        md.write_text(
            "# Lesson\n\n"
            "## 📑 Оглавление\n\n- [A](#a)\n\n"
            "## A\n\nТекст раздела A.\n\n### A.1\n\nДеталь A.\n\n"
            "## B\n\nТекст раздела B.\n",
            encoding="utf-8",
        )
        rows = [_row(heading="A", line_start=5, konspekt_md_abs=md)]
        state: dict = {}

        added, duplicates = view._add_document_sections_to_workbench(str(md), rows, state=state)

        assert (added, duplicates) == (2, 0)
        headings = [row["heading_text"] for row in state["workbench_sections"]]
        assert headings == ["A", "B"]

        added_again, duplicates_again = view._add_document_sections_to_workbench(str(md), rows, state=state)

        assert (added_again, duplicates_again) == (0, 2)


class TestTermCardsPanelSmoke:
    """«🃏 Карточки из терминов лекции» — без нового LLM-вызова, через preview Flashcards."""

    def _konspekt_with_terms(self, tmp_path: Path) -> Path:
        p = _data_fixture_path(tmp_path, "lecture.md")
        p.write_text(
            "# Конспект\n\n## 🧠 Важные термины и концепции\n\n"
            "- **LLM** — большая языковая модель.\n"
            "- **Harness** — обвязка вокруг LLM.\n",
            encoding="utf-8",
        )
        return p

    def _konspekt_with_five_terms(self, tmp_path: Path) -> Path:
        p = _data_fixture_path(tmp_path, "lecture5.md")
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
        from app.term_cards import source_tag_value

        assert {"front": "LLM", "back": "большая языковая модель.", "tags": f"source:{source_tag_value(md)}"} in cards
        assert len(cards) == 5
