"""Area library read-model: courses → konspekts → sections (0 LLM, 0 storage).

Shared pure API for the Streamlit «Библиотека» view (P0-2a) and the future
agent ``catalog.list`` tool (P1). Reuses existing resolvers only:
``build_mission_control_course_options``, ``scan_konspekts`` / staleness,
``build_section_index`` / ``parse_sections``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.config import DATA_DIR
from app.course_cache import build_mission_control_course_options
from app.konspekt_discovery import (
    KonspektMeta,
    konspekt_source_staleness,
    scan_konspekts,
)
from app.path_safety import data_relative_from_path, resolve_data_relative_path


@dataclass(frozen=True)
class LibraryCourse:
    folder_rel: str
    title: str
    source_paths: tuple[str, ...]
    needs_reindex: bool = False
    supported_file_count: int | None = None


@dataclass(frozen=True)
class LibraryKonspekt:
    path_rel: str
    path_abs: str
    title: str
    source: str
    presentation: str | None
    generated: str | None
    tags: tuple[str, ...]
    staleness: str | None  # "fresh" | "stale" | None
    badge: str | None


@dataclass(frozen=True)
class LibrarySection:
    heading_text: str
    slug: str
    level: int
    line_start: int
    line_end: int


def _normalize_folder_rel(folder_rel: str) -> str:
    return str(folder_rel or "").strip().replace("\\", "/").strip("/")


def _course_dir(folder_rel: str, *, data_dir: Path) -> Path | None:
    rel = _normalize_folder_rel(folder_rel)
    if not rel:
        return None
    try:
        path = resolve_data_relative_path(rel, data_dir=data_dir)
    except ValueError:
        return None
    return path if path.is_dir() else None


def _safe_data_rel(path: Path, *, data_dir: Path) -> str:
    try:
        return data_relative_from_path(path, data_dir=data_dir)
    except ValueError:
        return path.name


def list_library_courses(
    index_stats: Mapping[str, Any] | None = None,
) -> list[LibraryCourse]:
    """Courses of the current index area (same resolver as Mission Control)."""
    raw = build_mission_control_course_options(
        dict(index_stats) if isinstance(index_stats, Mapping) else None
    )
    out: list[LibraryCourse] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        folder_rel = _normalize_folder_rel(str(item.get("folder_rel") or ""))
        if not folder_rel or folder_rel in seen:
            continue
        seen.add(folder_rel)
        paths_raw = item.get("source_paths") or []
        source_paths = tuple(
            str(p).strip().replace("\\", "/")
            for p in paths_raw
            if str(p).strip()
        )
        count_raw = item.get("supported_file_count")
        try:
            supported = int(count_raw) if count_raw is not None else None
        except (TypeError, ValueError):
            supported = None
        title = str(item.get("title") or folder_rel).strip() or folder_rel
        # Drop redundant "Курс: " prefix for display when present.
        if title.casefold().startswith("курс:"):
            title = title.split(":", 1)[1].strip() or folder_rel
        out.append(
            LibraryCourse(
                folder_rel=folder_rel,
                title=title,
                source_paths=source_paths,
                needs_reindex=bool(item.get("needs_reindex")),
                supported_file_count=supported,
            )
        )
    return out


def _konspekt_title(km: KonspektMeta) -> str:
    stem = km.path.stem.replace("_", " ").strip()
    return stem or km.path.name


def list_library_konspekts(
    folder_rel: str,
    *,
    data_dir: Path | str | None = None,
) -> list[LibraryKonspekt]:
    """Vault konspekts under a course folder (``type: konspekt``), with staleness."""
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    course_dir = _course_dir(folder_rel, data_dir=root)
    if course_dir is None:
        return []
    items: list[LibraryKonspekt] = []
    for km in scan_konspekts(course_dir):
        path_rel = _safe_data_rel(km.path, data_dir=root)
        staleness = konspekt_source_staleness(km, data_dir=root)
        badge = "🕰 устарел" if staleness == "stale" else None
        items.append(
            LibraryKonspekt(
                path_rel=path_rel,
                path_abs=str(km.path),
                title=_konspekt_title(km),
                source=str(km.source or ""),
                presentation=km.presentation,
                generated=km.generated,
                tags=tuple(km.tags or ()),
                staleness=staleness,
                badge=badge,
            )
        )
    items.sort(key=lambda item: item.title.casefold())
    return items


def list_library_sections(
    konspekt_path: str | Path,
    *,
    data_dir: Path | str | None = None,
) -> list[LibrarySection]:
    """Addressable sections of a konspekt (or any markdown path)."""
    from app.section_index import build_section_index, parse_sections

    raw = str(konspekt_path or "").strip()
    if not raw:
        return []

    root = Path(data_dir) if data_dir is not None else DATA_DIR
    path: Path | None = None
    try:
        # Prefer data-relative resolution when caller passes a rel path.
        if not Path(raw).is_absolute():
            path = resolve_data_relative_path(raw, data_dir=root)
        else:
            path = Path(raw)
    except ValueError:
        path = Path(raw)

    sections_raw: list[Any] = []
    try:
        indexed = build_section_index(path if path is not None else raw)
        if indexed:
            sections_raw = list(indexed)
    except Exception:  # noqa: BLE001 - section index is best-effort; fall back to parse
        sections_raw = []

    if not sections_raw and path is not None and path.is_file():
        try:
            sections_raw = list(parse_sections(path))
        except Exception:  # noqa: BLE001 - unreadable md → empty sections list
            sections_raw = []

    out: list[LibrarySection] = []
    for sec in sections_raw:
        out.append(
            LibrarySection(
                heading_text=str(getattr(sec, "heading_text", "") or ""),
                slug=str(getattr(sec, "slug", "") or ""),
                level=int(getattr(sec, "level", 0) or 0),
                line_start=int(getattr(sec, "line_start", 0) or 0),
                line_end=int(getattr(sec, "line_end", 0) or 0),
            )
        )
    return out


def library_ask_folder_rel(folder_rel: str | None) -> str:
    """Folder filter for Q&A: course folder, or empty string for whole area."""
    return _normalize_folder_rel(folder_rel or "")


def library_browse_does_not_require_scope() -> bool:
    """Contract marker: read-model never touches study scope."""
    return True


__all__ = [
    "LibraryCourse",
    "LibraryKonspekt",
    "LibrarySection",
    "library_ask_folder_rel",
    "library_browse_does_not_require_scope",
    "list_library_courses",
    "list_library_konspekts",
    "list_library_sections",
]
