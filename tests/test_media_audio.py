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
