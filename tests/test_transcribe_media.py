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
