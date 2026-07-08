import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from app import obsidian_export
from app.living_konspekt_source_resolver import resolve_source_section

_MODULE = sys.modules[__name__]

# Isolated from the real DATA_DIR: these tests used to write fixtures directly
# into the configured production data directory (leaking `_test_living_konspekt_
# source_resolver/` into the real corpus and knowledge-graph ingestion).
ROOT: Path
SRC: Path
MD: Path


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch):
    # `vault_root()` derives from ``DATA_DIR.parent / "data"`` — keep that
    # coincidence intact so source and konspekt md resolve to the same tree.
    home = Path(tempfile.mkdtemp(prefix="hometutor_test_source_resolver_"))
    base = home / "data"
    base.mkdir()
    monkeypatch.setattr(obsidian_export, "DATA_DIR", base)
    monkeypatch.setattr(_MODULE, "ROOT", base / "_test_living_konspekt_source_resolver", raising=False)
    monkeypatch.setattr(_MODULE, "SRC", base / "_test_living_konspekt_source_resolver" / "lesson.txt", raising=False)
    monkeypatch.setattr(_MODULE, "MD", base / "_test_living_konspekt_source_resolver" / "lesson.md", raising=False)
    try:
        yield base
    finally:
        shutil.rmtree(home, ignore_errors=True)


def _write_pair(markdown: str) -> str:
    ROOT.mkdir(parents=True, exist_ok=True)
    SRC.write_text("source", encoding="utf-8")
    MD.write_text(markdown, encoding="utf-8")
    return "_test_living_konspekt_source_resolver/lesson.txt"


def test_resolves_high_confidence_source_to_single_section() -> None:
    rel = _write_pair(
        "# Lesson\n\n"
        "## Инструменты агента\n\n"
        "Функции, schema, вызовы инструментов и валидация параметров.\n\n"
        "## Память агента\n\n"
        "Контекст, заметки и долговременное состояние.\n"
    )

    result = resolve_source_section({"relative_path": rel, "text": "schema вызовы инструментов параметры"})

    assert result.status == "single"
    assert result.single is not None
    assert result.single.section.heading_text == "Инструменты агента"


def test_duplicate_heading_requires_candidate_choice() -> None:
    rel = _write_pair(
        "# Lesson\n\n"
        "## Архитектура\n\n"
        "Компоненты и адаптеры.\n\n"
        "## Архитектура\n\n"
        "Runtime слой и сервисы.\n"
    )

    result = resolve_source_section({"relative_path": rel, "text": "runtime сервисы"})

    assert result.status == "choose"
    assert result.candidates


def test_weak_match_falls_back_to_manual_candidates() -> None:
    rel = _write_pair(
        "# Lesson\n\n"
        "## Семплирование\n\n"
        "Температура и top-p.\n\n"
        "## Индексация\n\n"
        "Чанки и embeddings.\n"
    )

    result = resolve_source_section({"relative_path": rel, "text": "совсем другое слово"})

    assert result.status == "choose"
    assert [candidate.section.heading_text for candidate in result.candidates] == ["Семплирование", "Индексация"]


def test_missing_konspekt_is_unavailable(tmp_path: Path) -> None:
    source = tmp_path / "plain.txt"
    source.write_text("plain", encoding="utf-8")

    result = resolve_source_section({"relative_path": str(source), "text": "plain"})

    assert result.status == "unavailable"
