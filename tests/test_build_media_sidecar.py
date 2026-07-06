"""Тесты сборщика media-sidecar: авто-wire frontmatter и метрики покрытия.

``_ensure_frontmatter_pointer`` мутирует .md пользователя — самый рисковый код
пайплайна, поэтому покрыт отдельно: идемпотентность, сохранение CRLF/LF,
обновление устаревшего указателя, вставка при отсутствии блока. Критичный кейс:
писатель обязан работать в том же frontmatter-scope, что и читатель приложения
(``app.media_sidecar.read_media_sidecar_pointer``) — ``media_sidecar:`` в теле
конспекта (документация/пример о фиче) не считается указателем и не переписывается,
иначе «wired» лжёт, а читатель sidecar не найдёт.
"""

from __future__ import annotations

from types import SimpleNamespace

import scripts.build_media_sidecar as bms


# ── _coverage_metrics ──────────────────────────────────────────────────


def _pair(anchored: bool, t0: float | None, t1: float | None, conf: float):
    """Параллельные (section-dict, aligned-like) для _coverage_metrics."""
    sec: dict = {"confidence": conf}
    if t0 is not None:
        sec["t_start"] = t0
    if t1 is not None:
        sec["t_end"] = t1
    return sec, SimpleNamespace(anchored=anchored, t_start=t0)


def _metrics(specs, media_duration=None):
    secs, aligned = [], []
    for sec, al in specs:
        secs.append(sec)
        aligned.append(al)
    return bms._coverage_metrics({"sections": secs}, aligned, media_duration)


def test_coverage_metrics_counts_and_playlist():
    specs = [
        _pair(anchored=True, t0=0.0, t1=60.0, conf=0.90),    # confident, +60 c
        _pair(anchored=True, t0=60.0, t1=90.0, conf=0.72),   # confident, +30 c
        _pair(anchored=True, t0=90.0, t1=120.0, conf=0.65),  # реальный якорь, <0.70
        _pair(anchored=False, t0=120.0, t1=None, conf=0.40),  # интерполяция
        _pair(anchored=False, t0=None, t1=None, conf=0.0),   # край без таймкода
    ]
    m = _metrics(specs, media_duration=600.0)
    assert m["sections"] == 5
    assert m["with_timestamp"] == 4
    assert m["anchored"] == 3
    assert m["interpolated"] == 1
    assert m["no_timestamp"] == 1
    assert m["confident"] == 2
    assert m["playlist_seconds"] == 90.0  # 60 + 30 — только confident-фрагменты
    assert m["media_seconds"] == 600.0


def test_coverage_metrics_null_media_duration():
    m = _metrics([_pair(True, 0.0, 10.0, 0.9)], media_duration=None)
    assert m["media_seconds"] is None
    assert m["playlist_seconds"] == 10.0


# ── _ensure_frontmatter_pointer ────────────────────────────────────────


def _wire(monkeypatch, rel="k.media.json"):
    # data_relative_from_path не нужен для логики wire — изолируемся от DATA_DIR.
    monkeypatch.setattr(bms, "data_relative_from_path", lambda _p: rel)


def test_pointer_inserts_block_when_absent(tmp_path, monkeypatch):
    _wire(monkeypatch)
    md = tmp_path / "k.md"
    md.write_text("# Заголовок\n\nТекст лекции.\n", encoding="utf-8")

    changed, msg = bms._ensure_frontmatter_pointer(md, tmp_path / "k.media.json")
    assert changed and "Добавлен" in msg

    text = md.read_text(encoding="utf-8")
    assert text.startswith("---\nmedia_sidecar: k.media.json\n---\n")
    assert "# Заголовок" in text  # тело не пострадало

    changed2, _ = bms._ensure_frontmatter_pointer(md, tmp_path / "k.media.json")
    assert not changed2  # идемпотент


def test_pointer_inserts_into_existing_block(tmp_path, monkeypatch):
    _wire(monkeypatch)
    md = tmp_path / "k.md"
    md.write_text("---\ntitle: Лекция\n---\n\nТело.\n", encoding="utf-8")

    changed, msg = bms._ensure_frontmatter_pointer(md, tmp_path / "k.media.json")
    assert changed and "Добавлен" in msg

    text = md.read_text(encoding="utf-8")
    assert text.startswith("---\nmedia_sidecar: k.media.json\ntitle: Лекция\n---\n")
    assert "Тело." in text


def test_pointer_updates_stale_path(tmp_path, monkeypatch):
    _wire(monkeypatch)
    md = tmp_path / "k.md"
    md.write_text("---\nmedia_sidecar: old.media.json\ntitle: x\n---\n\nbody\n", encoding="utf-8")

    changed, msg = bms._ensure_frontmatter_pointer(md, tmp_path / "k.media.json")
    assert changed and "Обновлён" in msg and "old.media.json" in msg

    text = md.read_text(encoding="utf-8")
    assert "media_sidecar: k.media.json" in text
    assert "old.media.json" not in text

    changed2, _ = bms._ensure_frontmatter_pointer(md, tmp_path / "k.media.json")
    assert not changed2


def test_pointer_does_not_touch_body_line_when_no_block(tmp_path, monkeypatch):
    """Регресс аудита: media_sidecar: в теле — НЕ указатель. Без frontmatter-блока
    писатель создаёт блок поверх файла, а строку-ловушку в теле оставляет как есть."""
    _wire(monkeypatch)
    md = tmp_path / "k.md"
    md.write_text("# Лекция\n\nПример frontmatter:\nmedia_sidecar: trap.media.json\n", encoding="utf-8")

    changed, _ = bms._ensure_frontmatter_pointer(md, tmp_path / "k.media.json")
    assert changed

    text = md.read_text(encoding="utf-8")
    assert text.startswith("---\nmedia_sidecar: k.media.json\n---\n")
    assert "media_sidecar: trap.media.json" in text  # тело не тронуто


def test_pointer_does_not_touch_body_line_when_block_exists(tmp_path, monkeypatch):
    """Блок есть, указателя в нём нет, но media_sidecar: есть в теле: вставляем в блок,
    тело не переписываем."""
    _wire(monkeypatch)
    md = tmp_path / "k.md"
    md.write_text("---\ntitle: x\n---\n\nmedia_sidecar: trap.media.json\n", encoding="utf-8")

    changed, msg = bms._ensure_frontmatter_pointer(md, tmp_path / "k.media.json")
    assert changed and "Добавлен" in msg

    text = md.read_text(encoding="utf-8")
    assert text.startswith("---\nmedia_sidecar: k.media.json\ntitle: x\n---\n")
    assert "media_sidecar: trap.media.json" in text


def test_pointer_preserves_crlf(tmp_path, monkeypatch):
    _wire(monkeypatch)
    md = tmp_path / "k.md"
    md.write_bytes(b"---\r\ntitle: x\r\n---\r\n\r\n# Body\r\n")

    bms._ensure_frontmatter_pointer(md, tmp_path / "k.media.json")

    text = md.read_bytes().decode("utf-8")
    # все переводы строк остались CRLF (каждый \n предварён \r)
    assert text.count("\r\n") == text.count("\n")
    assert "media_sidecar: k.media.json" in text


def test_pointer_preserves_lf(tmp_path, monkeypatch):
    _wire(monkeypatch)
    md = tmp_path / "k.md"
    md.write_bytes(b"---\ntitle: x\n---\n\n# Body\n")

    bms._ensure_frontmatter_pointer(md, tmp_path / "k.media.json")

    text = md.read_bytes().decode("utf-8")
    assert "\r" not in text  # CRLF не внесён
    assert "media_sidecar: k.media.json" in text
