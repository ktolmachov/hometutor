"""Saved Living Konspekt artifact contract and deterministic body builders."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app import workbench_service
from app.config import DATA_DIR
from app.ingestion_sections import _parse_md_frontmatter
from app.media_alignment import compute_section_id
from app.media_sidecar import (
    UrlVideoSource,
    load_media_sidecar_for_konspekt,
    read_media_sidecar_pointer,
    sidecar_stale_reasons as _sidecar_stale_reasons,
)
from app.media_urls import normalize_video_url
from app.path_safety import resolve_data_relative_path, validate_data_relative_path
from app.section_index import ParsedSection, parse_sections

MANIFEST_TYPE = "living-konspekt"
MANIFEST_VERSION = 1
ARTIFACTS_DIR_NAME = "living-konspekt"

_MAX_CHECK_QUESTIONS = 8
_SLUG_RE = re.compile(r"[^\w\-]+", re.UNICODE)
# Поля portable-строк, восстанавливаемые из источника при reassemble — не хранятся
# в манифесте, чтобы не дублировать контент лекции (97% размера артефакта раньше).
_SLIM_PORTABLE_DROP_FIELDS = ("text", "own_text")


@dataclass(frozen=True)
class ManifestPayload:
    artifact_id: str
    title: str
    created_at: str
    updated_at: str
    goal: Any
    rows: list[dict[str, Any]]
    sidecar_pointers: list[dict[str, str]]
    manifest_version: int = MANIFEST_VERSION
    type: str = MANIFEST_TYPE


@dataclass(frozen=True)
class SavedArtifact:
    path: Path
    artifact_id: str | None
    title: str
    updated_at: str
    section_count: int
    has_manifest: bool

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def can_reassemble(self) -> bool:
        return self.has_manifest and bool(self.artifact_id)


import ntpath
import os


def _rewrite_image_paths_for_artifact(text: str, doc_dir: Path) -> str:
    from app.obsidian_export import vault_root

    try:
        artifacts_dir = (vault_root() / "living-konspekt").resolve()
    except Exception:
        from app.config import DATA_DIR
        artifacts_dir = (DATA_DIR / "living-konspekt").resolve()

    def replacer(match: re.Match) -> str:
        alt = match.group(1)
        path_str = match.group(2).strip()

        if path_str.startswith(("http://", "https://", "data:")):
            return match.group(0)

        doc_dir_raw = str(doc_dir).replace("\\", "/")
        if re.match(r"^[A-Za-z]:/", doc_dir_raw):
            img_path = ntpath.normpath(ntpath.join(doc_dir_raw, path_str.replace("\\", "/")))
            doc_parts = doc_dir_raw.split("/")
            data_idx = next((i for i, part in enumerate(doc_parts) if part.lower() == "data"), len(doc_parts) - 1)
            artifacts_win = ntpath.normpath("/".join([*doc_parts[: data_idx + 1], ARTIFACTS_DIR_NAME]))
            rel_path = ntpath.relpath(img_path, artifacts_win)
            rel_path_posix = rel_path.replace("\\", "/")
            return f"![{alt}]({rel_path_posix})"

        img_path = (doc_dir / path_str).resolve()
        try:
            rel_path = os.path.relpath(img_path, artifacts_dir)
            rel_path_posix = rel_path.replace("\\", "/")
            return f"![{alt}]({rel_path_posix})"
        except Exception:
            return match.group(0)

    img_re = re.compile(r"!\[(.*?)\]\((.*?)\)")
    return img_re.sub(replacer, text)


def build_artifact_body(rows: list[dict[str, Any]]) -> str:
    """Build the deterministic readable body for a saved Living Konspekt."""
    header_parts = [
        f"> **Главная мысль исходной лекции ({doc_name}):** {idea}"
        for doc_name, idea in _lecture_main_ideas(rows)
    ]

    sidecar_cache: dict[str, Any] = {}
    stale_cache: dict[str, list[str]] = {}
    parts: list[str] = []
    for row in rows:
        heading = str(row.get("heading_text") or "Без названия")
        source_name = _row_konspekt_label(row)
        location = f"{source_name}:{row.get('line_start')}"
        media_line = _media_line_for_row(row, sidecar_cache, stale_cache)
        source_block = f"*Источник: {location}*" + (f"\n\n{media_line}" if media_line else "")
        note = str(row.get("note") or "").strip()
        note_block = f"\n\n### 💬 Моими словами\n\n{note}" if note else ""
        q = str(row.get("open_question") or "").strip()
        q_block = f"\n\n### ❓ Мой открытый вопрос\n\n{q}" if q else ""
        # A2.3: status marker in caption (per plan)
        status = row.get("knowledge_status")
        status_marker = ""
        if status:
            status_label = {"understood": "Понял", "unsure": "Сомневаюсь", "unclear": "Не понял"}.get(status, status)
            status_marker = f" **[Статус: {status_label}]**"
        row_text = str(row.get("text") or "")
        md_abs = row.get("konspekt_md_abs")
        if md_abs:
            row_text = _rewrite_image_paths_for_artifact(row_text, Path(md_abs).parent)
        parts.append(f"## {heading}{status_marker}\n\n{source_block}\n\n{row_text}{note_block}{q_block}")

    blocks: list[str] = []
    if header_parts:
        blocks.append("\n>\n".join(header_parts))
    blocks.append("\n\n---\n\n".join(parts))
    videos = _videos_block(sidecar_cache)
    if videos:
        blocks.append(videos)
    tail = _study_pack_tail(rows)
    if tail:
        blocks.append(tail)
    return "\n\n".join(blocks)


def serialize_manifest(
    title: str,
    persisted_rows: list[dict[str, Any]],
    sidecar_pointers: list[dict[str, str]],
    *,
    artifact_id: str | None = None,
    goal: Any = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> str:
    """Return YAML frontmatter for artifact_manifest_v1."""
    now = _utc_now_iso()
    normalized_id = artifact_id_from_title(artifact_id or title)
    rows = [_row_with_section_id(row) for row in persisted_rows if isinstance(row, dict)]
    payload = {
        "type": MANIFEST_TYPE,
        "manifest_version": MANIFEST_VERSION,
        "artifact_id": normalized_id,
        "title": title.strip() or "Рабочий конспект",
        "created_at": created_at or now,
        "updated_at": updated_at or now,
        "goal": goal,
        "rows": rows,
        "sidecar_pointers": [_normalize_sidecar_pointer(pointer) for pointer in sidecar_pointers],
    }
    return "---\n" + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False) + "---\n\n"


def parse_manifest(markdown_text: str) -> ManifestPayload | None:
    """Parse a Living Konspekt artifact manifest, or return None for plain markdown."""
    meta, _body = _parse_md_frontmatter(markdown_text)
    if meta.get("type") != MANIFEST_TYPE:
        return None

    version = _expect_int(meta.get("manifest_version"), "manifest_version")
    if version != MANIFEST_VERSION:
        raise ValueError("Unsupported artifact manifest version")

    rows = [_normalize_manifest_row(row) for row in _expect_list(meta.get("rows"), "rows")]
    return ManifestPayload(
        artifact_id=_expect_str(meta.get("artifact_id"), "artifact_id"),
        title=_expect_str(meta.get("title"), "title"),
        created_at=_expect_str(meta.get("created_at"), "created_at"),
        updated_at=_expect_str(meta.get("updated_at"), "updated_at"),
        goal=meta.get("goal"),
        rows=rows,
        sidecar_pointers=[
            _normalize_sidecar_pointer(pointer)
            for pointer in _expect_list(meta.get("sidecar_pointers"), "sidecar_pointers")
        ],
    )


_PARSED_ARTIFACT_CACHE: dict[tuple[str, float, int], SavedArtifact] = {}


def scan_saved_artifacts(vault_root: Path) -> list[SavedArtifact]:
    """Return saved Living Konspekt artifacts, including plain files marked as such."""
    artifacts_dir = _artifacts_dir(vault_root)
    if not artifacts_dir.exists():
        return []

    artifacts: list[SavedArtifact] = []
    for path in sorted(artifacts_dir.rglob("*.md")):
        try:
            resolved_path = str(path.resolve())
            stat = path.stat()
            mtime = stat.st_mtime
            size = stat.st_size
            key = (resolved_path, mtime, size)
            if key in _PARSED_ARTIFACT_CACHE:
                artifacts.append(_PARSED_ARTIFACT_CACHE[key])
                continue

            text = path.read_text(encoding="utf-8", errors="replace")
            manifest = parse_manifest(text)
            if manifest is None:
                artifact = _manifestless_artifact(path)
            else:
                artifact = SavedArtifact(
                    path=path,
                    artifact_id=manifest.artifact_id,
                    title=manifest.title,
                    updated_at=manifest.updated_at,
                    section_count=len(manifest.rows),
                    has_manifest=True,
                )
            _PARSED_ARTIFACT_CACHE[key] = artifact
            artifacts.append(artifact)
        except (OSError, UnicodeError, ValueError):
            continue

    return sorted(artifacts, key=lambda item: (item.updated_at, item.name), reverse=True)



def resolve_artifact_path(vault_root: Path, artifact_id: str) -> Path | None:
    normalized_id = artifact_id_from_title(artifact_id)
    for artifact in scan_saved_artifacts(vault_root):
        if artifact.artifact_id == normalized_id:
            return artifact.path
    return None


def delete_saved_artifact(artifact_path: Path, vault_root: Path) -> None:
    """Delete a saved artifact file under ``vault_root/living-konspekt/``."""
    base = _artifacts_dir(Path(vault_root)).resolve()
    target = Path(artifact_path).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError("Artifact path is outside the living-konspekt directory") from exc
    if not target.is_file():
        raise FileNotFoundError(f"Artifact not found: {target.name}")
    target.unlink()


def reassemble_rows(
    manifest: ManifestPayload,
    *,
    data_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Hydrate manifest rows into runtime workbench rows with best-effort re-anchoring."""
    root = data_dir or DATA_DIR
    persisted_rows: list[dict[str, Any]] = []
    for row in manifest.rows:
        section_id = str(row.get("section_id") or "")
        persisted = {key: value for key, value in row.items() if key != "section_id"}
        if str(persisted.get("portability_status") or workbench_service.PORTABLE) == workbench_service.PORTABLE:
            persisted = _reanchor_or_snapshot(persisted, section_id, data_dir=root)
        persisted_rows.append(persisted)
    return workbench_service.runtime_rows_from_persisted(persisted_rows)


def collect_sidecar_pointers(
    persisted_rows: list[dict[str, Any]],
    *,
    data_dir: Path | None = None,
) -> list[dict[str, str]]:
    """Collect original konspekt media_sidecar pointers for unique manifest rows."""
    pointers: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in persisted_rows:
        if not isinstance(row, dict):
            continue
        md_rel_raw = row.get("konspekt_md_rel")
        if not md_rel_raw:
            continue
        try:
            md_rel = validate_data_relative_path(str(md_rel_raw), data_dir=data_dir)
        except ValueError:
            continue
        if md_rel in seen:
            continue
        seen.add(md_rel)
        try:
            markdown_text = resolve_data_relative_path(md_rel, data_dir=data_dir).read_text(
                encoding="utf-8",
                errors="replace",
            )
            pointer = read_media_sidecar_pointer(markdown_text, data_dir=data_dir)
        except (OSError, UnicodeError, ValueError):
            continue
        if pointer:
            pointers.append({"konspekt_md_rel": md_rel, "media_sidecar": pointer})
    return pointers


def save_artifact(
    title: str,
    body_markdown: str,
    rows: list[dict[str, Any]],
    *,
    artifact_id: str | None = None,
    goal: Any = None,
    save_as_new: bool = False,
    vault_root_path: Path | None = None,
) -> Path:
    """Persist a Living Konspekt artifact in the vault by stable artifact_id."""
    from app.obsidian_export import vault_root

    root = vault_root_path or vault_root()
    target_dir = _artifacts_dir(root)
    target_dir.mkdir(parents=True, exist_ok=True)
    normalized_id = _new_artifact_id(root, title) if save_as_new else artifact_id_from_title(artifact_id or title)
    target_path = target_path_for_artifact(root, title, normalized_id)
    previous_manifest = None
    if target_path.exists() and not save_as_new:
        previous_manifest = parse_manifest(target_path.read_text(encoding="utf-8", errors="replace"))

    persisted_rows = workbench_service.persisted_rows_from_runtime(rows)
    manifest = serialize_manifest(
        title,
        persisted_rows,
        collect_sidecar_pointers(persisted_rows),
        artifact_id=normalized_id,
        goal=goal if goal is not None else (previous_manifest.goal if previous_manifest is not None else None),
        created_at=previous_manifest.created_at if previous_manifest is not None else None,
    )
    target_path.write_text(f"{manifest}# {title}\n\n{body_markdown}\n", encoding="utf-8")
    return target_path


def target_path_for_artifact(vault_root: Path, title: str, artifact_id: str | None = None) -> Path:
    normalized_id = artifact_id_from_title(artifact_id or title)
    existing = resolve_artifact_path(vault_root, normalized_id)
    if existing is not None:
        return existing
    return _artifacts_dir(vault_root) / f"{normalized_id}.md"


def artifact_id_from_title(title: str) -> str:
    return _filename_slug(title)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _lecture_main_ideas(rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    try:
        from app.section_index import _cached_parse_sections, main_idea_section, sections_by_role
    except Exception:  # noqa: BLE001 - optional enrichment must not block artifact export
        return []

    out: list[tuple[str, str]] = []
    for md in _unique_md_paths(rows):
        try:
            parsed = _cached_parse_sections(Path(md))
        except OSError:
            continue
        main_idea = sections_by_role(parsed).get("main_idea") or main_idea_section(parsed)
        if main_idea is None or not main_idea.text.strip():
            continue
        first_paragraph = main_idea.text.strip().split("\n\n", 1)[0].strip()
        if first_paragraph:
            out.append((Path(md).name, first_paragraph))
    return out


def _sources_footer(rows: list[dict[str, Any]]) -> str:
    source_lines = [
        f"- {_row_konspekt_label(row)}:{row.get('line_start')}-{row.get('line_end')}"
        f" — «{row.get('heading_text') or '—'}»"
        for row in rows
    ]
    return "## Источники\n\n" + "\n".join(source_lines) if source_lines else ""


def _check_questions_block(rows: list[dict[str, Any]]) -> str:
    try:
        from app.section_index import _cached_parse_sections, sections_by_role
    except Exception:  # noqa: BLE001 - optional enrichment must not block artifact export
        return ""

    # Round-robin по документам: сборка из нескольких лекций получает вопросы из
    # каждой, а не только из первой сверху (retrieval practice по СВОЕЙ сборке).
    per_doc: list[list[str]] = []
    for md in _unique_md_paths(rows):
        try:
            parsed = _cached_parse_sections(Path(md))
        except OSError:
            continue
        section = sections_by_role(parsed).get("check_questions")
        if section is None:
            continue
        doc_questions = [line.strip() for line in section.text.splitlines() if line.strip()]
        if doc_questions:
            per_doc.append(doc_questions)
    if not per_doc:
        return ""
    questions: list[str] = []
    idx = 0
    while len(questions) < _MAX_CHECK_QUESTIONS:
        added_this_round = False
        for doc_questions in per_doc:
            if idx < len(doc_questions):
                questions.append(doc_questions[idx])
                added_this_round = True
                if len(questions) >= _MAX_CHECK_QUESTIONS:
                    break
        if not added_this_round:
            break
        idx += 1
    if not questions:
        return ""
    return "## ✅ Проверь себя\n\n" + "\n".join(questions)


def _study_pack_tail(rows: list[dict[str, Any]]) -> str:
    blocks = [block for block in (_check_questions_block(rows), _sources_footer(rows)) if block]
    return "\n\n".join(blocks)


def media_caption_line(
    t_start: float | int | None,
    t_end: float | int | None,
    video_title: str | None,
    youtube_url_with_t: str | None = None,
) -> str | None:
    if t_start is None:
        return None
    window = _format_timestamp(t_start) + (f"–{_format_timestamp(t_end)}" if t_end is not None else "")
    title = (video_title or "видео").strip() or "видео"
    if youtube_url_with_t:
        return f"*🎬 [{title} · {window}]({youtube_url_with_t})*"
    return f"*🎬 {title} · {window}*"


def _media_line_for_row(
    row: dict[str, Any],
    sidecar_cache: dict[str, Any],
    stale_cache: dict[str, list[str]] | None = None,
) -> str | None:
    md_abs = str(row.get("konspekt_md_abs") or "")
    if not md_abs:
        return None
    if md_abs not in sidecar_cache:
        try:
            sidecar_cache[md_abs] = load_media_sidecar_for_konspekt(Path(md_abs))
        except Exception:  # noqa: BLE001 - optional media must not block artifact export
            sidecar_cache[md_abs] = None
    sidecar = sidecar_cache[md_abs]
    if sidecar is None:
        return None
    media_section = _media_section_for_row(sidecar, row)
    if media_section is None or media_section.t_start is None or media_section.low_confidence:
        return None
    stale = stale_cache if stale_cache is not None else {}
    if md_abs not in stale:
        stale[md_abs] = _sidecar_stale_reasons(sidecar, md_abs)
    if stale[md_abs]:
        return None

    video = sidecar.video
    youtube_url: str | None = None
    title: str | None = getattr(video, "title", None)
    if isinstance(video, UrlVideoSource):
        try:
            normalized = normalize_video_url(video.url)
            if normalized.is_youtube:
                youtube_url = normalized.with_timestamp(media_section.t_start)
        except ValueError:
            youtube_url = None
    return media_caption_line(media_section.t_start, media_section.t_end, title, youtube_url)


def _videos_block(sidecar_cache: dict[str, Any]) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for sidecar in sidecar_cache.values():
        if sidecar is None:
            continue
        for video in sidecar.videos:
            if isinstance(video, UrlVideoSource):
                key = video.canonical_url or video.url
                label = (video.title or "").strip() or key
                entry = f"- [{label}]({key})"
            else:
                key = str(getattr(video, "path", ""))
                label = (getattr(video, "title", None) or Path(key).name or "видео").strip()
                entry = f"- {label} (`{Path(key).name}`)"
            if key and key not in seen:
                seen.add(key)
                lines.append(entry)
    return "## 🎬 Видео материалов\n\n" + "\n".join(lines) if lines else ""


def build_videos_block_for_rows(rows: list[dict[str, Any]]) -> str:
    """Блок «Видео материалов» по sidecar'ам документов корзины.

    Используется в LLM-режиме сборки (раньше медиа-слой терялся целиком: sidecar_cache
    не заполнялся и ``_videos_block`` оставался пустым). Дедуп по md-файлу: один sidecar
    на документ, независимо от числа разделов из него.
    """
    sidecar_cache: dict[str, Any] = {}
    for row in rows:
        md_abs = str(row.get("konspekt_md_abs") or "")
        if not md_abs or md_abs in sidecar_cache:
            continue
        try:
            sidecar_cache[md_abs] = load_media_sidecar_for_konspekt(Path(md_abs))
        except Exception:  # noqa: BLE001 - optional media must not block artifact export
            sidecar_cache[md_abs] = None
    return _videos_block(sidecar_cache)


def _filename_slug(title: str) -> str:
    raw = title.strip().lower()
    slug = _SLUG_RE.sub("-", raw).strip("-")
    return slug or "konspekt"


def _row_konspekt_label(row: dict[str, Any]) -> str:
    md_abs = str(row.get("konspekt_md_abs") or "")
    if md_abs:
        return Path(md_abs).name
    return str(row.get("konspekt_md_label") or row.get("konspekt_md_rel") or "недоступный конспект")


def _unique_md_paths(rows: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        md = str(row.get("konspekt_md_abs") or "")
        if md and md not in seen:
            seen.add(md)
            out.append(md)
    return out


def _row_with_section_id(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    # section_id считается по полному контенту ДО slimming-а — это стабильный якорь
    # привязки к источнику, переживает сдвиг line_start при редактировании конспекта.
    section = ParsedSection(
        heading_text=str(out.get("heading_text") or ""),
        slug=str(out.get("slug") or ""),
        level=int(out.get("level") or 0),
        line_start=int(out.get("line_start") or 0),
        line_end=int(out.get("line_end") or 0),
        text=str(out.get("text") or ""),
        own_text=str(out.get("own_text") or ""),
    )
    out["section_id"] = compute_section_id(section)
    # Portable-строки при reassemble полностью перепривязываются к источнику
    # (_reanchor_or_snapshot перечитывает text/own_text из md-файла). Хранить их в
    # манифесте = дублировать источник и раздувать артефакт (раньше 97% файла — YAML).
    # Non-portable снимки обязаны сохранять текст: источник для них недоступен.
    if str(out.get("portability_status") or workbench_service.PORTABLE) == workbench_service.PORTABLE:
        for field in _SLIM_PORTABLE_DROP_FIELDS:
            out.pop(field, None)
    return out


def _reanchor_or_snapshot(row: dict[str, Any], section_id: str, *, data_dir: Path) -> dict[str, Any]:
    md_rel = str(row.get("konspekt_md_rel") or "")
    if not md_rel or not section_id:
        return _non_portable_snapshot(row, "missing_anchor")
    try:
        md_abs = resolve_data_relative_path(md_rel, data_dir=data_dir)
    except ValueError:
        return _non_portable_snapshot(row, "resolve_failed")
    if not md_abs.exists():
        return _non_portable_snapshot(row, "source_missing")
    try:
        sections = parse_sections(md_abs)
    except OSError:
        return _non_portable_snapshot(row, "source_unreadable")

    for section in sections:
        if compute_section_id(section) == section_id:
            updated = dict(row)
            updated.update(
                {
                    "heading_text": section.heading_text,
                    "slug": section.slug,
                    "level": section.level,
                    "line_start": section.line_start,
                    "line_end": section.line_end,
                    "text": section.text,
                    "own_text": section.own_text,
                    "row_key": _portable_row_key(md_rel, section.line_start),
                }
            )
            return updated
    return _non_portable_snapshot(row, "section_anchor_missing")


def _non_portable_snapshot(row: dict[str, Any], resolve_error: str) -> dict[str, Any]:
    snapshot = dict(row)
    md_label = Path(str(snapshot.pop("konspekt_md_rel", "") or snapshot.get("konspekt_md_label") or "")).name
    source_label = Path(str(snapshot.pop("source_rel", "") or snapshot.get("source_label") or "")).name
    snapshot["portability_status"] = workbench_service.NON_PORTABLE
    snapshot["konspekt_md_label"] = md_label or "недоступный конспект"
    snapshot["source_label"] = source_label or "недоступный источник"
    snapshot["resolve_error"] = resolve_error
    snapshot["row_key"] = _non_portable_row_key(snapshot)
    return snapshot


def _portable_row_key(konspekt_md_rel: str, line_start: int) -> str:
    return f"p:{konspekt_md_rel}:{int(line_start or 0)}"


def _non_portable_row_key(row: dict[str, Any]) -> str:
    identity = {
        "konspekt_md_label": str(row.get("konspekt_md_label") or ""),
        "source_label": str(row.get("source_label") or ""),
        "heading_text": str(row.get("heading_text") or ""),
        "line_start": int(row.get("line_start") or 0),
        "line_end": int(row.get("line_end") or 0),
        "text": str(row.get("text") or ""),
    }
    payload = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"np:{digest}"


def _media_section_for_row(sidecar: Any, row: dict[str, Any]) -> Any | None:
    row_slug = str(row.get("slug") or "")
    row_heading = str(row.get("heading_text") or "")
    row_line_start = int(row.get("line_start") or 0)
    row_line_end = int(row.get("line_end") or 0)
    row_id = compute_section_id(
        ParsedSection(
            heading_text=row_heading,
            slug=row_slug,
            level=int(row.get("level") or 0),
            line_start=row_line_start,
            line_end=row_line_end,
            text=str(row.get("text") or ""),
            own_text=str(row.get("own_text") or ""),
        )
    )
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


def _new_artifact_id(vault_root: Path, title: str) -> str:
    base = artifact_id_from_title(title)
    if resolve_artifact_path(vault_root, base) is None:
        return base
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _artifacts_dir(vault_root: Path) -> Path:
    return Path(vault_root) / ARTIFACTS_DIR_NAME


def _manifestless_artifact(path: Path) -> SavedArtifact:
    try:
        updated = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0)
        updated_at = updated.isoformat().replace("+00:00", "Z")
    except OSError:
        updated_at = ""
    return SavedArtifact(
        path=path,
        artifact_id=None,
        title=path.stem,
        updated_at=updated_at,
        section_count=0,
        has_manifest=False,
    )


def _normalize_manifest_row(value: Any) -> dict[str, Any]:
    row = _expect_dict(value, "rows[]")
    section_id = _expect_str(row.get("section_id"), "rows[].section_id")
    if not section_id.startswith("sha256:"):
        raise ValueError("rows[].section_id must start with sha256:")
    row["section_id"] = section_id
    return row


def _normalize_sidecar_pointer(value: Any) -> dict[str, str]:
    pointer = _expect_dict(value, "sidecar_pointers[]")
    return {
        "konspekt_md_rel": validate_data_relative_path(
            _expect_str(pointer.get("konspekt_md_rel"), "sidecar_pointers[].konspekt_md_rel")
        ),
        "media_sidecar": validate_data_relative_path(
            _expect_str(pointer.get("media_sidecar"), "sidecar_pointers[].media_sidecar")
        ),
    }


def _expect_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return dict(value)


def _expect_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return list(value)


def _expect_str(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _expect_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


__all__ = [
    "ARTIFACTS_DIR_NAME",
    "MANIFEST_TYPE",
    "MANIFEST_VERSION",
    "ManifestPayload",
    "SavedArtifact",
    "_check_questions_block",
    "_filename_slug",
    "_media_line_for_row",
    "_row_konspekt_label",
    "_sources_footer",
    "_stitch_verbatim",
    "_study_pack_tail",
    "_videos_block",
    "artifact_id_from_title",
    "build_artifact_body",
    "build_videos_block_for_rows",
    "collect_sidecar_pointers",
    "delete_saved_artifact",
    "media_caption_line",
    "parse_manifest",
    "reassemble_rows",
    "resolve_artifact_path",
    "save_artifact",
    "scan_saved_artifacts",
    "serialize_manifest",
    "target_path_for_artifact",
]

# Backward-compatible local name for tests and legacy imports from the view.
_stitch_verbatim = build_artifact_body
