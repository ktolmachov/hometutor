"""Медиа-панель Живого конспекта: видео/таймкоды разделов из media-sidecar.

Вынесено из ``living_konspekt_view`` (size-budget): матчинг раздела с sidecar
(section_id → позиционный fallback), staleness sidecar'а (sha + ASR fingerprint),
рендер плееров (YouTube с таймкодом, локальный ``st.video`` после path-safety)
и сводная панель «Видео лекции» по документам корзины.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from app.media_sidecar import (
    LocalVideoSource,
    MediaSection,
    MediaSidecar,
    UrlVideoSource,
    load_media_sidecar_for_konspekt,
    sha256_file,
)
from app.media_urls import NormalizedVideoUrl, normalize_video_url
from app.path_safety import resolve_data_relative_path
from app.section_index import row_to_section
from app.ui.helpers import format_request_error

_YOUTUBE_PLAYER_HEIGHT = 400


def _row_section_id(row: dict[str, Any]) -> str | None:
    """Стабильный section_id строки (контент-хэш) — переживает сдвиг line_start."""
    if not (row.get("heading_text") and (row.get("own_text") or row.get("text"))):
        return None
    try:
        from app.media_alignment import compute_section_id

        return compute_section_id(row_to_section(row))
    except Exception:  # noqa: BLE001 - деградация к позиционному матчингу, не падение рендера
        return None



def _media_section_for_row(sidecar: MediaSidecar, row: dict[str, Any]) -> MediaSection | None:
    row_slug = str(row.get("slug") or "")
    row_heading = str(row.get("heading_text") or "")
    row_line_start = int(row.get("line_start") or 0)
    row_line_end = int(row.get("line_end") or 0)

    row_id = _row_section_id(row)
    if row_id is not None:
        for section in sidecar.sections:
            if section.section_id == row_id:
                return section
    for section in sidecar.sections:
        if section.section_slug == row_slug and section.line_start == row_line_start:
            return section
    for section in sidecar.sections:
        if section.heading == row_heading and section.line_start == row_line_start:
            return section
    for section in sidecar.sections:
        if section.heading == row_heading and section.line_end == row_line_end:
            return section
    return None


def _format_timestamp(seconds: float | int | None) -> str:
    if seconds is None:
        return "—"
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:d}:{secs:02d}"


def playlist_items_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trusted video fragments in current workbench order."""
    items: list[dict[str, Any]] = []
    sidecar_cache: dict[str, MediaSidecar | None] = {}
    stale_cache: dict[str, list[str]] = {}
    for row in rows:
        md_abs = str(row.get("konspekt_md_abs") or "")
        if not md_abs:
            continue
        if md_abs not in sidecar_cache:
            try:
                sidecar_cache[md_abs] = load_media_sidecar_for_konspekt(Path(md_abs))
            except (OSError, ValueError, json.JSONDecodeError):
                sidecar_cache[md_abs] = None
        sidecar = sidecar_cache[md_abs]
        if sidecar is None:
            continue
        media_section = _media_section_for_row(sidecar, row)
        if media_section is None or media_section.t_start is None or media_section.low_confidence:
            continue
        if md_abs not in stale_cache:
            stale_cache[md_abs] = _sidecar_stale_reasons(sidecar, md_abs)
        if stale_cache[md_abs]:
            continue
        video = sidecar.video
        title = _video_title(video, 1)
        start = int(media_section.t_start)
        end = int(media_section.t_end) if media_section.t_end is not None else None
        url = _playlist_video_url(video, start)
        items.append(
            {
                "heading": str(row.get("heading_text") or "Без названия"),
                "source": Path(md_abs).name,
                "title": title,
                "start": start,
                "end": end,
                "duration": max(0, end - start) if end is not None else 0,
                "url": url,
            }
        )
    return items


def render_playlist_panel(rows: list[dict[str, Any]]) -> None:
    items = playlist_items_from_rows(rows)
    if not items:
        return
    total_seconds = sum(int(item.get("duration") or 0) for item in items)
    minutes = max(1, round(total_seconds / 60)) if total_seconds else len(items)
    st.markdown(f"### 🎧 Мои {minutes} минут")
    st.caption("Плейлист идёт в порядке собранных фрагментов и берёт только доверенные таймкоды.")
    for idx, item in enumerate(items, start=1):
        label = f"{idx}. {item['heading']} · {item['title']} · {_format_timestamp(item['start'])}"
        if item.get("end") is not None:
            label += f"–{_format_timestamp(item['end'])}"
        if item.get("url"):
            st.link_button(label, str(item["url"]), width="stretch")
        else:
            st.caption(f"{label} · {item['source']}")


def _playlist_video_url(video: LocalVideoSource | UrlVideoSource, start: int) -> str | None:
    if isinstance(video, LocalVideoSource):
        return None
    try:
        normalized = normalize_video_url(video.canonical_url or video.url)
    except ValueError:
        return video.url
    if normalized.is_youtube:
        return normalized.with_timestamp(start)
    return normalized.canonical_url


def _expected_asr_params(video_abs: Path) -> dict[str, Any] | None:
    """Ожидаемый fingerprint ASR из <video>.segments.json — источник истины для sidecar.

    Если сегменты перетранскрибированы с другими параметрами (beam_size/language/model),
    sidecar обязан считаться устаревшим даже при неизменном media_sha256.
    """
    segments_path = video_abs.with_suffix(".segments.json")
    if not segments_path.is_file():
        return None
    try:
        payload = json.loads(segments_path.read_text(encoding="utf-8"))
        params = (payload.get("asr") or {}).get("params")
        return params if isinstance(params, dict) else None
    except (OSError, ValueError):
        return None


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
    # asr_params передаём только если и sidecar, и segments-файл его знают:
    # ручные sidecar'ы (tool=manual) без fingerprint не должны стать stale задним числом.
    if asr_params is None or sidecar.generated_by.asr_params is None:
        return sidecar.stale_reasons(konspekt_sha256=konspekt_sha, media_sha256=media_sha)
    return sidecar.stale_reasons(
        konspekt_sha256=konspekt_sha, media_sha256=media_sha, asr_params=asr_params
    )


def _render_media_panel(row: dict[str, Any]) -> None:
    """Render optional section media from sidecar; never block the plain konspekt row."""
    md_abs = str(row.get("konspekt_md_abs") or "")
    if not md_abs:
        return
    try:
        sidecar = load_media_sidecar_for_konspekt(Path(md_abs))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        st.caption(f"🎬 Медиа недоступно: {format_request_error(exc)}")
        return
    if sidecar is None:
        return

    media_section = _media_section_for_row(sidecar, row)
    stale_reasons = _sidecar_stale_reasons(sidecar, md_abs)
    if media_section is None:
        st.caption("🎬 Медиа есть, но для этого раздела таймкод не найден.")
        return

    st.markdown("**🎬 Материал раздела**")
    if stale_reasons:
        st.caption("Таймкоды устарели: " + ", ".join(stale_reasons))
    if media_section.low_confidence:
        st.caption("Таймкод примерный: confidence ниже порога.")

    confident_timestamp = media_section.t_start is not None and not stale_reasons and not media_section.low_confidence
    timestamp_label = _format_timestamp(media_section.t_start)

    for idx, video in enumerate(sidecar.videos, start=1):
        title = _video_title(video, idx)
        if len(sidecar.videos) > 1:
            st.caption(title)
        if isinstance(video, UrlVideoSource):
            _render_url_video_media(video, media_section, confident_timestamp, timestamp_label, title)
        elif isinstance(video, LocalVideoSource):
            _render_local_video_media(video, media_section, confident_timestamp, timestamp_label, title)


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


def _render_youtube_video_player(normalized: NormalizedVideoUrl, *, start_time: int = 0) -> None:
    components.iframe(normalized.embed_url(start_time), height=_YOUTUBE_PLAYER_HEIGHT)


def _render_url_video_player(video: UrlVideoSource, title: str, *, start_time: int = 0) -> None:
    try:
        normalized = normalize_video_url(video.canonical_url or video.url)
    except ValueError:
        st.link_button(f"Открыть: {title}", video.url, width="stretch")
        return

    if normalized.is_youtube:
        _render_youtube_video_player(normalized, start_time=start_time)
        link_url = normalized.with_timestamp(start_time) if start_time > 0 else normalized.canonical_url
        if start_time > 0:
            st.link_button(
                f"Открыть на YouTube с {_format_timestamp(start_time)}",
                link_url,
                width="stretch",
            )
        else:
            st.link_button(f"Открыть на YouTube: {title}", link_url, width="stretch")
        return

    st.link_button(f"Открыть: {title}", normalized.canonical_url, width="stretch")


def _render_url_video_media(
    video: UrlVideoSource,
    media_section: MediaSection,
    confident_timestamp: bool,
    timestamp_label: str,
    title: str,
) -> None:
    start_time = int(media_section.t_start or 0) if confident_timestamp else 0
    _render_url_video_player(video, title, start_time=start_time)
    if confident_timestamp and start_time > 0:
        try:
            normalized = normalize_video_url(video.canonical_url or video.url)
        except ValueError:
            return
        if normalized.is_youtube:
            st.caption(f"{title} · старт: {timestamp_label}")


def _render_local_video_media(
    video: LocalVideoSource,
    media_section: MediaSection,
    confident_timestamp: bool,
    timestamp_label: str,
    title: str,
) -> None:
    start_time = int(media_section.t_start or 0) if confident_timestamp else 0
    _render_local_video_player(video, title, start_time=start_time)
    if confident_timestamp:
        st.caption(f"{title} · старт: {timestamp_label}")


def _render_local_video_player(video: LocalVideoSource, title: str, *, start_time: int = 0) -> None:
    try:
        video_path = resolve_data_relative_path(video.path)
    except ValueError as exc:
        st.caption(f"Локальное видео отклонено path-safety: {format_request_error(exc)}")
        return
    if not video_path.exists():
        st.caption(f"Локальное видео не найдено: `{video.path}`")
        return

    st.video(str(video_path), start_time=start_time)


def _unique_document_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        md_abs = str(row.get("konspekt_md_abs") or "")
        if not md_abs or md_abs in seen:
            continue
        seen.add(md_abs)
        out.append(row)
    return out


def _render_all_lesson_videos_panel(rows: list[dict[str, Any]]) -> None:
    entries: list[tuple[str, MediaSidecar, list[str]]] = []
    for row in _unique_document_rows(rows):
        md_abs = str(row.get("konspekt_md_abs") or "")
        try:
            sidecar = load_media_sidecar_for_konspekt(Path(md_abs))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if sidecar is None or not sidecar.videos:
            continue
        entries.append((md_abs, sidecar, _sidecar_stale_reasons(sidecar, md_abs)))

    if not entries:
        return

    st.markdown("### 🎞 Все видео урока")
    for md_abs, sidecar, stale_reasons in entries:
        label = f"{Path(md_abs).name} · {len(sidecar.videos)} видео"
        with st.expander(label, expanded=len(entries) == 1):
            if stale_reasons:
                st.caption("Таймкоды устарели: " + ", ".join(stale_reasons))
            for idx, video in enumerate(sidecar.videos, start=1):
                title = _video_title(video, idx)
                with st.expander(title, expanded=len(sidecar.videos) == 1):
                    if isinstance(video, UrlVideoSource):
                        _render_url_video_player(video, title)
                    elif isinstance(video, LocalVideoSource):
                        _render_local_video_player(video, title)

