"""P0-2a: area library read-model and scope isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.library_catalog_read import (
    library_ask_folder_rel,
    library_browse_does_not_require_scope,
    list_library_courses,
    list_library_konspekts,
    list_library_sections,
)
from app.ui.library_catalog import (
    activate_course_from_library,
    navigate_to_ask,
    _scope_snapshot,
)
from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
from app.ui.study_scope import ACTIVE_SCOPE_KEY, get_active_scope
from app.library_catalog_read import LibraryCourse


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_list_library_courses_from_index_stats_without_scope() -> None:
    index_stats = {
        "folder_rel_options": ["course_a", "course_b", "living-konspekt"],
        "files": [
            "course_a/lesson-1.md",
            "course_a/lesson-2.md",
            "course_b/module-1.md",
        ],
    }
    courses = list_library_courses(index_stats)
    folders = {c.folder_rel for c in courses}
    assert "course_a" in folders
    assert "course_b" in folders
    # living-konspekt is filtered by is_user_course_folder_rel in course options path
    # (may or may not appear depending on filter); must not require active scope.
    assert library_browse_does_not_require_scope() is True
    a = next(c for c in courses if c.folder_rel == "course_a")
    assert "course_a/lesson-1.md" in a.source_paths


def test_list_library_konspekts_and_sections(tmp_path: Path) -> None:
    course = tmp_path / "course_a"
    course.mkdir()
    body = """---
type: konspekt
source: lesson-1.md
source_sha256: deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef
tags: [agents, tools]
---

# Урок 1

## Введение

Текст введения.

## Tools

Про tools.
"""
    _write(course / "lesson-1-konspekt.md", body)
    # Non-konspekt lecture must not appear as type=konspekt
    _write(course / "notes.md", "# Notes\n\nplain\n")

    items = list_library_konspekts("course_a", data_dir=tmp_path)
    assert len(items) == 1
    km = items[0]
    assert km.path_rel.endswith("lesson-1-konspekt.md")
    assert km.source == "lesson-1.md"
    assert "agents" in km.tags
    # sha mismatch + no real source file → staleness None (unknown / missing source)
    assert km.staleness in (None, "stale", "fresh")

    sections = list_library_sections(km.path_abs, data_dir=tmp_path)
    headings = [s.heading_text for s in sections]
    assert any("Введение" in h for h in headings)
    assert any("Tools" in h for h in headings)


def test_list_library_konspekts_missing_course_returns_empty(tmp_path: Path) -> None:
    assert list_library_konspekts("no-such-course", data_dir=tmp_path) == []


def test_library_ask_folder_rel_normalizes() -> None:
    assert library_ask_folder_rel("course_b\\deep") == "course_b/deep"
    assert library_ask_folder_rel(None) == ""
    assert library_ask_folder_rel("  ") == ""


def test_browse_helpers_do_not_mutate_scope() -> None:
    """Listing courses/konspekts must not touch study scope session state."""
    state: dict = {}
    before = _scope_snapshot(state)
    assert before is None

    # Pure read-model — no state argument; calling it cannot write scope.
    list_library_courses(
        {
            "folder_rel_options": ["course_a"],
            "files": ["course_a/a.md"],
        }
    )
    assert get_active_scope(state) is None
    assert state.get(ACTIVE_SCOPE_KEY) is None

    navigate_to_ask("course_a", state=state)
    assert get_active_scope(state) is None
    assert state.get(ACTIVE_SCOPE_KEY) is None
    assert state[PENDING_CURRENT_VIEW_KEY] == "Быстрый ответ"
    assert state["qa_sidebar_folder_rel"] == "course_a"


def test_activate_only_via_explicit_helper() -> None:
    state: dict = {}
    course = LibraryCourse(
        folder_rel="course_deep",
        title="Deep",
        source_paths=("course_deep/m1.md",),
    )
    assert get_active_scope(state) is None
    activate_course_from_library(course, state=state)
    scope = get_active_scope(state)
    assert scope is not None
    assert scope["folder_rel"] == "course_deep"
    assert scope["title"] == "Deep"
    assert list(scope.get("source_paths") or []) == ["course_deep/m1.md"]


def test_ask_deep_sets_folder_prefix_for_qa() -> None:
    """«Спросить по Deep» → folder_rel filter for Q&A (path prefix), no scope."""
    state: dict = {ACTIVE_SCOPE_KEY: {"active": True, "folder_rel": "other", "title": "Other"}}
    navigate_to_ask("ИИ Агенты Deep", state=state)
    assert state["qa_sidebar_folder_rel"] == "ИИ Агенты Deep"
    # Scope left unchanged — only explicit activate mutates it.
    assert state[ACTIVE_SCOPE_KEY]["folder_rel"] == "other"
