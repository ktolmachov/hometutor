from __future__ import annotations

import json
from pathlib import Path

from app import path_safety
from app.media_sidecar import load_media_sidecar_for_konspekt, sidecar_stale_reasons
import scripts.attach_whole_lesson_video as attach_whole_video


def _patch_data_dir(monkeypatch, data_dir: Path) -> None:
    monkeypatch.setattr(path_safety, "DATA_DIR", data_dir)


def test_attach_whole_lesson_video_writes_clean_sidecar(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    _patch_data_dir(monkeypatch, data_dir)
    konspekt = data_dir / "uploads" / "hometutor_101" / "konspekts" / "lesson.konspekt.md"
    video = data_dir / "uploads" / "hometutor_101" / "videos" / "lesson.mp4"
    konspekt.parent.mkdir(parents=True)
    video.parent.mkdir(parents=True)
    konspekt.write_text("---\ntype: konspekt\n---\n\n# Lesson\n\nBody.\n", encoding="utf-8")
    video.write_bytes(b"fake mp4 bytes")

    rc = attach_whole_video.main(
        [
            "uploads/hometutor_101/konspekts/lesson.konspekt.md",
            "--video",
            "uploads/hometutor_101/videos/lesson.mp4",
            "--title",
            "Урок 1 · Целое видео",
        ]
    )

    assert rc == 0
    sidecar_path = konspekt.with_suffix(".media.json")
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert payload["media"]["video"]["path"] == "uploads/hometutor_101/videos/lesson.mp4"
    assert payload["media"]["video"]["title"] == "Урок 1 · Целое видео"
    assert payload["sections"] == []
    assert payload["semantic_blocks"] == []
    assert "alignment_version" not in payload["generated_by"]

    text = konspekt.read_text(encoding="utf-8")
    assert text.startswith(
        "---\n"
        "media_sidecar: uploads/hometutor_101/konspekts/lesson.konspekt.media.json\n"
        "type: konspekt\n"
        "---\n"
    )

    sidecar = load_media_sidecar_for_konspekt(konspekt)
    assert sidecar is not None
    assert len(sidecar.sections) == 0
    assert len(sidecar.videos) == 1
    assert sidecar_stale_reasons(sidecar, str(konspekt)) == []


def test_attach_whole_lesson_video_refuses_to_clobber_timestamps(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    _patch_data_dir(monkeypatch, data_dir)
    konspekt = data_dir / "course" / "lesson.md"
    video = data_dir / "course" / "lesson.mp4"
    konspekt.parent.mkdir(parents=True)
    konspekt.write_text("# Lesson\n", encoding="utf-8")
    video.write_bytes(b"fake mp4 bytes")
    sidecar_path = konspekt.with_suffix(".media.json")
    original = {"sections": [{"heading": "Intro", "t_start": 12.0}]}
    sidecar_path.write_text(json.dumps(original), encoding="utf-8")

    rc = attach_whole_video.main(["course/lesson.md", "--video", "course/lesson.mp4"])

    assert rc == 2
    assert json.loads(sidecar_path.read_text(encoding="utf-8")) == original
