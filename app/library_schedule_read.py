"""P0-2b schedule read-model: area summary, transfers, day-route tiles (0 LLM).

Pure helpers for the «Расписание области» UI. Addresses use the same
:mod:`app.concept_address` north star as Memory Run / catalog.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.concept_address import (
    attach_addresses_to_nodes,
    courses_from_documents,
    multi_course_badge_label,
    multi_course_source_list,
    resolve_concept_address,
)
from app.knowledge_graph import is_lesson_node
from app.library_catalog_read import list_library_courses


SCHEDULE_SEGMENTS = ("Каталог", "Пересадки", "Маршрут")


@dataclass(frozen=True)
class ScheduleTile:
    """One schedule card (summary / transfer / route stop)."""

    kind: str
    title: str
    address: str
    status: str
    quant: str
    courses: tuple[str, ...]
    concept_id: str = ""
    cta: str = ""
    meta: str = ""


def tile_matches_query(tile: ScheduleTile, query: str) -> bool:
    q = str(query or "").strip().casefold()
    if not q:
        return True
    hay = " ".join(
        [
            tile.title,
            tile.address,
            tile.status,
            tile.quant,
            tile.meta,
            tile.concept_id,
            " ".join(tile.courses),
        ]
    ).casefold()
    return q in hay


def filter_tiles(tiles: Sequence[ScheduleTile], query: str) -> list[ScheduleTile]:
    return [t for t in tiles if tile_matches_query(t, query)]


def build_area_summary_tile(
    *,
    index_stats: Mapping[str, Any] | None = None,
    course_count: int | None = None,
    concept_count: int | None = None,
    transfer_count: int | None = None,
    route_stop_count: int | None = None,
) -> ScheduleTile:
    """«Вся область» summary — counts from index/graph, never hardcoded 82/8."""
    stats = index_stats if isinstance(index_stats, Mapping) else {}
    files = stats.get("files") or []
    file_n = len(files) if isinstance(files, list) else int(stats.get("document_count") or 0)
    courses_n = int(course_count if course_count is not None else 0)
    concepts_n = int(concept_count if concept_count is not None else 0)
    transfers_n = int(transfer_count if transfer_count is not None else 0)
    route_n = int(route_stop_count if route_stop_count is not None else 0)
    quant = f"{courses_n} курс. · {concepts_n} тем"
    status_bits = [f"{file_n} док. в индексе"]
    if transfers_n:
        status_bits.append(f"{transfers_n} пересадок")
    if route_n:
        status_bits.append(f"{route_n} остановок маршрута")
    return ScheduleTile(
        kind="summary",
        title="Вся область",
        address="область · все курсы",
        status=" · ".join(status_bits) or "индекс пуст",
        quant=quant,
        courses=(),
        cta="ask_all",
        meta="summary",
    )


def _concept_docs(node: Mapping[str, Any]) -> list[str]:
    raw = node.get("documents") or node.get("related_documents") or []
    return [str(x).strip() for x in raw if str(x).strip()]


def build_concept_schedule_nodes(
    concepts: Mapping[str, Any] | None,
    typed_relations: Iterable[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Lightweight render-nodes with courses + address (no mastery/worth required)."""
    concepts = concepts or {}
    nodes: list[dict[str, Any]] = []
    for cid, data in concepts.items():
        if not isinstance(data, Mapping):
            continue
        cid_s = str(cid).strip()
        if not cid_s:
            continue
        docs = _concept_docs(data)
        courses = courses_from_documents(docs)
        if not courses and data.get("course"):
            courses = [str(data.get("course")).strip()]
        lesson = is_lesson_node(cid_s, data)
        nodes.append(
            {
                "id": cid_s,
                "label": str(data.get("label") or cid_s),
                "level": data.get("level"),
                "courses": courses,
                "course": data.get("course"),
                "documents": docs,
                "is_lesson": bool(lesson),
                "due": 0,
                "frontier": False,
                "worth": 0.0,
                "worth_reason": "",
            }
        )
    attach_addresses_to_nodes(
        nodes,
        concepts=concepts,
        typed_relations=typed_relations,
    )
    return nodes


def list_transfer_tiles(
    nodes: Sequence[Mapping[str, Any]] | None,
    *,
    limit: int = 40,
) -> list[ScheduleTile]:
    """Shared themes: concepts present in ≥2 courses (not lesson anchors)."""
    tiles: list[ScheduleTile] = []
    for n in nodes or []:
        if not isinstance(n, Mapping):
            continue
        if n.get("is_lesson"):
            continue
        courses = multi_course_source_list(list(n.get("courses") or []))
        badge = str(n.get("courses_badge") or multi_course_badge_label(courses) or "").strip()
        if len(courses) < 2 and not badge:
            continue
        if len(courses) < 2:
            continue
        cid = str(n.get("id") or "").strip()
        title = str(n.get("label") or cid)
        address = str(n.get("address") or "").strip()
        if not address:
            address = resolve_concept_address(
                cid,
                concept={"label": title, "documents": n.get("documents") or []},
                courses=courses,
            )
        tiles.append(
            ScheduleTile(
                kind="transfer",
                title=title,
                address=address,
                status=badge or f"в {len(courses)} курсах",
                quant=f"{len(courses)} курса",
                courses=tuple(courses),
                concept_id=cid,
                cta="ask",
                meta="transfer",
            )
        )
    tiles.sort(key=lambda t: (-len(t.courses), t.title.casefold()))
    return tiles[: max(1, int(limit))]


def list_route_tiles(
    nodes: Sequence[Mapping[str, Any]] | None,
    day_route: Sequence[str] | None,
) -> list[ScheduleTile]:
    """Day-route stops with the same address format as transfers/catalog."""
    by_id: dict[str, Mapping[str, Any]] = {}
    for n in nodes or []:
        if isinstance(n, Mapping):
            cid = str(n.get("id") or "").strip()
            if cid:
                by_id[cid] = n
    tiles: list[ScheduleTile] = []
    route = [str(x).strip() for x in (day_route or []) if str(x).strip()]
    total = len(route)
    for idx, cid in enumerate(route, start=1):
        n = by_id.get(cid) or {}
        title = str(n.get("label") or cid)
        courses = multi_course_source_list(list(n.get("courses") or []))
        address = str(n.get("address") or "").strip()
        if not address:
            address = resolve_concept_address(
                cid,
                concept={"label": title, "documents": n.get("documents") or []},
                courses=courses,
                is_lesson=bool(n.get("is_lesson")),
            )
        reason = str(n.get("worth_reason") or "").strip()
        status = reason or ("пересадка" if len(courses) >= 2 else "в маршруте дня")
        worth = n.get("worth")
        quant = f"стоп {idx}/{total}"
        if isinstance(worth, (int, float)) and worth:
            quant = f"{quant} · W {float(worth):.1f}"
        tiles.append(
            ScheduleTile(
                kind="route",
                title=title,
                address=address,
                status=status,
                quant=quant,
                courses=tuple(courses),
                concept_id=cid,
                cta="open_kg",
                meta=f"route:{idx}",
            )
        )
    return tiles


def list_catalog_course_tiles(
    index_stats: Mapping[str, Any] | None = None,
) -> list[ScheduleTile]:
    """Course tiles for the catalog segment (same courses as library read-model)."""
    tiles: list[ScheduleTile] = []
    for c in list_library_courses(index_stats):
        n_docs = len(c.source_paths)
        status = "нужна переиндексация" if c.needs_reindex else "в индексе"
        if n_docs:
            status = f"{status} · {n_docs} док."
        tiles.append(
            ScheduleTile(
                kind="catalog_course",
                title=c.title,
                address=f"{c.folder_rel} · курс",
                status=status,
                quant=f"{n_docs} док.",
                courses=(c.folder_rel,),
                cta="activate",
                meta=c.folder_rel,
            )
        )
    return tiles


def enrich_nodes_with_day_route(
    nodes: list[dict[str, Any]],
    *,
    mastery_vector: Mapping[str, float] | None = None,
    due_concept_ids: Sequence[str] | None = None,
    k: int = 6,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Best-effort frontier/due flags + select_day_route (pure; no I/O)."""
    from app.ui.knowledge_graph_d3_analysis import select_day_route

    mastery = mastery_vector or {}
    due_set = {str(x).strip() for x in (due_concept_ids or []) if str(x).strip()}
    for nd in nodes:
        if not isinstance(nd, dict) or nd.get("is_lesson"):
            continue
        cid = str(nd.get("id") or "")
        m = float(mastery.get(cid) or 0.0)
        due_n = 1 if cid in due_set else 0
        nd["due"] = due_n
        # Lightweight frontier: not learned and low mastery (no full prereq graph here).
        nd["frontier"] = bool(m < 0.8 and due_n == 0)
        # Simple worth for ordering when full A2 stack is unavailable.
        nd["worth"] = float(due_n) * 3.0 + (1.5 if nd["frontier"] else 0.0) + (1.0 - m)
        if due_n:
            nd["worth_reason"] = "к повторению"
        elif nd["frontier"]:
            nd["worth_reason"] = "доступно"
        else:
            nd["worth_reason"] = "в маршруте дня"
    route = select_day_route(nodes, k=k)
    # If nothing actionable, keep empty — UI shows empty state (honest).
    return nodes, list(route)


__all__ = [
    "SCHEDULE_SEGMENTS",
    "ScheduleTile",
    "build_area_summary_tile",
    "build_concept_schedule_nodes",
    "enrich_nodes_with_day_route",
    "filter_tiles",
    "list_catalog_course_tiles",
    "list_route_tiles",
    "list_transfer_tiles",
    "tile_matches_query",
]
