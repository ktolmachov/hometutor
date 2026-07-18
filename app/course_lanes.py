"""P2: course color lanes + owner order (presentation / recommendations only).

Never invents cross-course ``precedes``. Owner order reorders recommendations
and lane paint order only.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from app.concept_address import multi_course_source_list

# Distinct hall tints (local|all). Stable palette — do not rely on CSS vars alone.
COURSE_LANE_PALETTE: tuple[str, ...] = (
    "#42e8e0",  # cyan
    "#b9f75b",  # lime
    "#ffc857",  # gold
    "#ff6b8a",  # coral
    "#9a6cff",  # violet
    "#67e8f9",  # sky
    "#f472b6",  # pink
    "#34d399",  # emerald
)

TRANSFER_HIGHLIGHT = "#ffc857"  # gold ring for multi-course nodes


def collect_courses_from_nodes(nodes: Iterable[Mapping[str, Any]] | None) -> list[str]:
    found: set[str] = set()
    for n in nodes or []:
        if not isinstance(n, Mapping):
            continue
        for c in multi_course_source_list(list(n.get("courses") or [])):
            found.add(c)
        primary = str(n.get("primary_course") or n.get("course") or "").strip()
        if primary:
            found.add(primary)
    return sorted(found)


def resolve_course_order(
    courses: Sequence[str],
    *,
    owner_order: Sequence[str] | None = None,
) -> list[str]:
    """Stable course list: owner pins first (as given), then remaining alpha.

    Used for lane index and recommendation order — never writes curriculum edges.
    """
    available = multi_course_source_list(list(courses or []))
    avail_set = set(available)
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in owner_order or []:
        name = str(raw or "").strip()
        if name and name in avail_set and name not in seen:
            ordered.append(name)
            seen.add(name)
    for name in available:
        if name not in seen:
            ordered.append(name)
            seen.add(name)
    return ordered


def lane_color_for_index(index: int) -> str:
    if not COURSE_LANE_PALETTE:
        return "#a5b4fc"
    return COURSE_LANE_PALETTE[int(index) % len(COURSE_LANE_PALETTE)]


def build_course_lane_legend(
    ordered_courses: Sequence[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, name in enumerate(ordered_courses):
        rows.append(
            {
                "course": name,
                "lane": i,
                "color": lane_color_for_index(i),
            }
        )
    return rows


def _primary_course(courses: Sequence[str], ordered: Sequence[str]) -> str:
    if not courses:
        return ""
    for c in ordered:
        if c in courses:
            return c
    return courses[0]


def enrich_nodes_with_course_lanes(
    nodes: list[dict[str, Any]],
    *,
    owner_order: Sequence[str] | None = None,
) -> list[dict[str, str | int | bool]]:
    """Mutate nodes: primary_course, course_lane, lane_color, is_transfer.

    Returns legend rows for hall/export. Does not touch typed_relations.
    """
    ordered = resolve_course_order(
        collect_courses_from_nodes(nodes),
        owner_order=owner_order,
    )
    index_by = {name: i for i, name in enumerate(ordered)}
    for nd in nodes:
        if not isinstance(nd, dict):
            continue
        courses = multi_course_source_list(list(nd.get("courses") or []))
        if not courses and nd.get("course"):
            courses = multi_course_source_list([str(nd.get("course"))])
        is_lesson = bool(nd.get("is_lesson"))
        is_transfer = (not is_lesson) and len(courses) >= 2
        primary = _primary_course(courses, ordered)
        lane = int(index_by.get(primary, 0)) if primary else 0
        nd["primary_course"] = primary
        nd["course_lane"] = lane
        nd["lane_color"] = lane_color_for_index(lane) if primary else ""
        nd["is_transfer"] = is_transfer
        if is_transfer:
            nd["transfer_color"] = TRANSFER_HIGHLIGHT
    return build_course_lane_legend(ordered)


def recommend_course_sequence(
    courses: Sequence[str],
    *,
    owner_order: Sequence[str] | None = None,
) -> list[str]:
    """Recommendation-only sequence (same rules as lane order)."""
    return resolve_course_order(courses, owner_order=owner_order)


def transfer_recommend_hint(
    concept_courses: Sequence[str],
    *,
    owner_order: Sequence[str] | None = None,
    from_course: str | None = None,
) -> str:
    """Human hint like «пересадка в Deep» — never a curriculum edge."""
    courses = multi_course_source_list(list(concept_courses or []))
    if len(courses) < 2:
        return ""
    ordered = recommend_course_sequence(courses, owner_order=owner_order)
    current = str(from_course or "").strip()
    targets = [c for c in ordered if c != current] if current else ordered[1:]
    if not targets:
        targets = [c for c in ordered if c != ordered[0]] if ordered else []
    if not targets:
        return ""
    return f"пересадка в {targets[0]}"


__all__ = [
    "COURSE_LANE_PALETTE",
    "TRANSFER_HIGHLIGHT",
    "build_course_lane_legend",
    "collect_courses_from_nodes",
    "enrich_nodes_with_course_lanes",
    "lane_color_for_index",
    "recommend_course_sequence",
    "resolve_course_order",
    "transfer_recommend_hint",
]
