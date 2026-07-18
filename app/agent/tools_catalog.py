"""Agent tool: ``catalog.list`` — area library browse (P1, read-only).

Wraps the shared pure read-model from :mod:`app.library_catalog_read`
(same source as Streamlit «Библиотека»). No Streamlit imports. No LLM.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.agent.contracts import ToolArgModel, ToolContext, ToolResult, ToolSpec

logger = logging.getLogger(__name__)

_MAX_COURSES = 40
_MAX_KONSPEKTS = 40
_MAX_SECTIONS = 60
_MAX_RESULT_CHARS = 6000

CatalogLevel = Literal["courses", "konspekts", "sections", "auto"]


class CatalogListArgs(ToolArgModel):
    """Browse courses / konspekts / sections of the current data area.

    Paths in the result are relative to the data directory (never invent paths).
    """

    course: str | None = None
    query: str | None = None
    level: str | None = None  # courses | konspekts | sections | auto


def _norm(s: str | None) -> str:
    return str(s or "").strip()


def _matches_query(text: str, query: str) -> bool:
    if not query:
        return True
    return query.casefold() in str(text or "").casefold()


def _resolve_level(args: CatalogListArgs) -> str:
    raw = _norm(args.level).lower() or "auto"
    if raw in {"courses", "konspekts", "sections", "auto"}:
        return raw
    return "auto"


def _catalog_list_handler(ctx: ToolContext, args: ToolArgModel) -> ToolResult:
    assert isinstance(args, CatalogListArgs)
    try:
        from app.library_catalog_read import (
            list_library_courses,
            list_library_konspekts,
            list_library_sections,
        )

        course_filter = _norm(args.course)
        query = _norm(args.query)
        level = _resolve_level(args)

        # Prefer index folder options from query options when available.
        index_stats: dict[str, Any] | None = None
        folder_hint = ""
        try:
            opts = ctx.query_options
            folder_hint = _norm(getattr(opts, "folder_rel", None) or getattr(opts, "folder", None))
        except Exception:  # noqa: BLE001 - options shape is best-effort
            folder_hint = ""

        courses = list_library_courses(index_stats)
        if course_filter:
            cf = course_filter.casefold()
            courses = [
                c
                for c in courses
                if cf in c.folder_rel.casefold() or cf in c.title.casefold()
            ]
        elif folder_hint and level == "auto":
            # Soft bias: when Q&A already has a folder filter, surface it first.
            courses = sorted(
                courses,
                key=lambda c: (0 if c.folder_rel.casefold() == folder_hint.casefold() else 1, c.title.casefold()),
            )

        data: dict[str, Any] = {
            "level": level,
            "query": query or None,
            "course_filter": course_filter or None,
            "courses": [],
            "konspekts": [],
            "sections": [],
        }

        if level in {"courses", "auto"}:
            course_rows: list[dict[str, Any]] = []
            for c in courses[:_MAX_COURSES]:
                # Course filter already narrowed the set. Free-text query alone
                # may match the course name; with both, still list the course so
                # konspekt/section hits under it are explainable.
                if query and not course_filter and not _matches_query(
                    f"{c.title} {c.folder_rel}", query
                ):
                    continue
                course_rows.append(
                    {
                        "folder_rel": c.folder_rel,
                        "title": c.title,
                        "source_path_count": len(c.source_paths),
                        "needs_reindex": c.needs_reindex,
                    }
                )
            data["courses"] = course_rows

        need_konspekts = level in {"konspekts", "sections", "auto"} and (
            level != "auto" or course_filter or query or len(courses) <= 8
        )
        target_courses = courses
        if course_filter:
            target_courses = courses
        elif level in {"konspekts", "sections"} and courses:
            target_courses = courses[:8]

        if need_konspekts:
            konspekt_rows: list[dict[str, Any]] = []
            for c in target_courses[:12]:
                for km in list_library_konspekts(c.folder_rel):
                    hay = f"{km.title} {km.path_rel} {km.source} {' '.join(km.tags)} {c.folder_rel}"
                    # With a free-text query, match material text; course filter already narrowed set.
                    if query and not _matches_query(hay, query):
                        continue
                    konspekt_rows.append(
                        {
                            "course": c.folder_rel,
                            "course_title": c.title,
                            "path_rel": km.path_rel,
                            "title": km.title,
                            "source": km.source,
                            "staleness": km.staleness,
                            "badge": km.badge,
                            "tags": list(km.tags),
                        }
                    )
                    if len(konspekt_rows) >= _MAX_KONSPEKTS:
                        break
                if len(konspekt_rows) >= _MAX_KONSPEKTS:
                    break
            data["konspekts"] = konspekt_rows

        if level in {"sections", "auto"} and (level == "sections" or query):
            section_rows: list[dict[str, Any]] = []
            for krow in data.get("konspekts") or []:
                path_rel = str(krow.get("path_rel") or "")
                if not path_rel:
                    continue
                for sec in list_library_sections(path_rel):
                    if query and not _matches_query(sec.heading_text, query):
                        continue
                    section_rows.append(
                        {
                            "course": krow.get("course"),
                            "konspekt_path": path_rel,
                            "heading": sec.heading_text,
                            "slug": sec.slug,
                            "level": sec.level,
                            "line_start": sec.line_start,
                            "line_end": sec.line_end,
                            "address": f"{krow.get('course')} · {krow.get('title')} · {sec.heading_text}",
                        }
                    )
                    if len(section_rows) >= _MAX_SECTIONS:
                        break
                if len(section_rows) >= _MAX_SECTIONS:
                    break
            data["sections"] = section_rows

        # Honest empty: never invent paths
        data["counts"] = {
            "courses": len(data["courses"]),
            "konspekts": len(data["konspekts"]),
            "sections": len(data["sections"]),
        }
        return ToolResult.success(data=data, **data["counts"])
    except Exception as exc:  # noqa: BLE001 - tool boundary returns failure string
        logger.debug("agent.catalog_list_failed: %s", exc)
        return ToolResult.failure(f"catalog.list failed: {exc}")


CATALOG_LIST_SPEC = ToolSpec(
    name="catalog.list",
    description=(
        "Browse the area library: courses, vault konspekts (type:konspekt), and "
        "section headings. Returns real relative paths only — never invent paths. "
        "Use course filter for a specific course folder (e.g. Deep)."
    ),
    when_to_use=(
        "Use to find where a topic lives in a course or konspekt section "
        "(«найди раздел про X в Deep»), or to list courses without activating scope."
    ),
    args_schema=CatalogListArgs,
    limits={"max_result_chars": _MAX_RESULT_CHARS},
)


def get_catalog_tool_specs() -> list[tuple[ToolSpec, Any]]:
    return [(CATALOG_LIST_SPEC, _catalog_list_handler)]


__all__ = [
    "CATALOG_LIST_SPEC",
    "CatalogListArgs",
    "get_catalog_tool_specs",
]
