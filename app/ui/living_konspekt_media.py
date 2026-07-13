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
    expected_asr_params as _expected_asr_params,
    load_media_sidecar_for_konspekt,
    sidecar_stale_reasons as _sidecar_stale_reasons,
)
from app.media_audio import audio_for_local_video, make_basket_audio_release
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
        audio_path = None
        if isinstance(video, LocalVideoSource):
            ap = audio_for_local_video(video)
            if ap is not None:
                audio_path = str(ap)
        items.append(
            {
                "heading": str(row.get("heading_text") or "Без названия"),
                "source": Path(md_abs).name,
                "title": title,
                "start": start,
                "end": end,
                "duration": max(0, end - start) if end is not None else 0,
                "url": url,
                "audio_path": audio_path,
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
        audio_path = item.get("audio_path")
        if item.get("url"):
            st.link_button(label, str(item["url"]), width="stretch")
        elif audio_path:
            # Local audio now playable (wave 2). Lazy checkbox to match video cost concern.
            cb_key = f"pl_audio_{idx}_{item.get('start', 0)}"
            if st.checkbox(f"🎧 {label}", key=cb_key):
                try:
                    ap = Path(audio_path)
                    end = item.get("end")
                    if end is not None and end > item["start"]:
                        st.audio(str(ap), start_time=item["start"], end_time=end)
                    else:
                        st.audio(str(ap), start_time=item["start"])
                except Exception as exc:  # noqa: BLE001 - playlist render must degrade
                    st.caption(f"Аудио плейлиста недоступно: {format_request_error(exc)}")
        else:
            st.caption(f"{label} · {item['source']}")

    _render_basket_audio_release(items)


def _render_basket_audio_release(items: list[dict[str, Any]]) -> None:
    """A2 UI: button to build+download single m4a from current playlist audio items.

    Extracted to keep render_playlist_panel lean. Only appears when usable audio
    siblings exist. ffmpeg work happens only on explicit user click.
    """
    audio_items = [it for it in items if it.get("audio_path")]
    if not audio_items:
        return
    st.markdown("---")
    if st.button("⬇️ Скачать выпуск (m4a)", key="download_basket_release"):
        release_path, toc = make_basket_audio_release(
            audio_items, suggested_name="hometutor_basket_release.m4a"
        )
        if release_path and release_path.exists():
            data = release_path.read_bytes()
            st.download_button(
                "Скачать готовый выпуск .m4a",
                data=data,
                file_name=release_path.name,
                mime="audio/mp4",
                key="do_download_release",
            )
            st.caption("Выпуск готов. Время сборки — секунды (copy, без перекодирования).")
            with st.expander("Оглавление таймкодов (текст)", expanded=False):
                st.text(toc)
        else:
            st.caption(toc or "Не удалось собрать выпуск (см. логи).")
    else:
        st.caption("Собери ≥1 аудио-фрагмент в корзину и нажми кнопку для склейки в один файл (ffmpeg concat).")


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


def _render_media_panel(row: dict[str, Any], is_first: bool = False, *, key_prefix: str = "wb") -> None:
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

    trusted_timestamp = (
        media_section.t_start is not None
        and not stale_reasons
        and not media_section.low_confidence
    )
    timestamp_label = _format_section_time_range(media_section)
    expander_label = "🎬 Видео раздела" if trusted_timestamp else "🎬 Видео-кандидат"
    if timestamp_label:
        suffix = timestamp_label if trusted_timestamp else f"примерно {timestamp_label}"
        expander_label += f" ({suffix})"

    with st.expander(expander_label, expanded=is_first):
        st.markdown("**🎬 Материал раздела**")
        if stale_reasons:
            st.caption("Таймкоды устарели: " + ", ".join(stale_reasons))
        if media_section.low_confidence:
            st.caption("Видео не добавлено в раздел: confidence ниже порога.")
            if timestamp_label:
                st.caption(f"Кандидат таймкода: {timestamp_label} (примерно).")
        if not trusted_timestamp:
            return

        video = sidecar.video
        title = _video_title(video, 1)
        st.caption(f"{title} · таймкод раздела: {timestamp_label}")
        if isinstance(video, UrlVideoSource):
            _render_url_video_media(video, media_section, title)
        elif isinstance(video, LocalVideoSource):
            row_key = str(row.get("row_key") or f"{row.get('line_start')}_{row.get('heading_text')}")
            checkbox_key = f"lk_play_video_{key_prefix}_{row_key}"
            _render_local_video_media(video, media_section, title, checkbox_key)



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


def _format_section_time_range(media_section: MediaSection) -> str:
    if media_section.t_start is None:
        return ""
    start = _format_timestamp(media_section.t_start)
    if media_section.t_end is None or media_section.t_end <= media_section.t_start:
        return start
    return f"{start}–{_format_timestamp(media_section.t_end)}"


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
    title: str,
) -> None:
    start_time = int(media_section.t_start or 0)
    _render_url_video_player(video, title, start_time=start_time)
    if start_time > 0:
        try:
            normalized = normalize_video_url(video.canonical_url or video.url)
        except ValueError:
            return
        if normalized.is_youtube:
            st.caption(f"{title} · старт: {_format_timestamp(start_time)}")


def _render_local_video_media(
    video: LocalVideoSource,
    media_section: MediaSection,
    title: str,
    checkbox_key: str,
) -> None:
    # Локальный st.video() читает весь файл в память при КАЖДОМ вызове (Streamlit
    # хэширует контент, чтобы определить file_id — кэша по mtime у него нет). При
    # 812 МБ-видео и 24 разделах на 2 вкладки это давало ~48 полных чтений файла за
    # rerun. Плеер поэтому рендерится только по явному клику, а не для каждой строки.
    if st.checkbox("▶ Показать видео", key=checkbox_key):
        start_time = int(media_section.t_start or 0)
        _render_local_video_player(video, title, start_time=start_time)

    # Audio sibling (wave-audio-01): discovered by convention next to video file.
    # No schema change. Render only if .m4a present (graceful, same lazy checkbox).
    audio_path = audio_for_local_video(video)
    if audio_path is not None:
        audio_key = f"lk_play_audio_{checkbox_key}"
        if st.checkbox("🎧 Слушать раздел", key=audio_key):
            start_time = int(media_section.t_start or 0)
            end_time = int(media_section.t_end) if media_section.t_end is not None else None
            _render_local_audio_player(audio_path, title, start_time=start_time, end_time=end_time)


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


def _render_local_audio_player(
    audio_path: Path,
    title: str,
    *,
    start_time: int = 0,
    end_time: int | None = None,
) -> None:
    """Render clipped st.audio for local .m4a sibling (P0 first-sound)."""
    try:
        # audio_path is already absolute resolved from helper
        if not audio_path.exists():
            st.caption(f"Аудио не найдено: `{audio_path}`")
            return
        # end_time is keyword-only in Streamlit; pass only if present
        if end_time is not None and end_time > start_time:
            st.audio(str(audio_path), start_time=start_time, end_time=end_time)
        else:
            st.audio(str(audio_path), start_time=start_time)
    except Exception as exc:  # noqa: BLE001 - audio render must not break the whole panel
        st.caption(f"Аудио недоступно: {format_request_error(exc)}")


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


def render_lesson_video_links_for_md(md_abs: str) -> None:
    """Compact link-only panel for all lesson videos of *md_abs* (no embedded player).

    Intended for inline per-section use inside ``render_collected_sections``.
    Silently no-ops when the document has no sidecar or no videos.
    """
    if not md_abs:
        return
    try:
        sidecar = load_media_sidecar_for_konspekt(Path(md_abs))
    except (OSError, ValueError, json.JSONDecodeError):
        return
    if sidecar is None or not sidecar.videos:
        return
    stale_reasons = _sidecar_stale_reasons(sidecar, md_abs)
    st.caption("🎞 Видео урока:")
    if stale_reasons:
        st.caption("⚠ Таймкоды устарели: " + ", ".join(stale_reasons))
    for idx, video in enumerate(sidecar.videos, start=1):
        title = _video_title(video, idx)
        if isinstance(video, UrlVideoSource):
            try:
                normalized = normalize_video_url(video.canonical_url or video.url)
            except ValueError:
                st.link_button(title, video.url, width="stretch")
                continue
            st.link_button(title, normalized.canonical_url, width="stretch")
        elif isinstance(video, LocalVideoSource):
            st.caption(f"📹 {title} (локальный файл: {video.path})")


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
                with st.expander(title, expanded=False):
                    if isinstance(video, UrlVideoSource):
                        try:
                            normalized = normalize_video_url(video.canonical_url or video.url)
                            link_url = normalized.canonical_url
                            st.link_button(f"Открыть на YouTube: {title}", link_url, width="stretch")
                        except ValueError:
                            st.link_button(f"Открыть: {title}", video.url, width="stretch")
                            normalized = None

                        if normalized and normalized.is_youtube:
                            if st.checkbox("Показать встроенный плеер", key=f"embed_all_v_{md_abs}_{idx}"):
                                _render_youtube_video_player(normalized)
                    elif isinstance(video, LocalVideoSource):
                        st.caption(f"📹 {title} (локальный файл: {video.path})")
                        if st.checkbox("Показать встроенный плеер", key=f"embed_all_v_{md_abs}_{idx}"):
                            _render_local_video_player(video, title)
