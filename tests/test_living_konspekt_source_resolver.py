from pathlib import Path

from app.config import DATA_DIR
from app.living_konspekt_source_resolver import resolve_source_section


ROOT = DATA_DIR / "_test_living_konspekt_source_resolver"
SRC = ROOT / "lesson.txt"
MD = ROOT / "lesson.md"


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
