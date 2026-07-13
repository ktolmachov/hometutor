"""Audio support for local lecture media (P0 wave-audio-01).

Sibling ``<video>.m4a`` is discovered by pure filesystem convention next to the
video file recorded in ``media_sidecar`` (LocalVideoSource.path). This does
**not** modify the sidecar schema (v1 + ``additionalProperties: false`` /
``_reject_extra_keys``) and adds no new storage or LLM calls.

Used to enable ``st.audio`` playback of trusted sections/playlists with
precise ``t_start``/``t_end`` clipping (same pattern as lazy ``st.video``).

See evolutionary plan wave-audio-first-sound (A1).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

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
