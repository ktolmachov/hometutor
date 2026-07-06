"""Manifest contract for saved Living Konspekt artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.ingestion_sections import _parse_md_frontmatter
from app.media_alignment import compute_section_id
from app.media_sidecar import read_media_sidecar_pointer
from app.path_safety import resolve_data_relative_path, validate_data_relative_path
from app.section_index import ParsedSection
from app import workbench_service

MANIFEST_TYPE = "living-konspekt"
MANIFEST_VERSION = 1
ARTIFACTS_DIR_NAME = "living-konspekt"

_SLUG_RE = re.compile(r"[^\w\-]+", re.UNICODE)


@dataclass(frozen=True)
class ManifestPayload:
    artifact_id: str
    title: str
    created_at: str
    updated_at: str
    goal: Any
    rows: list[dict[str, Any]]
    section_anchors: list[dict[str, str]]
    sidecar_pointers: list[dict[str, str]]
    manifest_version: int = MANIFEST_VERSION
    type: str = MANIFEST_TYPE


@dataclass(frozen=True)
class SavedArtifact:
    path: Path
    artifact_id: str
    title: str
    updated_at: str
    section_count: int

    @property
    def name(self) -> str:
        return self.path.name


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def artifact_id_from_title(title: str) -> str:
    raw = title.strip().lower()
    slug = _SLUG_RE.sub("-", raw).strip("-")
    return slug or "konspekt"


def serialize_manifest(
    title: str,
    persisted_rows: list[dict[str, Any]],
    sidecar_pointers: list[dict[str, str]],
    *,
    artifact_id: str | None = None,
    goal: Any = None,
    section_anchors: list[dict[str, str]] | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> str:
    """Return YAML frontmatter for a Living Konspekt artifact."""
    now = _utc_now_iso()
    normalized_id = artifact_id_from_title(artifact_id or title)
    rows = [dict(row) for row in persisted_rows if isinstance(row, dict)]
    payload = {
        "type": MANIFEST_TYPE,
        "manifest_version": MANIFEST_VERSION,
        "artifact_id": normalized_id,
        "title": title.strip() or "Рабочий конспект",
        "created_at": created_at or now,
        "updated_at": updated_at or now,
        "goal": goal,
        "rows": rows,
        "section_anchors": (
            [_normalize_section_anchor(anchor) for anchor in section_anchors]
            if section_anchors is not None
            else collect_section_anchors(rows)
        ),
        "sidecar_pointers": [_normalize_sidecar_pointer(pointer) for pointer in sidecar_pointers],
    }
    return "---\n" + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False) + "---\n\n"


def parse_manifest(markdown_text: str) -> ManifestPayload | None:
    """Parse artifact frontmatter, or return None for non-Living-Konspekt markdown."""
    meta, _body = _parse_md_frontmatter(markdown_text)
    if meta.get("type") != MANIFEST_TYPE:
        return None

    version = _expect_int(meta.get("manifest_version"), "manifest_version")
    if version != MANIFEST_VERSION:
        raise ValueError("Unsupported artifact manifest version")

    rows = _expect_list(meta.get("rows"), "rows")
    row_dicts = [_expect_dict(row, "rows[]") for row in rows]
    raw_section_anchors = meta.get("section_anchors")
    sidecar_pointers = _expect_list(meta.get("sidecar_pointers"), "sidecar_pointers")
    return ManifestPayload(
        artifact_id=_expect_str(meta.get("artifact_id"), "artifact_id"),
        title=_expect_str(meta.get("title"), "title"),
        created_at=_expect_str(meta.get("created_at"), "created_at"),
        updated_at=_expect_str(meta.get("updated_at"), "updated_at"),
        goal=meta.get("goal"),
        rows=row_dicts,
        section_anchors=(
            [_normalize_section_anchor(anchor) for anchor in _expect_list(raw_section_anchors, "section_anchors")]
            if raw_section_anchors is not None
            else collect_section_anchors(row_dicts)
        ),
        sidecar_pointers=[_normalize_sidecar_pointer(pointer) for pointer in sidecar_pointers],
    )


def reassemble_rows(manifest: ManifestPayload) -> list[dict[str, Any]]:
    """Hydrate manifest persisted rows into runtime workbench rows."""
    return workbench_service.runtime_rows_from_persisted(manifest.rows)


def scan_saved_artifacts(vault_root: Path) -> list[SavedArtifact]:
    """Return saved Living Konspekt artifacts under the vault artifacts directory."""
    artifacts_dir = _artifacts_dir(vault_root)
    if not artifacts_dir.exists():
        return []

    artifacts: list[SavedArtifact] = []
    for path in sorted(artifacts_dir.rglob("*.md")):
        try:
            manifest = parse_manifest(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, UnicodeError, ValueError):
            continue
        if manifest is None:
            continue
        artifacts.append(
            SavedArtifact(
                path=path,
                artifact_id=manifest.artifact_id,
                title=manifest.title,
                updated_at=manifest.updated_at,
                section_count=len(manifest.rows),
            )
        )
    return sorted(artifacts, key=lambda item: (item.updated_at, item.name), reverse=True)


def find_artifact_path(vault_root: Path, artifact_id: str) -> Path | None:
    normalized_id = artifact_id_from_title(artifact_id)
    for artifact in scan_saved_artifacts(vault_root):
        if artifact.artifact_id == normalized_id:
            return artifact.path
    return None


def target_path_for_artifact(vault_root: Path, title: str, artifact_id: str | None = None) -> Path:
    normalized_id = artifact_id_from_title(artifact_id or title)
    existing = find_artifact_path(vault_root, normalized_id)
    if existing is not None:
        return existing
    return _artifacts_dir(vault_root) / f"{normalized_id}.md"


def collect_sidecar_pointers(
    persisted_rows: list[dict[str, Any]],
    *,
    data_dir: Path | None = None,
) -> list[dict[str, str]]:
    """Collect source konspekt media_sidecar pointers referenced by persisted rows."""
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


def collect_section_anchors(persisted_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Compute stable content anchors for manifest rows without changing row v2."""
    anchors: list[dict[str, str]] = []
    for row in persisted_rows:
        if not isinstance(row, dict):
            continue
        row_key = str(row.get("row_key") or "").strip()
        if not row_key:
            continue
        try:
            section = ParsedSection(
                heading_text=str(row.get("heading_text") or ""),
                slug=str(row.get("slug") or ""),
                level=int(row.get("level") or 0),
                line_start=int(row.get("line_start") or 0),
                line_end=int(row.get("line_end") or 0),
                text=str(row.get("text") or ""),
                own_text=str(row.get("own_text") or ""),
            )
        except (TypeError, ValueError):
            continue
        anchors.append(
            {
                "row_key": row_key,
                "section_id": compute_section_id(section),
                "anchor_status": "snapshot",
            }
        )
    return anchors


def _artifacts_dir(vault_root: Path) -> Path:
    return Path(vault_root) / ARTIFACTS_DIR_NAME


def _normalize_section_anchor(value: Any) -> dict[str, str]:
    anchor = _expect_dict(value, "section_anchors[]")
    section_id = _expect_str(anchor.get("section_id"), "section_anchors[].section_id")
    if not section_id.startswith("sha256:"):
        raise ValueError("section_anchors[].section_id must start with sha256:")
    return {
        "row_key": _expect_str(anchor.get("row_key"), "section_anchors[].row_key"),
        "section_id": section_id,
        "anchor_status": str(anchor.get("anchor_status") or "snapshot"),
    }


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
    "artifact_id_from_title",
    "collect_section_anchors",
    "collect_sidecar_pointers",
    "find_artifact_path",
    "parse_manifest",
    "reassemble_rows",
    "scan_saved_artifacts",
    "serialize_manifest",
    "target_path_for_artifact",
]
