"""Narrow targeted tests for audio sibling discovery (wave-audio-01).

Covers the convention used by living_konspekt_media for st.audio without
touching media_sidecar schema or requiring real video files in DATA_DIR.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.media_audio import audio_for_local_video, find_audio_sibling
from app.media_sidecar import LocalVideoSource


def _make_local_video(rel_path: str) -> LocalVideoSource:
    return LocalVideoSource(
        path=rel_path,
        sha256="a" * 64,
        title="test video",
    )


def test_find_audio_sibling_returns_none_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app.path_safety as path_safety

    base = tmp_path / "data"
    base.mkdir()
    monkeypatch.setattr(path_safety, "DATA_DIR", base)

    video_rel = "courses/lec/video.mp4"
    (base / "courses" / "lec").mkdir(parents=True)
    (base / "courses" / "lec" / "video.mp4").touch()

    # no .m4a sibling
    assert find_audio_sibling(video_rel) is None
    assert find_audio_sibling("courses/lec/video.mp4") is None


def test_find_audio_sibling_finds_sibling_m4a(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app.path_safety as path_safety

    base = tmp_path / "data"
    base.mkdir()
    monkeypatch.setattr(path_safety, "DATA_DIR", base)

    lec_dir = base / "courses" / "lec"
    lec_dir.mkdir(parents=True)
    (lec_dir / "video.mp4").touch()
    m4a = lec_dir / "video.m4a"
    m4a.write_bytes(b"fake m4a content for test")

    found = find_audio_sibling("courses/lec/video.mp4")
    assert found is not None
    assert found.name == "video.m4a"
    assert found.is_file()

    # absolute also works
    abs_found = find_audio_sibling(lec_dir / "video.mp4")
    assert abs_found == found


def test_audio_for_local_video_uses_path(monkeypatch: pytest.MonkeyPatch):
    import app.path_safety as path_safety
    import shutil
    import tempfile

    base = Path(tempfile.mkdtemp(prefix="ht_audio_test_"))
    try:
        monkeypatch.setattr(path_safety, "DATA_DIR", base)
        (base / "v").mkdir(exist_ok=True)
        (base / "v" / "lec.mp4").touch()
        m4a = base / "v" / "lec.m4a"
        m4a.touch()

        v = _make_local_video("v/lec.mp4")
        found = audio_for_local_video(v)
        assert found is not None
        assert found.name == "lec.m4a"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_audio_for_local_video_none_for_missing(monkeypatch: pytest.MonkeyPatch):
    import app.path_safety as path_safety
    import tempfile, shutil

    base = Path(tempfile.mkdtemp(prefix="ht_audio_test_"))
    try:
        monkeypatch.setattr(path_safety, "DATA_DIR", base)
        (base / "v").mkdir(exist_ok=True)
        (base / "v" / "lec.mp4").touch()
        # no m4a

        v = _make_local_video("v/lec.mp4")
        assert audio_for_local_video(v) is None
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_audio_for_local_video_handles_none():
    assert audio_for_local_video(None) is None  # type: ignore[arg-type]


# --- A2 release tests (command/TOC, no real ffmpeg execution) ---

def test_build_release_toc_basic():
    from app.media_audio import build_release_toc
    items = [
        {"heading": "Введение", "start": 120, "end": 300, "duration": 180, "audio_path": "/tmp/a.m4a"},
        {"heading": "Выводы", "start": 600, "end": 660, "duration": 60, "audio_path": "/tmp/b.m4a"},
    ]
    toc = build_release_toc(items)
    assert "Введение" in toc
    assert "3:00" in toc  # cursor after first 180s segment
    assert "Оглавление" in toc or "таймкод" in toc.lower()


def test_make_basket_audio_release_no_ffmpeg_graceful(monkeypatch: pytest.MonkeyPatch):
    from app import media_audio as ma

    monkeypatch.setattr(ma, "_has_ffmpeg", lambda: False)
    items = [{"audio_path": "/x.m4a", "start": 0, "end": 30, "heading": "t1"}]
    path, toc = ma.make_basket_audio_release(items)
    assert path is None
    assert "ffmpeg не найден" in toc


def test_make_basket_audio_release_no_items():
    from app import media_audio as ma
    path, toc = ma.make_basket_audio_release([])
    assert path is None
    assert "Нет аудио" in toc


def test_make_basket_audio_release_builds_and_mocks_concat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Verify concat flow + TOC without executing real ffmpeg (mock run + which)."""
    from app import media_audio as ma
    import time

    # prepare two fake source audios in a temp 'data'
    base = tmp_path / "d"
    base.mkdir()
    src1 = base / "v1.m4a"
    src2 = base / "v2.m4a"
    src1.write_bytes(b"\x00" * 100)
    src2.write_bytes(b"\x00" * 80)

    items = [
        {"audio_path": str(src1), "start": 0, "end": 10, "heading": "Part1", "duration": 10},
        {"audio_path": str(src2), "start": 5, "end": 12, "heading": "Part2", "duration": 7},
    ]

    calls: list = []

    def fake_which(name):
        return "/f/ffmpeg" if name == "ffmpeg" else None

    def fake_run(cmd, **kw):
        calls.append(cmd)
        # simulate success: touch the last arg as 'output'
        outp = Path(cmd[-1])
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"FAKEAUDIO")
        class R: returncode = 0
        return R()

    monkeypatch.setattr(ma, "_has_ffmpeg", lambda: True)
    monkeypatch.setattr(ma.shutil, "which", fake_which)
    monkeypatch.setattr(ma.subprocess, "run", fake_run)

    rel_path, toc = ma.make_basket_audio_release(items, suggested_name="test_release.m4a")
    assert rel_path is not None
    assert rel_path.name.endswith(".m4a")
    assert "Part1" in toc and "Part2" in toc
    # At least 2 cuts + 1 concat = 3 calls
    assert len([c for c in calls if "ffmpeg" in str(c)]) >= 2


# --- Regression pins for previously regressed contracts (per audit) ---

def test_find_audio_sibling_returns_none_for_absolute_path_outside_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Regression: absolute paths outside DATA_DIR must be rejected (path-safety invariant)."""
    import app.path_safety as path_safety
    import shutil

    data_dir = tmp_path / "safe_data"
    data_dir.mkdir(parents=True)
    monkeypatch.setattr(path_safety, "DATA_DIR", data_dir)

    # File outside the DATA_DIR
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_video = outside_dir / "lecture.mp4"
    outside_video.touch()

    result = find_audio_sibling(outside_video)
    assert result is None


def test_make_basket_audio_release_ignores_items_without_end(monkeypatch: pytest.MonkeyPatch):
    """Regression: items with audio_path but end=None must be excluded from basket release."""
    from app import media_audio as ma

    monkeypatch.setattr(ma, "_has_ffmpeg", lambda: False)

    items = [
        {"audio_path": "/good.m4a", "start": 10, "end": 40, "heading": "Valid Clip"},
        {"audio_path": "/bad.m4a", "start": 100, "heading": "Missing End"},  # no end
    ]

    path, toc = ma.make_basket_audio_release(items)
    assert path is None
    assert "Valid Clip" in toc
    assert "Missing End" not in toc
    # Should behave as if only the valid item existed for the no-ffmpeg case
    assert "ffmpeg не найден" in toc
