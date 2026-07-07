from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.media_urls import normalize_video_url
from app.path_safety import resolve_data_relative_path, validate_data_relative_path

SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")
_SECTION_ID_RE = re.compile(r"^sha256:[a-fA-F0-9]{64}$")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<body>.*?)(?:\n|\r\n)---\s*(?:\n|\r\n)", re.DOTALL)
_MEDIA_SIDECAR_RE = re.compile(r"^media_sidecar:\s*[\"']?(?P<path>[^\"'\n#]+)[\"']?\s*$", re.MULTILINE)


@dataclass(frozen=True)
class GeneratedBy:
    tool: str
    created_at: str
    asr_model: str | None = None
    alignment_version: str | None = None
    # Полный fingerprint ASR-параметров из <video>.segments.json (asr.params):
    # участвует в stale detection — перетранскрибация с другими beam_size/language
    # обязана инвалидировать sidecar даже при неизменном media_sha256.
    asr_params: dict[str, Any] | None = None


@dataclass(frozen=True)
class LocalVideoSource:
    path: str
    sha256: str
    title: str | None = None
    duration_seconds: float | None = None
    codec: str | None = None
    kind: str = "local"


@dataclass(frozen=True)
class UrlVideoSource:
    url: str
    canonical_url: str | None = None
    title: str | None = None
    kind: str = "url"


VideoSource = LocalVideoSource | UrlVideoSource


@dataclass(frozen=True)
class MediaImage:
    path: str
    sha256: str | None = None
    caption: str | None = None
    source: str | None = None
    source_page: int | None = None
    t_start: float | None = None


@dataclass(frozen=True)
class MediaSection:
    section_id: str
    section_slug: str
    heading: str
    line_start: int
    line_end: int
    confidence: float
    t_start: float | None = None
    t_end: float | None = None
    images: tuple[MediaImage, ...] = field(default_factory=tuple)

    @property
    def has_timestamp(self) -> bool:
        return self.t_start is not None

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.70


@dataclass(frozen=True)
class MediaSemanticBlock:
    """Смысловой блок видео: узел смысла с настоящими границами темы.

    Пишется ``scripts/build_media_sidecar.py`` из детерминированной сегментации
    транскрипта (:func:`app.media_alignment.build_semantic_blocks`). ``keywords``
    — топ TF-IDF токенов блока; используется графом знаний (видео-моменты в
    граф-линзе) и плейлистами.
    """

    t_start: float
    t_end: float
    keywords: tuple[str, ...] = ()
    label: str | None = None


@dataclass(frozen=True)
class MediaSidecar:
    schema_version: int
    konspekt_sha256: str
    generated_by: GeneratedBy
    video: VideoSource
    sections: tuple[MediaSection, ...]
    media_sha256: str | None = None
    videos: tuple[VideoSource, ...] = field(default_factory=tuple)
    semantic_blocks: tuple[MediaSemanticBlock, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.videos:
            object.__setattr__(self, "videos", (self.video,))

    def stale_reasons(
        self,
        *,
        konspekt_sha256: str | None = None,
        media_sha256: str | None = None,
        asr_model: str | None = None,
        alignment_version: str | None = None,
        asr_params: dict[str, Any] | None = None,
        schema_version: int = SCHEMA_VERSION,
    ) -> list[str]:
        reasons: list[str] = []
        if self.schema_version != schema_version:
            reasons.append("schema_version")
        if konspekt_sha256 is not None and self.konspekt_sha256.lower() != konspekt_sha256.lower():
            reasons.append("konspekt_sha256")
        expected_media = media_sha256.lower() if media_sha256 is not None else None
        if expected_media is not None and (self.media_sha256 or "").lower() != expected_media:
            reasons.append("media_sha256")
        if asr_model is not None and self.generated_by.asr_model != asr_model:
            reasons.append("asr_model")
        if alignment_version is not None and self.generated_by.alignment_version != alignment_version:
            reasons.append("alignment_version")
        if asr_params is not None and self.generated_by.asr_params != asr_params:
            reasons.append("asr_params")
        return reasons

    def is_stale(self, **kwargs: Any) -> bool:
        return bool(self.stale_reasons(**kwargs))


_SHA256_FILE_CACHE: dict[tuple[str, float, int], str] = {}


def sha256_file(path: Path) -> str:
    try:
        resolved_path = str(path.resolve())
        stat = path.stat()
        mtime = stat.st_mtime
        size = stat.st_size
        key = (resolved_path, mtime, size)
        if key in _SHA256_FILE_CACHE:
            return _SHA256_FILE_CACHE[key]

        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        h = digest.hexdigest()
        _SHA256_FILE_CACHE[key] = h
        return h
    except OSError:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()



def sha256_konspekt_file(path: Path) -> str:
    """Content hash for media-sidecar invalidation.

    The frontmatter pointer to the sidecar is wiring metadata. It may be added by
    ``scripts/build_media_sidecar.py`` during generation and must not make the
    freshly generated sidecar stale.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    return hashlib.sha256(_strip_media_sidecar_pointer(text).encode("utf-8")).hexdigest()


def current_konspekt_sha256_for_sidecar(path: Path, sidecar_konspekt_sha256: str) -> str:
    """Return a comparable current hash while accepting legacy sidecar hashes."""
    normalized = sha256_konspekt_file(path)
    expected = sidecar_konspekt_sha256.lower()
    if expected == normalized:
        return normalized
    full = sha256_file(path)
    if expected == full:
        return full
    return normalized


def expected_asr_params(video_abs: Path) -> dict[str, Any] | None:
    """Ожидаемый fingerprint ASR из ``<video>.segments.json`` — источник истины для sidecar.

    Если сегменты перетранскрибированы с другими параметрами (beam_size/language/model),
    sidecar обязан считаться устаревшим даже при неизменном media_sha256.
    """
    segments_path = video_abs.with_suffix(".segments.json")
    if not segments_path.is_file():
        return None
    try:
        payload = json.loads(segments_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    params = (payload.get("asr") or {}).get("params")
    return params if isinstance(params, dict) else None


def sidecar_stale_reasons(sidecar: MediaSidecar, md_abs: str) -> list[str]:
    """Почему sidecar протух относительно konspekt-файла и/или медиа.

    Единая реализация для артефакта, медиа-панели UI и video-citations
    (раньше жила в трёх идентичных копиях). Делегирует хэш-вычисления
    :func:`sha256_file`/:func:`current_konspekt_sha256_for_sidecar`, у которых уже
    есть mtime/size-кэш, поэтому повторные вызовы на один документ дёшевы.
    """
    try:
        konspekt_sha = current_konspekt_sha256_for_sidecar(Path(md_abs), sidecar.konspekt_sha256)
    except OSError:
        konspekt_sha = None
    media_sha: str | None = None
    asr_params: dict[str, Any] | None = None
    if isinstance(sidecar.video, LocalVideoSource):
        try:
            video_abs = resolve_data_relative_path(sidecar.video.path)
            media_sha = sha256_file(video_abs)
            asr_params = expected_asr_params(video_abs)
        except (OSError, ValueError):
            media_sha = None
    from app.media_alignment import ALIGNMENT_VERSION

    alignment_version = (
        ALIGNMENT_VERSION if sidecar.generated_by.alignment_version is not None else None
    )

    # asr_params учитываем только если и sidecar, и segments-файл его знают:
    # ручные sidecar'ы (tool=manual) без fingerprint не должны стать stale задним числом.
    if asr_params is None or sidecar.generated_by.asr_params is None:
        return sidecar.stale_reasons(
            konspekt_sha256=konspekt_sha,
            media_sha256=media_sha,
            alignment_version=alignment_version,
        )
    return sidecar.stale_reasons(
        konspekt_sha256=konspekt_sha,
        media_sha256=media_sha,
        alignment_version=alignment_version,
        asr_params=asr_params,
    )


def _strip_media_sidecar_pointer(markdown_text: str) -> str:
    split = _split_frontmatter(markdown_text)
    if split is None:
        return markdown_text

    opening, frontmatter, closing, remainder = split
    lines = frontmatter.splitlines(keepends=True)
    kept = [line for line in lines if not _MEDIA_SIDECAR_RE.match(line.rstrip("\r\n"))]
    if kept == lines:
        return markdown_text

    if any(line.strip() for line in kept):
        return opening + "".join(kept) + closing + remainder
    if remainder.startswith("\r\n"):
        return remainder[2:]
    if remainder.startswith("\n"):
        return remainder[1:]
    return remainder


def _split_frontmatter(markdown_text: str) -> tuple[str, str, str, str] | None:
    if markdown_text.startswith("---\r\n"):
        start = 5
    elif markdown_text.startswith("---\n"):
        start = 4
    else:
        return None

    pos = start
    while pos < len(markdown_text):
        nl_pos = markdown_text.find("\n", pos)
        if nl_pos == -1:
            raw_line = markdown_text[pos:]
            line_end = len(markdown_text)
        else:
            raw_line = markdown_text[pos : nl_pos + 1]
            line_end = nl_pos + 1
        if raw_line.rstrip("\r\n") == "---":
            return markdown_text[:start], markdown_text[start:pos], raw_line, markdown_text[line_end:]
        pos = line_end
    return None


def read_media_sidecar_pointer(markdown_text: str, *, data_dir: Path | None = None) -> str | None:
    match = _FRONTMATTER_RE.match(markdown_text)
    if not match:
        return None
    pointer_match = _MEDIA_SIDECAR_RE.search(match.group("body"))
    if not pointer_match:
        return None
    return validate_data_relative_path(pointer_match.group("path").strip(), data_dir=data_dir)


_SIDECAR_LOAD_CACHE: dict[tuple[str, float, int, str], MediaSidecar | None] = {}


def load_media_sidecar_for_konspekt(konspekt_path: Path, *, data_dir: Path | None = None) -> MediaSidecar | None:
    # Каждый rerun Живого конспекта звал это по разу на строку × вкладку (до 48 раз
    # на документ). md (128 КБ) + sidecar JSON парсились каждый раз. Кэш по
    # (resolved path, mtime, size, data_dir) схлопывает повторы в один парс на документ;
    # инвалидируется автоматически при любой правке md.
    try:
        resolved = str(konspekt_path.resolve())
        stat = konspekt_path.stat()
        cache_key = (resolved, stat.st_mtime, stat.st_size, str(data_dir) if data_dir else "")
    except OSError:
        cache_key = None

    if cache_key is not None and cache_key in _SIDECAR_LOAD_CACHE:
        return _SIDECAR_LOAD_CACHE[cache_key]

    markdown_text = konspekt_path.read_text(encoding="utf-8", errors="replace")
    pointer = read_media_sidecar_pointer(markdown_text, data_dir=data_dir)
    if pointer is None:
        result = None
    else:
        result = load_media_sidecar(pointer, data_dir=data_dir)

    if cache_key is not None:
        _SIDECAR_LOAD_CACHE[cache_key] = result
    return result


def load_media_sidecar(relative_path: str, *, data_dir: Path | None = None) -> MediaSidecar:
    path = resolve_data_relative_path(relative_path, data_dir=data_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return parse_media_sidecar(payload, data_dir=data_dir)


def parse_media_sidecar(payload: dict[str, Any], *, data_dir: Path | None = None) -> MediaSidecar:
    _require_keys(payload, {"schema_version", "konspekt_sha256", "generated_by", "media", "sections"}, "sidecar")
    _reject_extra_keys(
        payload,
        {
            "schema_version",
            "konspekt_sha256",
            "media_sha256",
            "generated_by",
            "media",
            "sections",
            "semantic_blocks",
        },
        "sidecar",
    )
    schema_version = _expect_int(payload["schema_version"], "schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ValueError("Unsupported media sidecar schema version")
    konspekt_sha256 = _expect_sha256(payload["konspekt_sha256"], "konspekt_sha256")
    media_sha256 = _optional_sha256(payload.get("media_sha256"), "media_sha256")
    generated_by = _parse_generated_by(payload["generated_by"])
    video, videos = _parse_media(payload["media"], data_dir=data_dir)
    sections = tuple(_parse_section(item, data_dir=data_dir) for item in _expect_list(payload["sections"], "sections"))
    semantic_blocks: tuple[MediaSemanticBlock, ...] = ()
    if "semantic_blocks" in payload:
        semantic_blocks = tuple(
            _parse_semantic_block(item)
            for item in _expect_list(payload["semantic_blocks"], "semantic_blocks")
        )
    return MediaSidecar(
        schema_version=schema_version,
        konspekt_sha256=konspekt_sha256,
        generated_by=generated_by,
        video=video,
        sections=sections,
        media_sha256=media_sha256,
        videos=videos,
        semantic_blocks=semantic_blocks,
    )


def _require_keys(payload: dict[str, Any], keys: set[str], label: str) -> None:
    missing = sorted(key for key in keys if key not in payload)
    if missing:
        raise ValueError(f"{label} missing required keys: {', '.join(missing)}")


def _reject_extra_keys(payload: dict[str, Any], keys: set[str], label: str) -> None:
    extra = sorted(key for key in payload if key not in keys)
    if extra:
        raise ValueError(f"{label} has unsupported keys: {', '.join(extra)}")


def _expect_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _expect_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def _expect_str(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _expect_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def _expect_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    return float(value)


def _expect_sha256(value: Any, label: str) -> str:
    raw = _expect_str(value, label)
    if not _SHA256_RE.match(raw):
        raise ValueError(f"{label} must be a sha256 hex digest")
    return raw.lower()


def _optional_sha256(value: Any, label: str) -> str | None:
    return None if value is None else _expect_sha256(value, label)


def _parse_generated_by(value: Any) -> GeneratedBy:
    payload = _expect_dict(value, "generated_by")
    _require_keys(payload, {"tool", "created_at"}, "generated_by")
    _reject_extra_keys(
        payload,
        {"tool", "created_at", "asr_model", "alignment_version", "asr_params"},
        "generated_by",
    )
    asr_params = payload.get("asr_params")
    if asr_params is not None and not isinstance(asr_params, dict):
        raise ValueError("generated_by.asr_params must be an object")
    return GeneratedBy(
        tool=_expect_str(payload["tool"], "generated_by.tool"),
        created_at=_expect_str(payload["created_at"], "generated_by.created_at"),
        asr_model=_optional_str(payload.get("asr_model"), "generated_by.asr_model"),
        alignment_version=_optional_str(payload.get("alignment_version"), "generated_by.alignment_version"),
        asr_params=asr_params,
    )


def _optional_str(value: Any, label: str) -> str | None:
    return None if value is None else _expect_str(value, label)


def _parse_media(value: Any, *, data_dir: Path | None) -> tuple[VideoSource, tuple[VideoSource, ...]]:
    media = _expect_dict(value, "media")
    _reject_extra_keys(media, {"video", "videos"}, "media")
    video = _parse_video_source(media.get("video"), label="media.video", data_dir=data_dir)

    extra_videos: list[VideoSource] = []
    if "videos" in media:
        for idx, item in enumerate(_expect_list(media["videos"], "media.videos")):
            extra_videos.append(_parse_video_source(item, label=f"media.videos[{idx}]", data_dir=data_dir))

    return video, _dedupe_videos((video, *extra_videos))


def _dedupe_videos(videos: tuple[VideoSource, ...]) -> tuple[VideoSource, ...]:
    seen: set[tuple[str, str]] = set()
    deduped: list[VideoSource] = []
    for video in videos:
        key = ("local", video.path) if isinstance(video, LocalVideoSource) else ("url", video.canonical_url or video.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(video)
    return tuple(deduped)


def _parse_video_source(value: Any, *, label: str, data_dir: Path | None) -> VideoSource:
    video = _expect_dict(value, label)
    kind = _expect_str(video.get("kind"), f"{label}.kind")
    if kind == "local":
        _reject_extra_keys(video, {"kind", "title", "path", "sha256", "duration_seconds", "codec"}, label)
        path = validate_data_relative_path(_expect_str(video.get("path"), f"{label}.path"), data_dir=data_dir)
        return LocalVideoSource(
            path=path,
            sha256=_expect_sha256(video.get("sha256"), f"{label}.sha256"),
            title=_optional_str(video.get("title"), f"{label}.title"),
            duration_seconds=_optional_non_negative_number(video.get("duration_seconds"), f"{label}.duration_seconds"),
            codec=_optional_str(video.get("codec"), f"{label}.codec"),
        )
    if kind == "url":
        _reject_extra_keys(video, {"kind", "title", "url", "canonical_url"}, label)
        normalized = normalize_video_url(_expect_str(video.get("url"), f"{label}.url"))
        canonical_url = _optional_str(video.get("canonical_url"), f"{label}.canonical_url") or normalized.canonical_url
        return UrlVideoSource(
            url=normalized.original_url,
            canonical_url=canonical_url,
            title=_optional_str(video.get("title"), f"{label}.title"),
        )
    raise ValueError(f"{label}.kind must be local or url")


def _optional_non_negative_number(value: Any, label: str) -> float | None:
    if value is None:
        return None
    number = _expect_number(value, label)
    if number < 0:
        raise ValueError(f"{label} must be non-negative")
    return number


def _parse_section(value: Any, *, data_dir: Path | None) -> MediaSection:
    section = _expect_dict(value, "section")
    _require_keys(
        section,
        {"section_id", "section_slug", "heading", "line_start", "line_end", "confidence"},
        "section",
    )
    _reject_extra_keys(
        section,
        {
            "section_id",
            "section_slug",
            "heading",
            "line_start",
            "line_end",
            "t_start",
            "t_end",
            "confidence",
            "images",
        },
        "section",
    )
    line_start = _expect_int(section["line_start"], "section.line_start")
    line_end = _expect_int(section["line_end"], "section.line_end")
    if line_start < 1 or line_end < line_start:
        raise ValueError("section line range is invalid")
    confidence = _expect_number(section["confidence"], "section.confidence")
    if not 0 <= confidence <= 1:
        raise ValueError("section.confidence must be between 0 and 1")
    t_start = _optional_non_negative_number(section.get("t_start"), "section.t_start")
    t_end = _optional_non_negative_number(section.get("t_end"), "section.t_end")
    if t_start is not None and t_end is not None and t_end < t_start:
        raise ValueError("section timestamp range is invalid")
    section_id = _expect_str(section["section_id"], "section.section_id")
    if not _SECTION_ID_RE.match(section_id):
        raise ValueError("section.section_id must be sha256:<digest>")
    return MediaSection(
        section_id=section_id.lower(),
        section_slug=_expect_str(section["section_slug"], "section.section_slug"),
        heading=_expect_str(section["heading"], "section.heading"),
        line_start=line_start,
        line_end=line_end,
        confidence=confidence,
        t_start=t_start,
        t_end=t_end,
        images=tuple(_parse_image(item, data_dir=data_dir) for item in section.get("images") or []),
    )


def _parse_image(value: Any, *, data_dir: Path | None) -> MediaImage:
    image = _expect_dict(value, "image")
    _reject_extra_keys(
        image,
        {"path", "sha256", "caption", "source", "source_page", "t_start"},
        "image",
    )
    path = validate_data_relative_path(_expect_str(image.get("path"), "image.path"), data_dir=data_dir)
    return MediaImage(
        path=path,
        sha256=_optional_sha256(image.get("sha256"), "image.sha256"),
        caption=_optional_str(image.get("caption"), "image.caption"),
        source=_optional_str(image.get("source"), "image.source"),
        source_page=_optional_positive_int(image.get("source_page"), "image.source_page"),
        t_start=_optional_non_negative_number(image.get("t_start"), "image.t_start"),
    )


def _optional_positive_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    parsed = _expect_int(value, label)
    if parsed < 1:
        raise ValueError(f"{label} must be positive")
    return parsed


def _parse_semantic_block(value: Any) -> MediaSemanticBlock:
    block = _expect_dict(value, "semantic_block")
    _require_keys(block, {"t_start", "t_end"}, "semantic_block")
    _reject_extra_keys(block, {"t_start", "t_end", "keywords", "label"}, "semantic_block")
    t_start = _expect_number(block["t_start"], "semantic_block.t_start")
    t_end = _expect_number(block["t_end"], "semantic_block.t_end")
    if t_start < 0 or t_end < t_start:
        raise ValueError("semantic_block time range is invalid")
    keywords: tuple[str, ...] = ()
    if "keywords" in block:
        keywords = tuple(
            _expect_str(item, "semantic_block.keywords[]")
            for item in _expect_list(block["keywords"], "semantic_block.keywords")
        )
    return MediaSemanticBlock(
        t_start=t_start,
        t_end=t_end,
        keywords=keywords,
        label=_optional_str(block.get("label"), "semantic_block.label"),
    )


__all__ = [
    "GeneratedBy",
    "LocalVideoSource",
    "MediaImage",
    "MediaSection",
    "MediaSemanticBlock",
    "MediaSidecar",
    "SCHEMA_VERSION",
    "UrlVideoSource",
    "current_konspekt_sha256_for_sidecar",
    "load_media_sidecar",
    "load_media_sidecar_for_konspekt",
    "parse_media_sidecar",
    "read_media_sidecar_pointer",
    "sha256_konspekt_file",
    "sha256_file",
]
