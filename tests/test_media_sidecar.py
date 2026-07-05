from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.media_sidecar import (
    LocalVideoSource,
    UrlVideoSource,
    load_media_sidecar,
    load_media_sidecar_for_konspekt,
    parse_media_sidecar,
    read_media_sidecar_pointer,
)

SHA = "a" * 64
MEDIA_SHA = "b" * 64
SECTION_SHA = "c" * 64
IMAGE_SHA = "d" * 64


def _payload() -> dict:
    return {
        "schema_version": 1,
        "konspekt_sha256": SHA,
        "media_sha256": MEDIA_SHA,
        "generated_by": {
            "tool": "transcribe_media",
            "asr_model": "faster-whisper-large-v3",
            "alignment_version": "section-align-v1",
            "created_at": "2026-07-05T00:00:00Z",
        },
        "media": {
            "video": {
                "kind": "local",
                "path": "courses/autonomy/lecture_01/video.mp4",
                "sha256": MEDIA_SHA,
                "duration_seconds": 123.4,
            }
        },
        "sections": [
            {
                "section_id": f"sha256:{SECTION_SHA}",
                "section_slug": "architecture-of-autonomy",
                "heading": "Architecture of Autonomy",
                "line_start": 12,
                "line_end": 58,
                "t_start": 734.2,
                "t_end": 1091.4,
                "confidence": 0.82,
                "images": [
                    {
                        "path": "courses/autonomy/lecture_01/slide-01.png",
                        "sha256": IMAGE_SHA,
                        "source": "video_keyframe",
                        "t_start": 735.0,
                    }
                ],
            }
        ],
    }


def test_parse_valid_local_media_sidecar(tmp_path: Path):
    sidecar = parse_media_sidecar(_payload(), data_dir=tmp_path)

    assert sidecar.schema_version == 1
    assert isinstance(sidecar.video, LocalVideoSource)
    assert sidecar.video.path == "courses/autonomy/lecture_01/video.mp4"
    assert sidecar.sections[0].section_id == f"sha256:{SECTION_SHA}"
    assert sidecar.sections[0].has_timestamp is True
    assert sidecar.sections[0].low_confidence is False
    assert sidecar.sections[0].images[0].path.endswith("slide-01.png")


def test_parse_valid_url_media_sidecar(tmp_path: Path):
    payload = _payload()
    payload["media"]["video"] = {
        "kind": "url",
        "url": "https://youtu.be/abcDEF12345?t=90",
    }

    sidecar = parse_media_sidecar(payload, data_dir=tmp_path)

    assert isinstance(sidecar.video, UrlVideoSource)
    assert sidecar.video.url == "https://youtu.be/abcDEF12345?t=90"
    assert sidecar.video.canonical_url == "https://www.youtube.com/watch?v=abcDEF12345"


def test_stale_reasons_cover_hash_model_alignment_and_schema(tmp_path: Path):
    sidecar = parse_media_sidecar(_payload(), data_dir=tmp_path)

    reasons = sidecar.stale_reasons(
        konspekt_sha256="0" * 64,
        media_sha256="1" * 64,
        asr_model="different-asr",
        alignment_version="different-aligner",
        schema_version=2,
    )

    assert reasons == [
        "schema_version",
        "konspekt_sha256",
        "media_sha256",
        "asr_model",
        "alignment_version",
    ]
    assert sidecar.is_stale(konspekt_sha256=SHA) is False


@pytest.mark.parametrize(
    "path",
    [
        "../secret.mp4",
        "courses/../../secret.mp4",
        "D:/private/video.mp4",
        "\\\\server\\share\\video.mp4",
    ],
)
def test_rejects_unsafe_persisted_local_paths(tmp_path: Path, path: str):
    payload = _payload()
    payload["media"]["video"]["path"] = path

    with pytest.raises(ValueError):
        parse_media_sidecar(payload, data_dir=tmp_path)


def test_rejects_unsafe_image_paths(tmp_path: Path):
    payload = _payload()
    payload["sections"][0]["images"][0]["path"] = "../slide.png"

    with pytest.raises(ValueError):
        parse_media_sidecar(payload, data_dir=tmp_path)


def test_rejects_invalid_section_ranges(tmp_path: Path):
    payload = _payload()
    payload["sections"][0]["line_end"] = 2

    with pytest.raises(ValueError):
        parse_media_sidecar(payload, data_dir=tmp_path)


def test_rejects_unsupported_keys_like_schema_additional_properties_false(tmp_path: Path):
    payload = _payload()
    payload["sections"][0]["unexpected"] = "nope"

    with pytest.raises(ValueError, match="unsupported keys"):
        parse_media_sidecar(payload, data_dir=tmp_path)


def test_read_media_sidecar_pointer_from_frontmatter(tmp_path: Path):
    markdown = """---
source: lecture.txt
media_sidecar: courses/autonomy/lecture_01/video.media.json
---

# Lecture
"""

    pointer = read_media_sidecar_pointer(markdown, data_dir=tmp_path)

    assert pointer == "courses/autonomy/lecture_01/video.media.json"


def test_read_media_sidecar_pointer_rejects_absolute_path(tmp_path: Path):
    markdown = """---
media_sidecar: D:/private/video.media.json
---

# Lecture
"""

    with pytest.raises(ValueError):
        read_media_sidecar_pointer(markdown, data_dir=tmp_path)


def test_load_sidecar_for_konspekt_returns_none_without_pointer(tmp_path: Path):
    konspekt = tmp_path / "lecture.md"
    konspekt.write_text("# Lecture\n", encoding="utf-8")

    assert load_media_sidecar_for_konspekt(konspekt, data_dir=tmp_path) is None


def test_load_sidecar_for_konspekt_reads_data_relative_sidecar(tmp_path: Path):
    sidecar_path = tmp_path / "courses" / "autonomy" / "lecture.media.json"
    sidecar_path.parent.mkdir(parents=True)
    sidecar_path.write_text(json.dumps(_payload()), encoding="utf-8")
    konspekt = tmp_path / "lecture.md"
    konspekt.write_text(
        "---\nmedia_sidecar: courses/autonomy/lecture.media.json\n---\n\n# Lecture\n",
        encoding="utf-8",
    )

    sidecar = load_media_sidecar_for_konspekt(konspekt, data_dir=tmp_path)

    assert sidecar is not None
    assert isinstance(sidecar.video, LocalVideoSource)


def test_load_sidecar_validates_json_payload(tmp_path: Path):
    path = tmp_path / "sidecar.media.json"
    payload = copy.deepcopy(_payload())
    payload["schema_version"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_media_sidecar("sidecar.media.json", data_dir=tmp_path)
