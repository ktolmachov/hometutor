"""Audio support for local lecture media (P0 wave-audio-01).

Sibling ``<video>.m4a`` is discovered by pure filesystem convention next to the
video file recorded in ``media_sidecar`` (LocalVideoSource.path). This does
**not** modify the sidecar schema (v1 + ``additionalProperties: false`` /
``_reject_extra_keys``) and adds no new storage or LLM calls.

Used to enable ``st.audio`` playback of trusted sections/playlists with
precise ``t_start``/``t_end`` clipping (same pattern as lazy ``st.video``).

See evolutionary plan wave-audio-first-sound (A1) and wave-audio-release (A2).

A2 helpers focus on command execution for basket concat with tests asserting shape
(ffmpeg invocations are mocked in unit tests; graceful when ffmpeg absent).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.path_safety import resolve_data_relative_path

if TYPE_CHECKING:  # avoid runtime import cycle for type checkers only
    from app.media_sidecar import LocalVideoSource


def find_audio_sibling(video_path: str | Path) -> Path | None:
    """Return absolute Path to sibling ``.m4a`` if it exists next to video.

    - Accepts data-relative path (from sidecar) or already-resolved absolute.
    - Resolution uses the same ``path_safety`` contract as video.
    - Returns None (never raises) when sibling is absent or resolution fails.
    - The convention is co-location + ``with_suffix(".m4a")``; no sidecar field.
    """
    try:
        p = Path(video_path)
        if p.is_absolute():
            video_abs = p
        else:
            video_abs = resolve_data_relative_path(str(video_path))
        audio_abs = video_abs.with_suffix(".m4a")
        if audio_abs.is_file():
            return audio_abs
    except (OSError, ValueError):
        return None
    return None


def audio_for_local_video(video: "LocalVideoSource") -> Path | None:
    """Convenience wrapper for ``LocalVideoSource`` from a media sidecar."""
    if video is None:
        return None
    return find_audio_sibling(video.path)


# --- A2: basket release (single m4a from playlist fragments) ---

def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def build_release_toc(items: list[dict[str, Any]]) -> str:
    """Human readable timestamped table of contents for the concatenated release."""
    lines: list[str] = ["Выпуск «Мои N минут» (аудио) — таймкоды в готовом файле начинаются с 0:00"]
    cursor = 0
    for i, it in enumerate(items, 1):
        start = int(it.get("start", 0))
        end = it.get("end")
        dur = int(it.get("duration") or 0) if end is None else max(0, int(end) - start)
        heading = it.get("heading", "раздел")
        ts = _fmt_release_ts(cursor)
        lines.append(f"{ts}  —  {heading}  ({_fmt_release_ts(dur)})")
        cursor += dur
    lines.append("")
    lines.append("Собран из доверенных фрагментов Живого конспекта. Переходы в исходные разделы — через UI.")
    return "\n".join(lines)


def _fmt_release_ts(seconds: int | float) -> str:
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _perform_cuts(usable: list[dict[str, Any]], workdir: Path) -> list[Path]:
    """Cut audio fragments for each item into workdir. Returns list of cut files (successful only)."""
    cuts: list[Path] = []
    for i, it in enumerate(usable, 1):
        src = Path(str(it.get("audio_path")))
        if not src.is_file():
            continue
        start = int(it.get("start", 0))
        end = it.get("end")
        cut = workdir / f"cut_{i:02d}.m4a"
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src)]
        if start > 0:
            cmd += ["-ss", str(start)]
        if end is not None and end > start:
            cmd += ["-to", str(end)]
        cmd += ["-c", "copy", str(cut)]
        res = subprocess.run(cmd, check=False)
        if res.returncode == 0 and cut.exists():
            cuts.append(cut)
    return cuts


def _perform_concat(cut_files: list[Path], out_path: Path) -> bool:
    """Concat pre-cut files into out_path using ffmpeg concat demuxer. Returns success."""
    if not cut_files:
        return False
    listf = out_path.parent / "concat_list.txt"
    listf.write_text("".join(f"file '{c.name}'\n" for c in cut_files), encoding="utf-8")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(listf),
        "-c", "copy",
        str(out_path),
    ]
    res = subprocess.run(cmd, check=False)
    return res.returncode == 0 and out_path.exists()


def _persist_to_user_releases(src: Path, base_name: str) -> Path:
    """Copy the produced release out of temp into a stable(ish) user temp location."""
    final_dir = Path(tempfile.gettempdir()) / "hometutor_releases"
    final_dir.mkdir(parents=True, exist_ok=True)
    final = final_dir / base_name
    if final.exists():
        final = final_dir / f"{base_name.rsplit('.', 1)[0]}_{int(time.time())}.m4a"
    shutil.copy2(src, final)
    return final


def make_basket_audio_release(
    items: list[dict[str, Any]],
    *,
    suggested_name: str = "playlist_release.m4a",
) -> tuple[Path | None, str]:
    """Produce concatenated .m4a + TOC from playlist items that carry audio_path.

    Thin orchestration: cut per-fragment (copy) + concat (copy). Work in temp.
    Returns (final_m4a or None, toc_text or error/hint message).
    Never raises for missing ffmpeg (graceful per A2 plan).
    """
    usable = [it for it in items if it.get("audio_path")]
    if not usable:
        return None, "Нет аудио-фрагментов в корзине для сборки выпуска."

    if not _has_ffmpeg():
        toc = build_release_toc(usable)
        hint = "Скачивание выпуска недоступно: ffmpeg не найден в PATH.\nУстановка: winget install Gyan.FFmpeg\n\n" + toc
        return None, hint

    toc = build_release_toc(usable)

    release: Path | None = None
    with tempfile.TemporaryDirectory(prefix="hometutor_audio_release_") as td_str:
        tmp = Path(td_str)
        cuts = _perform_cuts(usable, tmp)
        if not cuts:
            return None, toc + "\n\n(Не удалось нарезать фрагменты.)"

        out = tmp / suggested_name
        if not _perform_concat(cuts, out):
            return None, toc + "\n\n(ffmpeg concat не удался.)"

        release = _persist_to_user_releases(out, suggested_name)
    return release, toc
