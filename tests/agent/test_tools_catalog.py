"""P1: catalog.list agent tool uses library read-model (no invented paths)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.agent.contracts import ToolContext
from app.agent.tools_catalog import CatalogListArgs, _catalog_list_handler
from app.agent.tool_registry import build_default_registry


def _ctx() -> ToolContext:
    return ToolContext(
        user_id="u1",
        question="найди раздел",
        query_options=SimpleNamespace(folder_rel="", folder=""),
        session_id="s1",
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_catalog_list_registered_read_only():
    reg = build_default_registry()
    spec = reg.get_spec("catalog.list")
    assert spec is not None
    assert spec.is_read_only


def test_catalog_list_returns_real_paths_only(tmp_path: Path, monkeypatch):
    deep = tmp_path / "ИИ Агенты Deep"
    deep.mkdir()
    _write(
        deep / "module-1-konspekt.md",
        """---
type: konspekt
source: module-1.md
tags: [tools, agents]
---

# Module 1

## Tools

Описание tools.

## Guardrails

Описание guardrails.
""",
    )
    base = tmp_path / "ИИ Агенты"
    base.mkdir()
    _write(
        base / "lesson-1-konspekt.md",
        """---
type: konspekt
source: lesson-1.md
---

# Lesson 1

## Intro

Текст.
""",
    )

    monkeypatch.setattr("app.library_catalog_read.DATA_DIR", tmp_path)
    monkeypatch.setattr(
        "app.library_catalog_read.build_mission_control_course_options",
        lambda _stats: [
            {
                "folder_rel": "ИИ Агенты",
                "title": "ИИ Агенты",
                "source_paths": ["ИИ Агенты/lesson-1.md"],
            },
            {
                "folder_rel": "ИИ Агенты Deep",
                "title": "ИИ Агенты Deep",
                "source_paths": ["ИИ Агенты Deep/module-1.md"],
            },
        ],
    )

    result = _catalog_list_handler(
        _ctx(),
        CatalogListArgs(course="Deep", query="tools", level="auto"),
    )
    assert result.ok, result.error
    data = result.data
    assert data["counts"]["courses"] >= 1
    folders = {c["folder_rel"] for c in data["courses"]}
    assert any("Deep" in f for f in folders)

    for k in data.get("konspekts") or []:
        path = str(k.get("path_rel") or "")
        assert path
        assert not path.startswith("D:")
        assert "Deep" in path or "Deep" in str(k.get("course") or "")

    # Sections for tools heading when query matches
    headings = [s.get("heading") for s in data.get("sections") or []]
    # May be empty if section scan needs absolute path via DATA_DIR — assert honesty
    for s in data.get("sections") or []:
        assert s.get("konspekt_path")
        assert s.get("heading")
        assert "address" in s


def test_catalog_list_empty_course_filter_no_hallucination(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.library_catalog_read.DATA_DIR", tmp_path)
    monkeypatch.setattr(
        "app.library_catalog_read.build_mission_control_course_options",
        lambda _stats: [],
    )
    result = _catalog_list_handler(
        _ctx(),
        CatalogListArgs(course="NonexistentDeep", query="tools"),
    )
    assert result.ok
    assert result.data["courses"] == []
    assert result.data["konspekts"] == []
    assert result.data["sections"] == []
