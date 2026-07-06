"""Дрейф строк корзины и медиа-таймкоды в сохранённом артефакте Живого конспекта."""

from __future__ import annotations

from pathlib import Path

from app.media_sidecar import (
    GeneratedBy,
    LocalVideoSource,
    MediaSection,
    MediaSidecar,
    UrlVideoSource,
    sha256_file,
)
from app import workbench_service
from app.section_index import section_to_row
from app.ui.living_konspekt_add_panel import sections_of_document
from app.ui.living_konspekt_view import (
    _media_line_for_row,
    _row_stale_status,
    _sources_footer,
    _stitch_verbatim,
    _videos_block,
    media_caption_line,
    move_section_in_workbench,
)

_KONSPEKT = """# Тестовый конспект

## Тема про инференс

Инференс токены логиты температура семплирование контекст модель вероятность распределение выбор.

## Тема про инструменты

Инструменты вызов контракт схема параметры валидация исполнение рантайм намерение действие.
"""


def _rows_from_file(md: Path) -> list[dict]:
    return [section_to_row(s) for s in sections_of_document(md)]


def test_row_stale_status_fresh_file_is_clean(tmp_path):
    md = tmp_path / "konspekt.md"
    md.write_text(_KONSPEKT, encoding="utf-8")
    rows = _rows_from_file(md)
    assert rows, "нужны разделы для теста"
    assert all(_row_stale_status(row) is None for row in rows)


def test_row_stale_status_detects_missing_file(tmp_path):
    md = tmp_path / "konspekt.md"
    md.write_text(_KONSPEKT, encoding="utf-8")
    rows = _rows_from_file(md)
    md.unlink()
    status = _row_stale_status(rows[0])
    assert status is not None and "не найден" in status


def test_row_stale_status_detects_content_drift(tmp_path):
    md = tmp_path / "konspekt.md"
    md.write_text(_KONSPEKT, encoding="utf-8")
    rows = _rows_from_file(md)
    md.write_text(_KONSPEKT.replace("температура", "энтропия"), encoding="utf-8")
    status = _row_stale_status(rows[0])
    assert status is not None and "изменился" in status


def test_row_stale_status_detects_line_shift(tmp_path):
    md = tmp_path / "konspekt.md"
    md.write_text(_KONSPEKT, encoding="utf-8")
    rows = _rows_from_file(md)
    # Вставка текста выше сдвигает строки, контент разделов не меняется.
    md.write_text("Новый вводный абзац.\n\n" + _KONSPEKT, encoding="utf-8")
    status = _row_stale_status(rows[0])
    assert status is not None and "переехал" in status


def test_non_portable_row_uses_labels_for_staleness_stitch_and_sources():
    row = {
        "row_key": "np:test",
        "portability_status": "non_portable",
        "resolve_error": "outside_data_dir",
        "konspekt_md_abs": "",
        "source_abs": "",
        "konspekt_md_label": "legacy.md",
        "source_label": "legacy.txt",
        "heading_text": "Тема",
        "slug": "tema",
        "level": 2,
        "line_start": 7,
        "line_end": 9,
        "text": "Снимок текста.",
        "own_text": "Снимок текста.",
        "concept": None,
        "note": None,
        "read_at": None,
    }

    assert "непереносимый снимок" in (_row_stale_status(row) or "")
    assert "legacy.md:7" in _stitch_verbatim([row])
    assert "legacy.md:7-9" in _sources_footer([row])


def test_media_caption_line_variants():
    assert media_caption_line(None, None, "Видео") is None
    plain = media_caption_line(754, 1082, "Урок 2")
    assert plain == "*🎬 Урок 2 · 12:34–18:02*"
    linked = media_caption_line(90, None, "Лекция", "https://www.youtube.com/watch?v=abc&t=90s")
    assert linked == "*🎬 [Лекция · 1:30](https://www.youtube.com/watch?v=abc&t=90s)*"
    assert "видео" in (media_caption_line(5, None, "  ") or "")


def _sidecar_for_row(row: dict, konspekt_sha: str, *, confidence: float) -> MediaSidecar:
    section = MediaSection(
        section_id="sha256:" + "c" * 64,
        section_slug=str(row["slug"]),
        heading=str(row["heading_text"]),
        line_start=int(row["line_start"]),
        line_end=int(row["line_end"]),
        confidence=confidence,
        t_start=90.0,
        t_end=150.0,
    )
    return MediaSidecar(
        schema_version=1,
        konspekt_sha256=konspekt_sha,
        generated_by=GeneratedBy(tool="test", created_at="2026-07-06T00:00:00Z"),
        video=UrlVideoSource(url="https://www.youtube.com/watch?v=abc123def", title="Лекция"),
        sections=(section,),
    )


def test_media_line_suppressed_for_stale_and_low_confidence(tmp_path):
    """Артефакт не должен доверять таймкоду больше, чем UI (P1 аудита)."""
    md = tmp_path / "konspekt.md"
    md.write_text(_KONSPEKT, encoding="utf-8")
    row = _rows_from_file(md)[0]
    fresh_sha = sha256_file(md)

    trusted = _media_line_for_row(row, {str(md): _sidecar_for_row(row, fresh_sha, confidence=0.9)})
    assert trusted is not None and "1:30" in trusted and "t=90s" in trusted

    low_conf = _media_line_for_row(row, {str(md): _sidecar_for_row(row, fresh_sha, confidence=0.4)})
    assert low_conf is None, "low-confidence таймкод не должен попадать в файл"

    stale = _media_line_for_row(row, {str(md): _sidecar_for_row(row, "b" * 64, confidence=0.9)})
    assert stale is None, "stale sidecar (konspekt изменился) не должен давать таймкод"


def test_playlist_items_use_trusted_timestamps_in_workbench_order(tmp_path, monkeypatch):
    import app.ui.living_konspekt_media as media

    md = tmp_path / "konspekt.md"
    md.write_text(_KONSPEKT, encoding="utf-8")
    rows = _rows_from_file(md)
    sidecar = _sidecar_for_row(rows[0], sha256_file(md), confidence=0.9)
    monkeypatch.setattr(media, "load_media_sidecar_for_konspekt", lambda path: sidecar)

    items = media.playlist_items_from_rows(rows[:1])

    assert items[0]["heading"] == rows[0]["heading_text"]
    assert items[0]["start"] == 90
    assert items[0]["duration"] == 60
    assert str(items[0]["url"]).endswith("t=90s")


def test_stale_check_runs_once_per_document_not_per_row(tmp_path, monkeypatch):
    """P2 аудита: staleness хэширует konspekt и видео — не должен зваться на каждый раздел."""
    import app.ui.living_konspekt_view as view

    md = tmp_path / "konspekt.md"
    md.write_text(_KONSPEKT, encoding="utf-8")
    rows = _rows_from_file(md)
    assert len(rows) >= 2
    sidecar = _sidecar_for_row(rows[0], sha256_file(md), confidence=0.9)

    calls: list[str] = []

    def _counting_stale(sc, md_abs):
        calls.append(md_abs)
        return []

    monkeypatch.setattr(view, "_sidecar_stale_reasons", _counting_stale)
    sidecar_cache = {str(md): sidecar}
    stale_cache: dict[str, list[str]] = {}
    for row in rows:
        view._media_line_for_row(row, sidecar_cache, stale_cache)

    assert len(calls) == 1, f"staleness должен считаться один раз на документ, было {len(calls)}"


def test_videos_block_lists_all_sources_with_dedup():
    """Вторичные media.videos[] не теряются при сохранении (P2 аудита)."""
    primary = LocalVideoSource(path="курс/урок_2.mp4", sha256="a" * 64, title="Урок 2")
    talk = UrlVideoSource(url="https://www.youtube.com/watch?v=talk123", title="Доклад Anthropic")
    sidecar = MediaSidecar(
        schema_version=1,
        konspekt_sha256="a" * 64,
        generated_by=GeneratedBy(tool="test", created_at="2026-07-06T00:00:00Z"),
        video=primary,
        sections=(),
        videos=(primary, talk),
    )
    block = _videos_block({"doc.md": sidecar, "doc2.md": sidecar})  # dedup между документами
    assert block.startswith("## 🎬 Видео материалов")
    assert block.count("Урок 2") == 1
    assert "[Доклад Anthropic](https://www.youtube.com/watch?v=talk123)" in block
    assert _videos_block({"doc.md": None}) == ""


def test_move_section_reorders_and_persists_bounds(tmp_path):
    md = tmp_path / "konspekt.md"
    md.write_text(_KONSPEKT, encoding="utf-8")
    rows = _rows_from_file(md)
    runtime_rows = workbench_service.normalize_runtime_rows(list(rows))
    state: dict = {"workbench_sections": runtime_rows}

    first_key = runtime_rows[0]["row_key"]
    assert move_section_in_workbench(first_key, 1, state) is True
    reordered = state["workbench_sections"]
    assert reordered[1]["row_key"] == first_key

    # Выход за границы — no-op.
    last = reordered[-1]
    assert move_section_in_workbench(last["row_key"], 1, state) is False
    assert move_section_in_workbench("нет-такого-row", 1, state) is False
