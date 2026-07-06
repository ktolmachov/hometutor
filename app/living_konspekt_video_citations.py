"""Trusted video citations for Quick Answer sources."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.living_konspekt_source_resolver import SourceSectionCandidate, resolve_source_section
from app.media_sidecar import (
    LocalVideoSource,
    MediaSection,
    MediaSidecar,
    UrlVideoSource,
    load_media_sidecar_for_konspekt,
    sha256_file,
)
from app.media_urls import normalize_video_url
from app.path_safety import resolve_data_relative_path
from app.section_index import IndexedSection, section_to_row


@dataclass(frozen=True)
class SourceVideoCitation:
    heading: str
    video_title: str
    timestamp_label: str
    start_seconds: int
    end_seconds: int | None
    url: str | None
    source_label: str


@dataclass(frozen=True)
class SourceVideoCitationResolution:
    status: str  # "available" | "unavailable"
    citation: SourceVideoCitation | None
    message: str


def resolve_source_video_citation(source: dict[str, Any]) -> SourceVideoCitationResolution:
    """Resolve a retrieval source into one trusted video citation, if possible."""
    section_resolution = resolve_source_section(source)
    if section_resolution.status != "single" or section_resolution.single is None:
        return SourceVideoCitationResolution(
            "unavailable",
            None,
            "Видео-цитата появится после уверенного сопоставления источника с разделом.",
        )
    return video_citation_for_candidate(section_resolution.single)


def video_citation_for_candidate(candidate: SourceSectionCandidate) -> SourceVideoCitationResolution:
    """Return a trusted timestamp citation for a resolved konspekt section."""
    section = candidate.section
    try:
        sidecar = load_media_sidecar_for_konspekt(Path(section.konspekt_md_abs))
    except (OSError, ValueError, json.JSONDecodeError):
        sidecar = None
    if sidecar is None:
        return SourceVideoCitationResolution(
            "unavailable",
            None,
            "Для раздела нет media-sidecar с таймкодами.",
        )

    media_section = _media_section_for_section(sidecar, section)
    if media_section is None:
        return SourceVideoCitationResolution(
            "unavailable",
            None,
            "Media-sidecar есть, но таймкод этого раздела не найден.",
        )
    if media_section.t_start is None:
        return SourceVideoCitationResolution(
            "unavailable",
            None,
            "Для раздела нет стартового таймкода.",
        )
    if media_section.low_confidence:
        return SourceVideoCitationResolution(
            "unavailable",
            None,
            "Таймкод есть, но confidence ниже доверенного порога.",
        )

    stale_reasons = _sidecar_stale_reasons(sidecar, str(section.konspekt_md_abs))
    if stale_reasons:
        return SourceVideoCitationResolution(
            "unavailable",
            None,
            "Таймкод устарел: " + ", ".join(stale_reasons),
        )

    start = int(media_section.t_start)
    end = int(media_section.t_end) if media_section.t_end is not None else None
    video = _first_url_video(sidecar) or sidecar.video
    title = _video_title(video, 1)
    url = _timestamp_url(video, start)
    citation = SourceVideoCitation(
        heading=section.heading_text,
        video_title=title,
        timestamp_label=_format_timestamp(start),
        start_seconds=start,
        end_seconds=end,
        url=url,
        source_label=Path(section.konspekt_md_abs).name,
    )
    return SourceVideoCitationResolution("available", citation, "Видео-цитата готова.")


def _media_section_for_section(sidecar: MediaSidecar, section: IndexedSection) -> MediaSection | None:
    row = section_to_row(section)
    row_id = _row_section_id(section)
    if row_id is not None:
        for item in sidecar.sections:
            if item.section_id == row_id:
                return item
    for item in sidecar.sections:
        if item.section_slug == row["slug"] and item.line_start == row["line_start"]:
            return item
    for item in sidecar.sections:
        if item.heading == row["heading_text"] and item.line_start == row["line_start"]:
            return item
    for item in sidecar.sections:
        if item.heading == row["heading_text"] and item.line_end == row["line_end"]:
            return item
    return None


def _row_section_id(section: IndexedSection) -> str:
    from app.media_alignment import compute_section_id

    return compute_section_id(section)


def _sidecar_stale_reasons(sidecar: MediaSidecar, md_abs: str) -> list[str]:
    try:
        konspekt_sha = sha256_file(Path(md_abs))
    except OSError:
        konspekt_sha = None
    media_sha: str | None = None
    asr_params: dict[str, Any] | None = None
    if isinstance(sidecar.video, LocalVideoSource):
        try:
            video_abs = resolve_data_relative_path(sidecar.video.path)
            media_sha = sha256_file(video_abs)
            asr_params = _expected_asr_params(video_abs)
        except (OSError, ValueError):
            media_sha = None
    if asr_params is None or sidecar.generated_by.asr_params is None:
        return sidecar.stale_reasons(konspekt_sha256=konspekt_sha, media_sha256=media_sha)
    return sidecar.stale_reasons(
        konspekt_sha256=konspekt_sha,
        media_sha256=media_sha,
        asr_params=asr_params,
    )


def _expected_asr_params(video_abs: Path) -> dict[str, Any] | None:
    segments_path = video_abs.with_suffix(".segments.json")
    if not segments_path.is_file():
        return None
    try:
        payload = json.loads(segments_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    params = (payload.get("asr") or {}).get("params")
    return params if isinstance(params, dict) else None


def _first_url_video(sidecar: MediaSidecar) -> UrlVideoSource | None:
    for video in sidecar.videos:
        if isinstance(video, UrlVideoSource):
            return video
    return None


def _timestamp_url(video: LocalVideoSource | UrlVideoSource, start: int) -> str | None:
    if isinstance(video, LocalVideoSource):
        return None
    try:
        normalized = normalize_video_url(video.canonical_url or video.url)
    except ValueError:
        return video.url
    if normalized.is_youtube:
        return normalized.with_timestamp(start)
    return normalized.canonical_url


def _video_title(video: LocalVideoSource | UrlVideoSource, idx: int) -> str:
    if video.title:
        return video.title
    if isinstance(video, LocalVideoSource):
        return Path(video.path).name
    try:
        normalized = normalize_video_url(video.canonical_url or video.url)
    except ValueError:
        return f"Видео {idx}"
    return normalized.canonical_url


def _format_timestamp(seconds: float | int | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:d}:{secs:02d}"


__all__ = [
    "SourceVideoCitation",
    "SourceVideoCitationResolution",
    "resolve_source_video_citation",
    "video_citation_for_candidate",
]
