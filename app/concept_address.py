"""Concept address + multi-course badge (P1, pure, 0 LLM).

North star: every concept stop can be labeled ``"{course} · {lesson}"``.
Uses ``courses[]`` / document top-folders, ``part_of`` → lesson nodes, and
document path fallbacks. Never invents paths that are not in the graph.
"""

from __future__ import annotations

import os
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


def top_folder_from_path(path: str) -> str:
    """First path segment of a relative document path (course folder)."""
    raw = str(path or "").replace("\\", "/").strip().strip("/")
    if not raw or "/" not in raw:
        return ""
    return raw.split("/", 1)[0].strip()


def courses_from_documents(documents: Iterable[Any] | None) -> list[str]:
    """Unique top-folders from document paths, sorted."""
    found: set[str] = set()
    for raw in documents or []:
        top = top_folder_from_path(str(raw or ""))
        if top:
            found.add(top)
    return sorted(found)


def multi_course_badge_label(courses: Sequence[str] | None) -> str | None:
    """Learner-facing badge when a concept appears in ≥2 courses."""
    unique = sorted({str(c).strip() for c in (courses or []) if str(c).strip()})
    if len(unique) < 2:
        return None
    return f"в {len(unique)} курсах"


def multi_course_source_list(courses: Sequence[str] | None) -> list[str]:
    """Stable list of course names for chips / clickable sources."""
    return sorted({str(c).strip() for c in (courses or []) if str(c).strip()})


def _is_lesson_ref(concept_id: str, node: Mapping[str, Any] | None) -> bool:
    if str(concept_id or "").startswith("lesson:"):
        return True
    if not isinstance(node, Mapping):
        return False
    if str(node.get("level") or "").strip().lower() == "lesson":
        return True
    return bool(node.get("is_lesson"))


def _lesson_course(lesson_id: str, lesson: Mapping[str, Any]) -> str:
    course = str(lesson.get("course") or "").strip()
    if course:
        return course
    docs = list(lesson.get("documents") or lesson.get("related_documents") or [])
    tops = courses_from_documents(docs)
    if tops:
        return tops[0]
    # lesson:course-a-lesson-1 style slug — no reliable reverse; leave empty
    return ""


def build_part_of_lesson_index(
    concepts: Mapping[str, Any] | None,
    typed_relations: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Map concept_id → list of ``{lesson_id, label, course}`` via ``part_of``."""
    concepts = concepts or {}
    out: dict[str, list[dict[str, str]]] = {}
    for rel in typed_relations or []:
        if not isinstance(rel, Mapping):
            continue
        if str(rel.get("relation_type") or "").strip() != "part_of":
            continue
        src = str(rel.get("source_concept_id") or "").strip()
        tgt = str(rel.get("target_concept_id") or "").strip()
        if not src or not tgt:
            continue
        lesson = concepts.get(tgt)
        if not isinstance(lesson, Mapping):
            # Accept lesson targets even if missing from concepts dict (id prefix).
            if not str(tgt).startswith("lesson:"):
                continue
            lesson = {}
        elif not _is_lesson_ref(tgt, lesson):
            continue
        label = str(lesson.get("label") or tgt).strip() or tgt
        course = _lesson_course(tgt, lesson)
        row = {"lesson_id": tgt, "label": label, "course": course}
        bucket = out.setdefault(src, [])
        if row not in bucket:
            bucket.append(row)
    return out


def _primary_doc_address(documents: Sequence[Any] | None) -> str:
    docs = [str(d).replace("\\", "/").strip() for d in (documents or []) if str(d).strip()]
    if not docs:
        return ""
    primary = docs[0]
    parts = [p for p in PurePosixPath(primary).parts if p]
    if len(parts) >= 2:
        stem = os.path.splitext(parts[-1])[0].replace("_", " ").strip()
        return f"{parts[0]} · {stem}" if stem else parts[0]
    if parts:
        return os.path.splitext(parts[0])[0].replace("_", " ").strip() or parts[0]
    return ""


def resolve_concept_address(
    concept_id: str,
    *,
    concept: Mapping[str, Any] | None = None,
    courses: Sequence[str] | None = None,
    lessons: Sequence[Mapping[str, str]] | None = None,
    is_lesson: bool | None = None,
) -> str:
    """Return a non-empty ``course · lesson`` style address when possible.

    Fallback chain (always tries to stay non-empty for north-star stops):
    1. lesson node → ``course · lesson_label``
    2. ``part_of`` lesson membership
    3. primary document path → ``course · stem``
    4. first course · concept label
    5. concept label / concept_id
    """
    cid = str(concept_id or "").strip()
    concept = concept if isinstance(concept, Mapping) else {}
    label = str(concept.get("label") or cid).strip() or cid
    course_list = multi_course_source_list(courses)
    if not course_list:
        course_list = courses_from_documents(
            concept.get("documents") or concept.get("related_documents") or []
        )

    lesson_flag = (
        bool(is_lesson)
        if is_lesson is not None
        else _is_lesson_ref(cid, concept)
    )
    if lesson_flag:
        course = str(concept.get("course") or "").strip()
        if not course and course_list:
            course = course_list[0]
        if course and label:
            return f"{course} · {label}"
        return label or cid

    lesson_rows = [dict(r) for r in (lessons or []) if isinstance(r, Mapping)]
    if lesson_rows:
        chosen: Mapping[str, str] | None = None
        if course_list:
            for row in lesson_rows:
                if str(row.get("course") or "").strip() in course_list:
                    chosen = row
                    break
        if chosen is None:
            chosen = lesson_rows[0]
        course = str(chosen.get("course") or "").strip()
        lesson_label = str(chosen.get("label") or "").strip()
        if course and lesson_label:
            return f"{course} · {lesson_label}"
        if lesson_label:
            return lesson_label
        if course:
            return f"{course} · {label}" if label else course

    path_addr = _primary_doc_address(
        list(concept.get("documents") or concept.get("related_documents") or [])
    )
    if path_addr:
        return path_addr

    if course_list and label:
        return f"{course_list[0]} · {label}"
    return label or cid or "—"


def attach_addresses_to_nodes(
    nodes: list[dict[str, Any]],
    *,
    concepts: Mapping[str, Any] | None = None,
    typed_relations: Iterable[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Mutate render nodes in place: ``address``, ``courses_badge``; return same list."""
    concepts = concepts or {}
    membership = build_part_of_lesson_index(concepts, typed_relations)
    for nd in nodes:
        if not isinstance(nd, dict):
            continue
        cid = str(nd.get("id") or "").strip()
        courses = list(nd.get("courses") or [])
        if not courses:
            domain = concepts.get(cid) if isinstance(concepts.get(cid), Mapping) else {}
            courses = courses_from_documents(
                (domain or {}).get("documents")
                or (domain or {}).get("related_documents")
                or nd.get("related")
                or []
            )
            # related may be card dicts
            if not courses and isinstance(nd.get("related"), list):
                paths = []
                for card in nd["related"]:
                    if isinstance(card, Mapping):
                        paths.append(card.get("path") or "")
                    else:
                        paths.append(str(card))
                courses = courses_from_documents(paths)
            nd["courses"] = courses
        nd["courses_badge"] = multi_course_badge_label(courses)
        domain = concepts.get(cid) if isinstance(concepts.get(cid), Mapping) else {}
        nd["address"] = resolve_concept_address(
            cid,
            concept=domain or {
                "label": nd.get("label"),
                "level": nd.get("level"),
                "documents": [
                    (c.get("path") if isinstance(c, Mapping) else c)
                    for c in (nd.get("related") or [])
                ],
                "course": nd.get("course"),
            },
            courses=courses,
            lessons=membership.get(cid) or [],
            is_lesson=bool(nd.get("is_lesson")),
        )
    return nodes


def day_route_addresses(
    payload: Mapping[str, Any] | None,
) -> list[dict[str, str]]:
    """Compact ``{id, label, address}`` rows for every day_route stop."""
    payload = payload or {}
    by_id: dict[str, Mapping[str, Any]] = {}
    for n in payload.get("nodes") or []:
        if isinstance(n, Mapping):
            cid = str(n.get("id") or "").strip()
            if cid:
                by_id[cid] = n
    rows: list[dict[str, str]] = []
    for raw in payload.get("day_route") or []:
        cid = str(raw or "").strip()
        if not cid:
            continue
        n = by_id.get(cid) or {}
        addr = str(n.get("address") or "").strip()
        if not addr:
            addr = resolve_concept_address(
                cid,
                concept={"label": n.get("label"), "level": n.get("level")},
                courses=list(n.get("courses") or []),
                is_lesson=bool(n.get("is_lesson")),
            )
        rows.append(
            {
                "id": cid,
                "label": str(n.get("label") or cid),
                "address": addr,
            }
        )
    return rows


__all__ = [
    "attach_addresses_to_nodes",
    "build_part_of_lesson_index",
    "courses_from_documents",
    "day_route_addresses",
    "multi_course_badge_label",
    "multi_course_source_list",
    "resolve_concept_address",
    "top_folder_from_path",
]
