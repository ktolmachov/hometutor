"""Tests for material plan C1 — konspekt source_sha256 staleness."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from app.konspekt_discovery import (
    KonspektMeta,
    konspekt_source_staleness,
    konspekt_stale_badge_label,
    resolve_konspekt_source_path,
)


def _obsidian_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _meta(path: Path, source: str, sha: str | None) -> KonspektMeta:
    return KonspektMeta(
        path=path,
        source=source,
        presentation=None,
        generated=None,
        tags=(),
        source_sha256=sha,
    )


def test_resolve_source_path_prefers_source_rel(tmp_path: Path) -> None:
    data = tmp_path / "data"
    course = data / "demo"
    course.mkdir(parents=True)
    src = course / "lecture.md"
    src.write_text("# L\n", encoding="utf-8")
    k = course / "lecture.konspekt.md"
    k.write_text("---\ntype: konspekt\nsource: lecture.md\n---\n", encoding="utf-8")
    km = _meta(k, "lecture.md", None)
    assert resolve_konspekt_source_path(km, source_rel="demo/lecture.md", data_dir=data) == src


def test_fresh_when_obsidian_hash_matches(tmp_path: Path) -> None:
    data = tmp_path / "data"
    course = data / "demo"
    course.mkdir(parents=True)
    src = course / "a.md"
    src.write_text("Hello lecture body\n", encoding="utf-8", newline="\n")
    # Hash what is actually on disk (Windows may normalize newlines if not forced).
    sha = _obsidian_hash(src.read_text(encoding="utf-8"))
    k = course / "a.konspekt.md"
    k.write_text(
        f"---\ntype: konspekt\nsource: a.md\nsource_sha256: {sha}\n---\n# K\n",
        encoding="utf-8",
        newline="\n",
    )
    km = _meta(k, "a.md", sha)
    assert konspekt_source_staleness(km, source_rel="demo/a.md", data_dir=data) == "fresh"
    assert konspekt_stale_badge_label(km, source_rel="demo/a.md", data_dir=data) is None


def test_stale_when_source_edited_after_konspekt(tmp_path: Path) -> None:
    data = tmp_path / "data"
    course = data / "demo"
    course.mkdir(parents=True)
    src = course / "a.md"
    src.write_text("Original\n", encoding="utf-8", newline="\n")
    sha = _obsidian_hash(src.read_text(encoding="utf-8"))
    k = course / "a.konspekt.md"
    k.write_text(
        f"---\ntype: konspekt\nsource: a.md\nsource_sha256: {sha}\n---\n# K\n",
        encoding="utf-8",
        newline="\n",
    )
    # Ensure konspekt mtime is older than the upcoming source edit.
    past = time.time() - 10
    import os

    os.utime(k, (past, past))
    src.write_text("Edited lecture\n", encoding="utf-8", newline="\n")
    km = _meta(k, "a.md", sha)
    assert konspekt_source_staleness(km, source_rel="demo/a.md", data_dir=data) == "stale"
    assert konspekt_stale_badge_label(km, source_rel="demo/a.md", data_dir=data) == "🕰 устарел"


def test_unknown_when_no_hash_or_ambiguous_multiinput(tmp_path: Path) -> None:
    data = tmp_path / "data"
    course = data / "demo"
    course.mkdir(parents=True)
    src = course / "a.md"
    src.write_text("x\n", encoding="utf-8")
    k = course / "a.konspekt.md"
    k.write_text("---\ntype: konspekt\nsource: a.md\n---\n", encoding="utf-8")
    # No hash → None
    assert konspekt_source_staleness(_meta(k, "a.md", None), source_rel="demo/a.md", data_dir=data) is None
    # Fake multi-input hash (won't match variants) + source not newer → unknown/None
    fake = "ab" * 32
    # konspekt newer than source
    past = time.time() - 10
    import os

    os.utime(src, (past, past))
    assert (
        konspekt_source_staleness(_meta(k, "a.md", fake), source_rel="demo/a.md", data_dir=data)
        is None
    )
