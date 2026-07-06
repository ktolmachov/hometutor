"""Матчинг раздела корзины с media-sidecar: section_id переживает сдвиг строк."""

from __future__ import annotations

from app.media_alignment import compute_section_id
from app.media_sidecar import MediaSection, parse_media_sidecar
from app.section_index import ParsedSection
from app.ui.living_konspekt_view import _media_section_for_row


def _row(heading: str, own_text: str, line_start: int) -> dict:
    return {
        "source_abs": "x",
        "konspekt_md_abs": "x",
        "heading_text": heading,
        "slug": heading.lower().replace(" ", "-"),
        "level": 2,
        "line_start": line_start,
        "line_end": line_start + 8,
        "text": own_text,
        "own_text": own_text,
        "concept": "",
    }


def _sidecar_with_section(section_id: str, slug: str, heading: str, line_start: int):
    payload = {
        "schema_version": 1,
        "konspekt_sha256": "a" * 64,
        "generated_by": {"tool": "test", "created_at": "2026-07-06T00:00:00Z"},
        "media": {
            "video": {"kind": "url", "url": "https://www.youtube.com/watch?v=abc123def"},
        },
        "sections": [
            {
                "section_id": section_id,
                "section_slug": slug,
                "heading": heading,
                "line_start": line_start,
                "line_end": line_start + 8,
                "confidence": 0.9,
                "t_start": 120.0,
            }
        ],
    }
    return parse_media_sidecar(payload)


def test_row_matches_by_section_id_after_line_shift():
    heading = "Тема про инференс и токены"
    own_text = "инференс токены логиты температура семплирование контекст модель вероятность"
    section = ParsedSection(
        heading_text=heading,
        slug="тема-про-инференс-и-токены",
        level=2,
        line_start=10,
        line_end=18,
        text=own_text,
        own_text=own_text,
    )
    sidecar = _sidecar_with_section(compute_section_id(section), section.slug, heading, line_start=10)

    # Конспект отредактировали выше по файлу: строки съехали на 40, slug/heading те же.
    row = _row(heading, own_text, line_start=50)

    matched = _media_section_for_row(sidecar, row)
    assert isinstance(matched, MediaSection)
    assert matched.t_start == 120.0


def test_sidecar_stale_when_asr_params_change():
    payload = {
        "schema_version": 1,
        "konspekt_sha256": "a" * 64,
        "generated_by": {
            "tool": "scripts/build_media_sidecar.py",
            "created_at": "2026-07-06T00:00:00Z",
            "asr_model": "large-v3",
            "asr_params": {"model": "large-v3", "beam_size": 5, "language_requested": "auto"},
        },
        "media": {"video": {"kind": "url", "url": "https://www.youtube.com/watch?v=abc123def"}},
        "sections": [],
    }
    sidecar = parse_media_sidecar(payload)

    same = {"model": "large-v3", "beam_size": 5, "language_requested": "auto"}
    changed = {"model": "large-v3", "beam_size": 1, "language_requested": "ru"}

    assert sidecar.stale_reasons(asr_params=same) == []
    assert "asr_params" in sidecar.stale_reasons(asr_params=changed)


def test_expected_asr_params_read_from_segments_sidecar_file(tmp_path):
    import json

    from app.ui.living_konspekt_view import _expected_asr_params

    video = tmp_path / "lecture.mp4"
    video.write_bytes(b"fake")
    assert _expected_asr_params(video) is None, "нет segments.json → нет ожиданий"

    params = {"model": "large-v3", "beam_size": 5, "language_requested": "auto"}
    (tmp_path / "lecture.segments.json").write_text(
        json.dumps({"schema_version": 1, "asr": {"params": params}, "segments": []}),
        encoding="utf-8",
    )
    assert _expected_asr_params(video) == params

    (tmp_path / "lecture.segments.json").write_text("{broken", encoding="utf-8")
    assert _expected_asr_params(video) is None, "битый файл → мягкая деградация, не падение"


def test_row_falls_back_to_positional_match_without_own_text():
    heading = "Раздел без текста"
    sidecar = _sidecar_with_section("sha256:" + "b" * 64, "раздел-без-текста", heading, line_start=7)
    row = _row(heading, "", line_start=7)
    row["own_text"] = ""
    row["text"] = ""

    matched = _media_section_for_row(sidecar, row)
    assert matched is not None
    assert matched.heading == heading
