"""Tests for the «Живой конспект» workbench (add/dedup/remove, stitch, persist)."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from dataclasses import replace

import pytest

from app import path_safety, workbench_service
from app.konspekt_artifact import (
    _check_questions_block,
    build_videos_block_for_rows,
    parse_manifest,
    reassemble_rows,
    serialize_manifest,
)
from app.path_safety import data_relative_from_path
from app.section_index import IndexedSection, section_to_row
from app.ui.living_konspekt_view import (
    WORKBENCH_SECTIONS_KEY,
    _collect_concept_context,
    _stitch_verbatim,
    _strip_synthesis_tail_sections,
    _study_pack_tail,
    add_section_to_workbench,
    clear_workbench,
    ensure_workbench_hydrated,
    get_workbench_rows,
    move_section_in_workbench,
    remove_section_from_workbench,
    remove_sections_from_workbench,
    set_workbench_rows,
)
from app.ui.living_konspekt_next_steps import graph_lens_items
from app.ui.living_konspekt_workbench_panel import deletion_options
from app.user_state_research import normalize_research_payload
from app.ui.sidebar import apply_research_payload

_MODULE = sys.modules[__name__]

# Isolated from the real DATA_DIR: these tests used to write fixtures directly into
# the configured production data directory (leaking `_test_workbench/` into the real
# corpus and knowledge-graph ingestion). Each test gets a fresh temp dir instead, with
# path_safety.DATA_DIR patched to match — workbench_service's portability round-trip
# resolves konspekt_md_abs/source_abs against it.
DATA_DIR: Path
MD_A: Path
MD_B: Path
SRC_A: Path


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch: pytest.MonkeyPatch):
    base = Path(tempfile.mkdtemp(prefix="hometutor_test_workbench_"))
    monkeypatch.setattr(path_safety, "DATA_DIR", base)
    monkeypatch.setattr(_MODULE, "DATA_DIR", base, raising=False)
    monkeypatch.setattr(_MODULE, "MD_A", base / "_test_workbench" / "lecture-a.md", raising=False)
    monkeypatch.setattr(_MODULE, "MD_B", base / "_test_workbench" / "lecture-b.md", raising=False)
    monkeypatch.setattr(_MODULE, "SRC_A", base / "_test_workbench" / "lecture-a.txt", raising=False)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _section(md: Path, line_start: int, heading: str = "Раздел", text: str = "Текст.") -> IndexedSection:
    return IndexedSection(
        heading_text=heading,
        slug="razdel",
        level=2,
        line_start=line_start,
        line_end=line_start + 3,
        text=text,
        source_abs=SRC_A,
        konspekt_md_abs=md,
    )


class TestWorkbenchServiceV2:
    def test_data_relative_from_path_accepts_abs_inside_data_and_rejects_outside(self):
        inside = DATA_DIR / "folder" / "lesson.md"
        assert data_relative_from_path(inside) == "folder/lesson.md"
        try:
            data_relative_from_path(Path("D:/outside/lesson.md"))
        except ValueError:
            pass
        else:
            raise AssertionError("outside DATA_DIR path must be rejected")

    def test_add_dedup_move_remove_with_storage_seam(self):
        storage = workbench_service.InMemoryWorkbenchStorage()
        rows: list[dict] = []

        rows = workbench_service.add_section(rows, _section(MD_A, 10, heading="A"), storage=storage)
        rows = workbench_service.add_section(rows, _section(MD_A, 20, heading="B"), storage=storage)
        rows = workbench_service.add_section(rows, _section(MD_A, 10, heading="A duplicate"), storage=storage)

        assert [row["heading_text"] for row in rows] == ["A", "B"]
        assert all(row["row_key"].startswith("p:") for row in rows)
        assert all("konspekt_md_abs" not in row for row in storage.rows)
        assert all(row["note"] is None and row["read_at"] is None for row in storage.rows)

        rows = workbench_service.move_section(rows, rows[1]["row_key"], -1, storage=storage)
        assert [row["heading_text"] for row in rows] == ["B", "A"]

        rows = workbench_service.remove_section(rows, rows[0]["row_key"], storage=storage)
        assert [row["heading_text"] for row in rows] == ["A"]

    def test_remove_many_and_clear_with_storage_seam(self):
        storage = workbench_service.InMemoryWorkbenchStorage()
        rows: list[dict] = []
        rows = workbench_service.add_section(rows, _section(MD_A, 10, heading="A"), storage=storage)
        rows = workbench_service.add_section(rows, _section(MD_A, 20, heading="B"), storage=storage)
        rows = workbench_service.add_section(rows, _section(MD_A, 30, heading="C"), storage=storage)

        rows = workbench_service.remove_sections(
            rows,
            {rows[0]["row_key"], rows[2]["row_key"]},
            storage=storage,
        )

        assert [row["heading_text"] for row in rows] == ["B"]
        assert [row["heading_text"] for row in workbench_service.load_rows(storage)] == ["B"]
        assert workbench_service.clear_rows(storage=storage) == []
        assert storage.rows == []

    def test_update_note_and_read_at_with_storage_seam(self):
        storage = workbench_service.InMemoryWorkbenchStorage()
        rows = workbench_service.add_section([], _section(MD_A, 10, heading="A"), storage=storage)
        row_key = rows[0]["row_key"]

        rows = workbench_service.update_section_fields(
            rows,
            row_key,
            note="  моя мысль  ",
            read_at="2026-07-06T10:00:00Z",
            storage=storage,
        )

        assert rows[0]["note"] == "моя мысль"
        assert rows[0]["read_at"] == "2026-07-06T10:00:00Z"
        assert storage.rows[0]["note"] == "моя мысль"
        assert storage.rows[0]["read_at"] == "2026-07-06T10:00:00Z"

    def test_project_goal_normalization_and_storage(self, monkeypatch):
        saved: dict[str, str] = {}

        monkeypatch.setattr("app.user_state_core.get_kv", lambda key, default=None: saved.get(key, default))
        monkeypatch.setattr("app.user_state_core.set_kv", lambda key, value: saved.__setitem__(key, value))

        goal = workbench_service.save_goal({"text": "  подготовиться к экзамену  "})

        assert goal["text"] == "подготовиться к экзамену"
        assert goal["updated_at"]
        assert workbench_service.load_goal()["text"] == "подготовиться к экзамену"

    def test_load_rows_lazily_migrates_v1_abs_to_v2_rel(self):
        legacy_row = section_to_row(_section(MD_A, 10, heading="Legacy"))
        storage = workbench_service.InMemoryWorkbenchStorage([legacy_row])

        rows = workbench_service.load_rows(storage=storage)

        assert rows[0]["heading_text"] == "Legacy"
        assert rows[0]["konspekt_md_abs"] == str(MD_A.resolve())
        assert storage.rows[0]["row_version"] == 2
        assert storage.rows[0]["portability_status"] == "portable"
        assert storage.rows[0]["konspekt_md_rel"].endswith("lecture-a.md")
        assert "konspekt_md_abs" not in storage.rows[0]

    def test_outside_data_dir_legacy_row_becomes_non_portable_snapshot(self):
        outside = Path("D:/outside/lecture.md")
        legacy_row = {
            **section_to_row(_section(outside, 10, heading="Outside")),
            "source_abs": "D:/outside/source.txt",
        }
        storage = workbench_service.InMemoryWorkbenchStorage([legacy_row])

        rows = workbench_service.load_rows(storage=storage)

        assert rows[0]["portability_status"] == "non_portable"
        assert rows[0]["konspekt_md_abs"] == ""
        assert rows[0]["source_abs"] == ""
        assert rows[0]["konspekt_md_label"] == "lecture.md"
        assert storage.rows[0]["row_key"].startswith("np:")
        assert "konspekt_md_rel" not in storage.rows[0]


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
        remove_section_from_workbench(get_workbench_rows(state)[0]["row_key"], state)
        rows = get_workbench_rows(state)
        assert len(rows) == 1
        assert rows[0]["line_start"] == 20

    def test_remove_many_and_clear_update_injected_state(self):
        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10, heading="A"), state)
        add_section_to_workbench(_section(MD_A, 20, heading="B"), state)
        add_section_to_workbench(_section(MD_A, 30, heading="C"), state)

        rows = get_workbench_rows(state)
        remove_sections_from_workbench({rows[0]["row_key"], rows[2]["row_key"]}, state)

        assert [row["heading_text"] for row in get_workbench_rows(state)] == ["B"]
        clear_workbench(state)
        assert get_workbench_rows(state) == []

    def test_deletion_options_label_single_and_bulk_cleanup_targets(self):
        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10, heading="A"), state)
        add_section_to_workbench(_section(MD_A, 20, heading="B"), state)

        options = deletion_options(get_workbench_rows(state))

        assert [label for _, label in options] == [
            "1. A — lecture-a.md:10",
            "2. B — lecture-a.md:20",
        ]
        assert [key for key, _ in options] == [row["row_key"] for row in get_workbench_rows(state)]

    def test_note_and_read_progress_update_injected_state(self):
        from app.ui.living_konspekt_view import mark_section_read_in_workbench, update_section_note_in_workbench

        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10, heading="A"), state)
        row_key = get_workbench_rows(state)[0]["row_key"]

        update_section_note_in_workbench(row_key, "моя мысль", state)
        mark_section_read_in_workbench(row_key, state)

        row = get_workbench_rows(state)[0]
        assert row["note"] == "моя мысль"
        assert str(row["read_at"]).endswith("Z")

    def test_move_reorders_sections_inside_workbench(self):
        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10, heading="A"), state)
        add_section_to_workbench(_section(MD_A, 20, heading="B"), state)
        add_section_to_workbench(_section(MD_A, 30, heading="C"), state)

        moved = move_section_in_workbench(get_workbench_rows(state)[2]["row_key"], -1, state)

        assert moved is True
        assert [row["heading_text"] for row in get_workbench_rows(state)] == ["A", "C", "B"]

    def test_move_outside_bounds_is_noop(self):
        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10, heading="A"), state)

        moved = move_section_in_workbench(get_workbench_rows(state)[0]["row_key"], -1, state)

        assert moved is False
        assert [row["heading_text"] for row in get_workbench_rows(state)] == ["A"]

    def test_defaults_to_streamlit_session_state(self, monkeypatch):
        import streamlit as st
        import app.ui_events as ui_events
        import app.user_state_core as user_state_core

        monkeypatch.setattr(st, "session_state", {})
        monkeypatch.setattr(user_state_core, "set_kv", lambda key, value: None)  # без записи в user_state.db
        monkeypatch.setattr(ui_events, "track_event", lambda name, payload=None: None)
        section = _section(MD_A, 30)
        assert add_section_to_workbench(section) is True
        assert st.session_state[WORKBENCH_SECTIONS_KEY][0]["line_start"] == 30


class TestWorkbenchAutoPersist:
    """Корзина автосохраняется в app_kv и гидрируется при старте сессии.

    Персист гейтится ``state is None``: инжектированный dict (юнит-тесты) не пишет в БД.
    """

    def _capture_kv(self, monkeypatch):
        import app.ui_events as ui_events
        import app.user_state_core as user_state_core

        saved: dict = {}
        monkeypatch.setattr(user_state_core, "set_kv", lambda key, value: saved.__setitem__(key, value))
        monkeypatch.setattr(ui_events, "track_event", lambda name, payload=None: None)
        return saved

    def test_add_with_injected_state_does_not_persist(self, monkeypatch):
        saved = self._capture_kv(monkeypatch)
        add_section_to_workbench(_section(MD_A, 10), {})
        assert saved == {}

    def test_add_with_session_state_persists_json(self, monkeypatch):
        import json
        import streamlit as st

        saved = self._capture_kv(monkeypatch)
        monkeypatch.setattr(st, "session_state", {})
        add_section_to_workbench(_section(MD_A, 10, heading="Тема"))
        rows = json.loads(saved["living_konspekt_workbench_json"])
        assert rows[0]["heading_text"] == "Тема"
        assert rows[0]["row_version"] == 2
        assert rows[0]["portability_status"] == "portable"
        assert "konspekt_md_abs" not in rows[0]

    def test_remove_with_session_state_persists(self, monkeypatch):
        import json
        import streamlit as st

        saved = self._capture_kv(monkeypatch)
        monkeypatch.setattr(st, "session_state", {})
        add_section_to_workbench(_section(MD_A, 10))
        remove_section_from_workbench(st.session_state[WORKBENCH_SECTIONS_KEY][0]["row_key"])
        assert json.loads(saved["living_konspekt_workbench_json"]) == []

    def test_injected_state_hydration_does_not_read_profile(self, monkeypatch):
        import app.user_state_core as user_state_core

        rows_json = '[{"heading_text": "Из профиля", "line_start": 5}]'
        calls: list[str] = []

        def fake_get_kv(key, default=None):
            calls.append(key)
            return rows_json

        monkeypatch.setattr(user_state_core, "get_kv", fake_get_kv)
        state: dict = {}
        ensure_workbench_hydrated(state)
        ensure_workbench_hydrated(state)  # второй вызов — no-op по флагу
        assert get_workbench_rows(state) == []
        assert calls == []

    def test_hydration_does_not_overwrite_existing_session_rows(self, monkeypatch):
        import app.user_state_core as user_state_core

        monkeypatch.setattr(
            user_state_core, "get_kv", lambda key, default=None: '[{"heading_text": "старое"}]'
        )
        state: dict = {WORKBENCH_SECTIONS_KEY: [{"heading_text": "свежее из сессии"}]}
        ensure_workbench_hydrated(state)
        assert get_workbench_rows(state)[0]["heading_text"] == "свежее из сессии"

    def test_hydration_survives_broken_profile(self, monkeypatch):
        import app.user_state_core as user_state_core

        monkeypatch.setattr(user_state_core, "get_kv", lambda key, default=None: "не json {")
        state: dict = {}
        ensure_workbench_hydrated(state)
        assert get_workbench_rows(state) == []

    def test_add_with_session_state_tracks_funnel_event(self, monkeypatch):
        import streamlit as st
        import app.ui_events as ui_events
        import app.user_state_core as user_state_core

        events: list[str] = []
        monkeypatch.setattr(st, "session_state", {})
        monkeypatch.setattr(user_state_core, "set_kv", lambda key, value: None)
        monkeypatch.setattr(ui_events, "track_event", lambda name, payload=None: events.append(name))
        add_section_to_workbench(_section(MD_A, 10))
        assert events == ["living_konspekt_section_added"]

    def test_duplicate_with_session_state_does_not_track_funnel_event(self, monkeypatch):
        import streamlit as st
        import app.ui_events as ui_events
        import app.user_state_core as user_state_core

        events: list[str] = []
        monkeypatch.setattr(st, "session_state", {})
        monkeypatch.setattr(user_state_core, "set_kv", lambda key, value: None)
        monkeypatch.setattr(ui_events, "track_event", lambda name, payload=None: events.append(name))
        add_section_to_workbench(_section(MD_A, 10, heading="First"))
        add_section_to_workbench(_section(MD_A, 10, heading="Duplicate"))
        assert events == ["living_konspekt_section_added"]

    def test_add_with_injected_state_does_not_track(self, monkeypatch):
        import app.ui_events as ui_events

        events: list[str] = []
        monkeypatch.setattr(ui_events, "track_event", lambda name, payload=None: events.append(name))
        add_section_to_workbench(_section(MD_A, 10), {})
        assert events == []

    def test_set_workbench_rows_replaces_and_marks_hydrated(self, monkeypatch):
        import app.user_state_core as user_state_core

        monkeypatch.setattr(
            user_state_core, "get_kv", lambda key, default=None: '[{"heading_text": "из профиля"}]'
        )
        state: dict = {}
        set_workbench_rows([{"heading_text": "restore"}], state)
        ensure_workbench_hydrated(state)  # не должен перетереть restore профилем
        assert get_workbench_rows(state)[0]["heading_text"] == "restore"


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

    def test_appends_sources_footer(self):
        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10, heading="Тема A"), state)
        stitched = _stitch_verbatim(get_workbench_rows(state))
        assert "## Источники" in stitched
        assert "lecture-a.md:10-13 — «Тема A»" in stitched

    def test_prepends_lecture_main_idea_when_konspekt_exists(self, tmp_path: Path):
        md = DATA_DIR / "_test_workbench" / "lecture-main-idea.md"
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(
            "# Конспект\n\n## 🎯 Главная мысль\n\nАгент — система вокруг LLM.\n\n"
            "Второй абзац мысли, который в шапку не идёт.\n\n## 🔹 Тема\n\nТело темы.\n",
            encoding="utf-8",
        )
        state: dict = {}
        add_section_to_workbench(_section(md, 11, heading="🔹 Тема", text="Тело темы."), state)
        stitched = _stitch_verbatim(get_workbench_rows(state))
        assert "> **Главная мысль исходной лекции (lecture-main-idea.md):** Агент — система вокруг LLM." in stitched
        assert "Второй абзац мысли" not in stitched  # только первый абзац — это шапка, не копия

    def test_main_idea_falls_back_to_first_content_h2_without_role_heading(self, tmp_path: Path):
        """Конспект без раздела «Главная мысль» → шапка из первой содержательной H2."""
        md = DATA_DIR / "_test_workbench" / "no-role.md"
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(
            "# Конспект\n\n## 📑 Оглавление\n- x\n\n## Первый раздел\n\nСодержательный абзац раздела.\n",
            encoding="utf-8",
        )
        state: dict = {}
        add_section_to_workbench(_section(md, 6, heading="Первый раздел", text="Содержательный абзац раздела."), state)
        stitched = _stitch_verbatim(get_workbench_rows(state))
        assert "> **Главная мысль исходной лекции (no-role.md):** Содержательный абзац раздела." in stitched

    def test_includes_lecturer_check_questions_when_role_present(self, tmp_path: Path):
        md = DATA_DIR / "_test_workbench" / "with-questions.md"
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(
            "# Конспект\n\n## 🔹 Тема\n\nТело темы.\n\n"
            "## ❓ Контрольные вопросы\n\n1. Чем workflow отличается от агента?\n2. Что такое harness?\n",
            encoding="utf-8",
        )
        state: dict = {}
        add_section_to_workbench(_section(md, 5, heading="🔹 Тема", text="Тело темы."), state)
        stitched = _stitch_verbatim(get_workbench_rows(state))
        assert "## ✅ Проверь себя" in stitched
        assert "1. Чем workflow отличается от агента?" in stitched
        # «Проверь себя» идёт ПЕРЕД источниками — файл заканчивается провенансом.
        assert stitched.index("## ✅ Проверь себя") < stitched.index("## Источники")

    def test_study_pack_tail_gives_sources_even_without_questions(self):
        """LLM-режим: summary + tail — провенанс не теряется, даже когда роли нет."""
        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10, heading="Тема A"), state)
        tail = _study_pack_tail(get_workbench_rows(state))
        assert "## Источники" in tail
        assert "lecture-a.md:10-13" in tail
        assert "Проверь себя" not in tail  # файла-конспекта нет — вопросов нет, честно

    def test_missing_konspekt_files_keep_stitching_working(self):
        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10, heading="Тема A"), state)
        stitched = _stitch_verbatim(get_workbench_rows(state))
        assert "Главная мысль исходной лекции" not in stitched  # файла нет — шапки нет
        assert "## Тема A" in stitched


class TestArtifactManifestSlim:
    """Артефакт не должен дублировать источник: portable-строки slim, non-portable — снимок."""

    def test_portable_row_omits_text_and_own_text_in_manifest(self):
        state: dict = {}
        add_section_to_workbench(_section(MD_A, 10, heading="Тема A", text="Уникальное тело A."), state)
        rows = get_workbench_rows(state)
        assert rows[0]["portability_status"] == workbench_service.PORTABLE

        manifest_yaml = serialize_manifest("T", workbench_service.persisted_rows_from_runtime(rows), [])
        payload = parse_manifest(manifest_yaml)
        row = payload.rows[0]
        assert "text" not in row and "own_text" not in row, "portable manifest row must be slim"
        assert row["section_id"].startswith("sha256:")

    def test_portable_round_trip_restores_text_from_source(self):
        md = DATA_DIR / "_test_workbench" / "slim-roundtrip.md"
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text("# Конспект\n\n## Тема\n\nУникальное тело для round-trip.\n", encoding="utf-8")
        try:
            state: dict = {}
            add_section_to_workbench(_section(md, 3, heading="Тема", text="Уникальное тело для round-trip."), state)
            rows = get_workbench_rows(state)
            manifest_yaml = serialize_manifest("T", workbench_service.persisted_rows_from_runtime(rows), [])
            reassembled = reassemble_rows(parse_manifest(manifest_yaml), data_dir=DATA_DIR)
            assert "Уникальное тело для round-trip." in (reassembled[0].get("text") or "")
        finally:
            md.unlink()

    def test_non_portable_row_keeps_text_snapshot(self):
        np = workbench_service.persisted_row_from_runtime({
            "portability_status": workbench_service.NON_PORTABLE, "resolve_error": "outside_data_dir",
            "konspekt_md_abs": "", "source_abs": "",
            "konspekt_md_label": "legacy.md", "source_label": "legacy.txt",
            "heading_text": "Тема", "slug": "tema", "level": 2,
            "line_start": 7, "line_end": 9, "text": "Снимок.", "own_text": "Снимок.",
        })
        row = parse_manifest(serialize_manifest("T", [np], [])).rows[0]
        assert row.get("text") == "Снимок." and row.get("own_text") == "Снимок."

    def test_check_questions_distributed_across_documents(self):
        md1 = DATA_DIR / "_test_workbench" / "questions-a.md"
        md2 = DATA_DIR / "_test_workbench" / "questions-b.md"
        md1.parent.mkdir(parents=True, exist_ok=True)
        md1.write_text("# A\n\n## ❓ Контрольные вопросы\n\n1. Q1a\n2. Q2a\n3. Q3a\n", encoding="utf-8")
        md2.write_text("# B\n\n## ❓ Контрольные вопросы\n\n1. Q1b\n2. Q2b\n", encoding="utf-8")
        try:
            rows = [{"konspekt_md_abs": str(md1)}, {"konspekt_md_abs": str(md2)}]
            block = _check_questions_block(rows)
            assert "Q1a" in block and "Q1b" in block, "questions must cover BOTH documents"
            # round-robin: первый вопрос каждого документа идёт раньше вторых
            assert block.index("Q1a") < block.index("Q2a")
            assert block.index("Q1b") < block.index("Q2b")
        finally:
            md1.unlink()
            md2.unlink()

    def test_strip_synthesis_tail_removes_llm_sources_block(self):
        sample = "## Введение\n\nТекст.\n\n## Итог\n\nВыводы.\n\n## Источники\n\n- файл.md"
        stripped = _strip_synthesis_tail_sections(sample)
        assert "## Итог" in stripped and "Выводы." in stripped
        assert "## Источники" not in stripped

    def test_build_videos_block_for_rows_returns_empty_without_sidecar(self):
        # Нет sidecar-файла → пустой блок (медиа опционально и не должно ронять сборку).
        assert build_videos_block_for_rows([{"konspekt_md_abs": str(MD_A)}]) == ""


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
        import app.user_state_core as user_state_core

        saved: dict = {}
        monkeypatch.setattr(user_state_core, "set_kv", lambda key, value: saved.__setitem__(key, value))
        monkeypatch.setattr(st, "session_state", {"current_view": "x"})
        rows = [
            {
                "source_abs": str(SRC_A),
                "konspekt_md_abs": str(MD_A),
                "line_start": 10,
                "heading_text": "Тема",
            }
        ]
        apply_research_payload({"workbench_sections": rows})
        assert st.session_state[WORKBENCH_SECTIONS_KEY][0]["heading_text"] == "Тема"
        assert st.session_state[WORKBENCH_SECTIONS_KEY][0]["row_key"].startswith("p:")
        # Restore перезаписывает и локальный профиль (авто-персист).
        assert "living_konspekt_workbench_json" in saved
        assert "konspekt_md_abs" not in saved["living_konspekt_workbench_json"]

    def test_apply_clears_workbench_when_absent_from_payload(self, monkeypatch):
        import streamlit as st
        import app.user_state_core as user_state_core

        monkeypatch.setattr(user_state_core, "set_kv", lambda key, value: None)
        monkeypatch.setattr(st, "session_state", {WORKBENCH_SECTIONS_KEY: [{"stale": True}]})
        apply_research_payload({"current_view": "x"})
        assert st.session_state[WORKBENCH_SECTIONS_KEY] == []


def _row(section: IndexedSection) -> dict:
    return section_to_row(section)


class _FakeKnowledgeGraph:
    """Минимальный double KnowledgeGraphReader для теста агрегации концепт-контекста."""

    def __init__(self, concepts: dict[str, dict]) -> None:
        self._concepts = concepts

    def get_concepts(self) -> dict[str, dict]:
        return dict(self._concepts)

    def get_prerequisites(self, concept_id: str) -> list[str]:
        return list(self._concepts.get(concept_id, {}).get("prerequisites") or [])


class TestCollectConceptContext:
    """См. Findings P2: deep-study prompt должен получать prerequisites/related_concepts
    концепта(ов), к которым привязаны разделы корзины (см. dashboards_graph.py:152)."""

    def _patch_kg(self, monkeypatch, concepts: dict[str, dict]) -> None:
        import app.knowledge_service as knowledge_service

        monkeypatch.setattr(
            knowledge_service, "get_active_knowledge_graph", lambda: _FakeKnowledgeGraph(concepts)
        )

    def test_aggregates_prereqs_and_related_from_single_concept(self, monkeypatch):
        self._patch_kg(
            monkeypatch,
            {
                "Агенты ИИ": {
                    "prerequisites": ["LLM основы"],
                    "related_concepts": ["RAG"],
                },
            },
        )
        row = replace(_section(MD_A, 10), concept="Агенты ИИ")
        prereqs, related = _collect_concept_context([_row(row)])
        assert prereqs == ["LLM основы"]
        assert related == ["RAG"]

    def test_dedups_and_excludes_concepts_already_in_workbench(self, monkeypatch):
        self._patch_kg(
            monkeypatch,
            {
                "A": {"prerequisites": ["B", "Общий"], "related_concepts": ["C"]},
                "B": {"prerequisites": ["Общий"], "related_concepts": ["C"]},
            },
        )
        rows = [
            _row(replace(_section(MD_A, 10), concept="A")),
            _row(replace(_section(MD_B, 5), concept="B")),
        ]
        prereqs, related = _collect_concept_context(rows)
        # "B" — сам концепт корзины (не показываем его как "недостающий prereq"); "Общий" дедупнут.
        assert prereqs == ["Общий"]
        assert related == ["C"]

    def test_graph_lens_marks_missing_and_nearby_concepts(self, monkeypatch):
        self._patch_kg(
            monkeypatch,
            {
                "A": {"prerequisites": ["B"], "related_concepts": ["C"]},
            },
        )
        row = replace(_section(MD_A, 10), concept="A")

        items = graph_lens_items([_row(row)])

        assert items == [{"kind": "missing", "label": "B"}, {"kind": "nearby", "label": "C"}]

    def test_no_concept_on_rows_returns_empty_without_touching_graph(self, monkeypatch):
        def _boom():
            raise AssertionError("get_active_knowledge_graph must not be called when no concept is set")

        import app.knowledge_service as knowledge_service


        monkeypatch.setattr(knowledge_service, "get_active_knowledge_graph", _boom)
        prereqs, related = _collect_concept_context([_row(_section(MD_A, 10))])
        assert prereqs == []
        assert related == []

    def test_graph_lookup_failure_degrades_to_empty_context(self, monkeypatch):
        import app.knowledge_service as knowledge_service

        def _raise():
            raise RuntimeError("no active generation")

        monkeypatch.setattr(knowledge_service, "get_active_knowledge_graph", _raise)
        row = replace(_section(MD_A, 10), concept="Агенты ИИ")
        prereqs, related = _collect_concept_context([_row(row)])
        assert prereqs == []
        assert related == []


class DummyLLMResponse:
    def __init__(self, text: str):
        self.text = text


class DummyLLM:
    def __init__(self, responses: list[str] | None = None):
        self.model = "gpt-4o-mini"
        self.responses = responses or []
        self.calls = []

    def complete(self, prompt: str, **kwargs: Any) -> DummyLLMResponse:
        self.calls.append(prompt)
        text = self.responses.pop(0) if self.responses else f"Synthesis for: {prompt[:30]}..."
        return DummyLLMResponse(text)


class TestLivingKonspektSynthesisMapReduce:
    def test_synthesize_sections_single_chunk_fast_path(self):
        from app.knowledge_synthesis import synthesize_sections

        llm = DummyLLM(responses=["Single Synthesis Output"])
        services = {
            "llm": llm,
        }

        sec = _section(MD_A, 10, heading="Sec1", text="Short text.")
        res = synthesize_sections(topic="My Topic", sections=[sec], services=services)

        assert res["summary"] == "Single Synthesis Output"
        assert len(llm.calls) == 1
        assert "Раздел: Sec1" in llm.calls[0]

    def test_synthesize_sections_map_reduce_multiple_chunks(self):
        from app.knowledge_synthesis import synthesize_sections

        sec1 = _section(MD_A, 10, heading="Sec1", text="A" * 24000)
        sec2 = _section(MD_A, 20, heading="Sec2", text="B" * 24000)
        sec3 = _section(MD_A, 30, heading="Sec3", text="C" * 24000)

        llm = DummyLLM(responses=["Summary Group 1", "Summary Group 2", "Final Synthesis Output"])
        services = {
            "llm": llm,
        }

        res = synthesize_sections(topic="My Topic", sections=[sec1, sec2, sec3], services=services)

        assert res["summary"] == "Final Synthesis Output"
        assert len(llm.calls) == 3
        assert "Sec1" in llm.calls[0] and "Sec2" in llm.calls[0]
        assert "Sec3" in llm.calls[1]
        assert "Summary Group 1" in llm.calls[2] and "Summary Group 2" in llm.calls[2]

    def test_synthesize_sections_truncation_for_giant_section(self):
        from app.knowledge_synthesis import synthesize_sections

        giant_text = "D" * 70000
        sec = _section(MD_A, 10, heading="GiantSec", text=giant_text)

        llm = DummyLLM(responses=["Giant Synthesis Output"])
        services = {
            "llm": llm,
        }

        res = synthesize_sections(topic="My Topic", sections=[sec], services=services)

        assert res["summary"] == "Giant Synthesis Output"
        assert len(llm.calls) == 1
        assert len(llm.calls[0]) < 70000

    def test_render_markdown_with_mermaid(self, monkeypatch):
        from app.ui.living_konspekt_reader import render_markdown_with_mermaid

        markdown_calls = []
        html_calls = []

        def mock_markdown(text, *args, **kwargs):
            markdown_calls.append(text)

        def mock_html(html, *args, **kwargs):
            html_calls.append(html)

        import streamlit as st
        import streamlit.components.v1 as components

        monkeypatch.setattr(st, "markdown", mock_markdown)
        monkeypatch.setattr(components, "html", mock_html)

        text = """Before block.
```flowchart LR
    A --> B
```
Middle block.
```mermaid
    C --> D
```
After block."""

        render_markdown_with_mermaid(text)

        assert len(markdown_calls) == 3
        assert markdown_calls[0] == "Before block.\n"
        assert markdown_calls[1] == "\nMiddle block.\n"
        assert markdown_calls[2] == "\nAfter block."

        assert len(html_calls) == 2
        assert "A --> B" in html_calls[0]
        assert "C --> D" in html_calls[1]

    def test_rewrite_image_paths_for_artifact(self):
        from app.konspekt_artifact import _rewrite_image_paths_for_artifact
        from pathlib import Path

        doc_dir = Path("D:/AI/app/data/Course")
        text = "This is a note with ![Image](assets/pic.png) and ![Web](https://example.com/logo.png)"
        rewritten = _rewrite_image_paths_for_artifact(text, doc_dir)
        
        assert "../Course/assets/pic.png" in rewritten or "..\\Course\\assets\\pic.png" in rewritten
        assert "https://example.com/logo.png" in rewritten


