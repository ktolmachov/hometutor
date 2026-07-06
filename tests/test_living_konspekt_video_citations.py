import json

from app.config import DATA_DIR
from app.living_konspekt_source_resolver import resolve_source_section
from app.living_konspekt_video_citations import (
    resolve_source_video_citation,
    video_citation_for_candidate,
)
from app.media_alignment import compute_section_id
from app.media_sidecar import sha256_file


ROOT = DATA_DIR / "_test_living_konspekt_video_citations"
SRC = ROOT / "lesson.txt"
MD = ROOT / "lesson.md"
SIDECAR = ROOT / "lesson.media.json"
REL = "_test_living_konspekt_video_citations/lesson.txt"
SIDECAR_REL = "_test_living_konspekt_video_citations/lesson.media.json"


def _write_pair(markdown_body: str) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    SRC.write_text("source", encoding="utf-8")
    MD.write_text(f"---\nmedia_sidecar: {SIDECAR_REL}\n---\n\n{markdown_body}", encoding="utf-8")


def _candidate(query: str):
    result = resolve_source_section({"relative_path": REL, "text": query})
    assert result.single is not None
    return result.single


def _write_sidecar(candidate, *, confidence: float = 0.9, konspekt_sha: str | None = None) -> None:
    section = candidate.section
    payload = {
        "schema_version": 1,
        "konspekt_sha256": konspekt_sha or sha256_file(MD),
        "generated_by": {"tool": "test", "created_at": "2026-07-06T00:00:00Z"},
        "media": {
            "video": {
                "kind": "url",
                "url": "https://www.youtube.com/watch?v=abc123def",
                "title": "Лекция про инструменты",
            }
        },
        "sections": [
            {
                "section_id": compute_section_id(section),
                "section_slug": section.slug,
                "heading": section.heading_text,
                "line_start": section.line_start,
                "line_end": section.line_end,
                "confidence": confidence,
                "t_start": 90.0,
                "t_end": 150.0,
            }
        ],
    }
    SIDECAR.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_video_citation_available_for_trusted_source_section() -> None:
    _write_pair(
        "# Lesson\n\n"
        "## Инструменты агента\n\n"
        "Функции, schema, вызовы инструментов и валидация параметров.\n"
    )
    candidate = _candidate("schema вызовы инструментов параметры")
    _write_sidecar(candidate)

    result = video_citation_for_candidate(candidate)

    assert result.status == "available"
    assert result.citation is not None
    assert result.citation.timestamp_label == "1:30"
    assert result.citation.url is not None
    assert result.citation.url.endswith("t=90s")


def test_video_citation_suppressed_for_low_confidence_timestamp() -> None:
    _write_pair(
        "# Lesson\n\n"
        "## Инструменты агента\n\n"
        "Функции, schema, вызовы инструментов и валидация параметров.\n"
    )
    candidate = _candidate("schema вызовы инструментов параметры")
    _write_sidecar(candidate, confidence=0.4)

    result = video_citation_for_candidate(candidate)

    assert result.status == "unavailable"
    assert "confidence" in result.message


def test_video_citation_suppressed_for_stale_sidecar() -> None:
    _write_pair(
        "# Lesson\n\n"
        "## Инструменты агента\n\n"
        "Функции, schema, вызовы инструментов и валидация параметров.\n"
    )
    candidate = _candidate("schema вызовы инструментов параметры")
    _write_sidecar(candidate, konspekt_sha="b" * 64)

    result = video_citation_for_candidate(candidate)

    assert result.status == "unavailable"
    assert "konspekt_sha256" in result.message


def test_source_video_citation_requires_unambiguous_section() -> None:
    _write_pair(
        "# Lesson\n\n"
        "## Архитектура\n\n"
        "Компоненты и адаптеры.\n\n"
        "## Архитектура\n\n"
        "Runtime слой и сервисы.\n"
    )

    result = resolve_source_video_citation({"relative_path": REL, "text": "runtime сервисы"})

    assert result.status == "unavailable"
    assert "уверенного сопоставления" in result.message
