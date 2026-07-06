from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_YOUTUBE_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
_TIMESTAMP_RE = re.compile(r"^(?:(?P<h>\d+)h)?(?:(?P<m>\d+)m)?(?:(?P<s>\d+)s?)?$", re.IGNORECASE)
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")


@dataclass(frozen=True)
class NormalizedVideoUrl:
    kind: str
    original_url: str
    canonical_url: str
    video_id: str | None = None
    timestamp_seconds: int | None = None

    @property
    def is_youtube(self) -> bool:
        return self.kind == "youtube"

    def with_timestamp(self, seconds: int | float | None = None) -> str:
        if not self.is_youtube:
            return self.canonical_url
        value = self.timestamp_seconds if seconds is None else int(seconds)
        if value is None or value < 0:
            return self.canonical_url
        return _replace_query_param(self.canonical_url, "t", f"{value}s")

    def embed_url(self, seconds: int | float | None = None) -> str:
        if not self.is_youtube or not self.video_id:
            raise ValueError("Not a YouTube URL")
        start = self.timestamp_seconds if seconds is None else int(seconds)
        base = f"https://www.youtube.com/embed/{self.video_id}"
        if start is not None and start > 0:
            return f"{base}?start={start}"
        return base


def _parse_timestamp(value: str | None) -> int | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    if ":" in raw:
        parts = raw.split(":")
        if not 1 <= len(parts) <= 3 or not all(part.isdigit() for part in parts):
            return None
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + int(part)
        return seconds
    match = _TIMESTAMP_RE.match(raw)
    if not match:
        return None
    hours = int(match.group("h") or 0)
    minutes = int(match.group("m") or 0)
    seconds = int(match.group("s") or 0)
    total = hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else None


def _clean_host(host: str | None) -> str:
    return (host or "").lower().removeprefix("www.")


def _replace_query_param(url: str, key: str, value: str) -> str:
    parsed = urlparse(url)
    pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k != key]
    pairs.append((key, value))
    return urlunparse(parsed._replace(query=urlencode(pairs)))


def _canonical_youtube_url(video_id: str, query_pairs: list[tuple[str, str]]) -> str:
    kept = [(k, v) for k, v in query_pairs if k not in {"v", "t", "start", "time_continue"}]
    query = urlencode([("v", video_id), *kept])
    return urlunparse(("https", "www.youtube.com", "/watch", "", query, ""))


def _youtube_video_id(parsed_path: str, query: dict[str, str], host: str) -> str | None:
    path_parts = [part for part in parsed_path.split("/") if part]
    if host in _YOUTUBE_SHORT_HOSTS:
        return path_parts[0] if path_parts else None
    if parsed_path == "/watch":
        return query.get("v")
    if len(path_parts) >= 2 and path_parts[0] in {"embed", "shorts", "live"}:
        return path_parts[1]
    return None


def normalize_video_url(url: str) -> NormalizedVideoUrl:
    raw = str(url or "").strip()
    if not raw:
        raise ValueError("Video URL is required")

    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Video URL must be an http(s) URL")

    host = _clean_host(parsed.hostname)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query = {key: value for key, value in query_pairs}
    timestamp = _parse_timestamp(query.get("t") or query.get("start") or query.get("time_continue"))

    if host in _YOUTUBE_HOSTS or host in _YOUTUBE_SHORT_HOSTS:
        video_id = _youtube_video_id(parsed.path, query, host)
        if not video_id or not _VIDEO_ID_RE.match(video_id):
            raise ValueError("YouTube URL does not contain a valid video id")
        return NormalizedVideoUrl(
            kind="youtube",
            original_url=raw,
            canonical_url=_canonical_youtube_url(video_id, query_pairs),
            video_id=video_id,
            timestamp_seconds=timestamp,
        )

    canonical = urlunparse(parsed._replace(scheme=scheme, fragment=""))
    return NormalizedVideoUrl(kind="external", original_url=raw, canonical_url=canonical)


__all__ = ["NormalizedVideoUrl", "normalize_video_url"]
