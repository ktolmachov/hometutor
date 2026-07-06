from __future__ import annotations

import pytest

from app.media_urls import normalize_video_url


def test_normalizes_youtube_watch_url_with_timestamp_and_query_params():
    normalized = normalize_video_url("https://www.youtube.com/watch?v=abcDEF12345&list=PL1&t=1m30s")

    assert normalized.kind == "youtube"
    assert normalized.video_id == "abcDEF12345"
    assert normalized.timestamp_seconds == 90
    assert normalized.canonical_url == "https://www.youtube.com/watch?v=abcDEF12345&list=PL1"
    assert normalized.with_timestamp() == "https://www.youtube.com/watch?v=abcDEF12345&list=PL1&t=90s"


def test_normalizes_youtu_be_url():
    normalized = normalize_video_url("https://youtu.be/abcDEF12345?t=75")

    assert normalized.kind == "youtube"
    assert normalized.video_id == "abcDEF12345"
    assert normalized.timestamp_seconds == 75
    assert normalized.canonical_url == "https://www.youtube.com/watch?v=abcDEF12345"


def test_normalizes_youtube_embed_url():
    normalized = normalize_video_url("https://www.youtube.com/embed/abcDEF12345?start=125")

    assert normalized.kind == "youtube"
    assert normalized.video_id == "abcDEF12345"
    assert normalized.timestamp_seconds == 125
    assert normalized.with_timestamp() == "https://www.youtube.com/watch?v=abcDEF12345&t=125s"


def test_youtube_embed_url_with_start():
    normalized = normalize_video_url("https://youtu.be/abcDEF12345?t=75")

    assert normalized.embed_url() == "https://www.youtube.com/embed/abcDEF12345?start=75"
    assert normalized.embed_url(120) == "https://www.youtube.com/embed/abcDEF12345?start=120"
    assert normalized.embed_url(0) == "https://www.youtube.com/embed/abcDEF12345"


def test_unknown_http_url_remains_external_link_without_timestamp_action():
    normalized = normalize_video_url("https://example.com/video.mp4?t=90#fragment")

    assert normalized.kind == "external"
    assert normalized.video_id is None
    assert normalized.timestamp_seconds is None
    assert normalized.canonical_url == "https://example.com/video.mp4?t=90"
    assert normalized.with_timestamp(120) == normalized.canonical_url


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///D:/lecture.mp4", "https://youtube.com/watch"])
def test_rejects_unsafe_or_invalid_video_urls(url: str):
    with pytest.raises(ValueError):
        normalize_video_url(url)
