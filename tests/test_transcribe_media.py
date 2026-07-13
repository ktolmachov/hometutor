from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.transcribe_media as transcribe_media


class _FakeSegment:
    start = 1.0
    end = 2.0
    text = " hello "


class _FakeWhisperModel:
    devices: list[str] = []
    fail_devices: set[str] = {"auto"}

    def __init__(self, model_name: str, *, device: str, compute_type: str):
        self.device = device
        self.devices.append(device)

    def transcribe(self, *args, **kwargs):
        if self.device in self.fail_devices:
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
        return [_FakeSegment()], SimpleNamespace(language="ru")


def test_transcribe_auto_falls_back_to_cpu_on_missing_cuda_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    _FakeWhisperModel.devices = []
    _FakeWhisperModel.fail_devices = {"auto"}
    monkeypatch.setattr(transcribe_media, "_import_whisper", lambda: _FakeWhisperModel)

    payload = transcribe_media.transcribe(
        tmp_path / "lecture.mp4",
        model_name="large-v3",
        language="auto",
        device="auto",
        beam_size=5,
    )

    assert _FakeWhisperModel.devices == ["auto", "cpu"]
    assert payload["asr"]["device"] == "cpu"
    assert payload["segments"] == [{"start": 1.0, "end": 2.0, "text": "hello"}]


def test_transcribe_explicit_cuda_does_not_hide_cuda_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    _FakeWhisperModel.devices = []
    _FakeWhisperModel.fail_devices = {"cuda"}
    monkeypatch.setattr(transcribe_media, "_import_whisper", lambda: _FakeWhisperModel)

    with pytest.raises(RuntimeError, match="cublas64_12"):
        transcribe_media.transcribe(
            tmp_path / "lecture.mp4",
            model_name="large-v3",
            language="auto",
            device="cuda",
            beam_size=5,
        )

    assert _FakeWhisperModel.devices == ["cuda"]


def test_extract_audio_to_m4a_graceful_no_ffmpeg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys):
    monkeypatch.setattr(transcribe_media.shutil, "which", lambda x: None)
    media = tmp_path / "lec.mp4"
    media.touch()

    res = transcribe_media.extract_audio_to_m4a(media)
    assert res is None
    captured = capsys.readouterr()
    assert "ffmpeg не найден" in captured.err


def test_extract_audio_to_m4a_skips_if_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys):
    monkeypatch.setattr(transcribe_media.shutil, "which", lambda x: "/usr/bin/ffmpeg")
    media = tmp_path / "lec.mp4"
    media.touch()
    m4a = tmp_path / "lec.m4a"
    m4a.touch()

    res = transcribe_media.extract_audio_to_m4a(media)
    assert res == m4a
    captured = capsys.readouterr()
    assert "уже существует" in captured.out


def test_extract_audio_to_m4a_builds_correct_ffmpeg_cmd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Test command shape (no real exec) — per evolutionary test guidance for ffmpeg ops."""
    calls: list[list[str]] = []

    def fake_which(x):
        return "/fake/ffmpeg" if x == "ffmpeg" else None

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        # simulate success by touching target
        Path(cmd[-1]).touch()
        class R: returncode = 0
        return R()

    monkeypatch.setattr(transcribe_media.shutil, "which", fake_which)
    monkeypatch.setattr(transcribe_media.subprocess, "run", fake_run)

    media = tmp_path / "video lecture.mp4"
    media.touch()

    res = transcribe_media.extract_audio_to_m4a(media)
    assert res is not None
    assert res.name == "video lecture.m4a"
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "/fake/ffmpeg"
    assert "-vn" in cmd
    assert "-c:a" in cmd and "copy" in cmd
    assert str(media) in cmd
    assert str(res) in cmd
