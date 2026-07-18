"""P0-2b «Расписание области»: Каталог | Пересадки | Маршрут.

Streamlit shell over pure read-models (library_catalog_read + library_schedule_read
+ concept_address). Search filters tiles; empty states in every segment.
"""

from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from app.library_schedule_read import (
    SCHEDULE_SEGMENTS,
    ScheduleTile,
    build_area_summary_tile,
    build_concept_schedule_nodes,
    enrich_nodes_with_day_route,
    filter_tiles,
    list_catalog_course_tiles,
    list_route_tiles,
    list_transfer_tiles,
)
from app.ui.library_catalog import (
    activate_course_from_library,
    navigate_to_ask,
    render_library_catalog_body,
)
from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
from app.ui.widgets import render_panel_header
from app.ui_client import load_index_stats
from app.course_owner_order import (
    merge_owner_order_with_available,
    move_course_in_order,
    read_course_owner_order,
    write_course_owner_order,
)
from app.library_catalog_read import list_library_courses

_SEG_KEY = "library_schedule_segment"
_SEARCH_KEY = "library_schedule_search"
_PIN_KEY = "library_schedule_pins"


def _load_graph_bundle() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Best-effort active KG concepts + typed_relations (empty if unavailable)."""
    try:
        from app.knowledge_graph import get_active_knowledge_graph

        kg = get_active_knowledge_graph()
        concepts = kg.get_concepts() or {}
        rels = list(kg.get_typed_relations() or [])
        if not isinstance(concepts, dict):
            return {}, []
        return concepts, [r for r in rels if isinstance(r, dict)]
    except Exception:  # noqa: BLE001 - schedule degrades without graph
        return {}, []


def _optional_mastery_and_due() -> tuple[dict[str, float], list[str]]:
    mastery: dict[str, float] = {}
    due_ids: list[str] = []
    try:
        from app.knowledge_service import get_mastery_vector

        raw = get_mastery_vector() or {}
        mastery = {str(k): float(v) for k, v in dict(raw).items()}
    except Exception:  # noqa: BLE001
        mastery = {}
    try:
        from app.knowledge_graph import get_active_knowledge_graph
        from app.learner_state_scope import filter_due_reviews_for_kg

        for row in filter_due_reviews_for_kg(get_active_knowledge_graph(), limit=50) or []:
            if isinstance(row, Mapping):
                c = str(row.get("concept") or "").strip()
                if c:
                    due_ids.append(c)
    except Exception:  # noqa: BLE001
        due_ids = []
    return mastery, due_ids


def _build_schedule_context(
    index_stats: dict | None,
    *,
    owner_order: list[str] | None = None,
) -> dict[str, Any]:
    from app.course_lanes import enrich_nodes_with_course_lanes

    courses = list_library_courses(index_stats)
    available = [c.folder_rel for c in courses]
    owner = merge_owner_order_with_available(available, owner_order=owner_order)
    concepts, rels = _load_graph_bundle()
    nodes = build_concept_schedule_nodes(concepts, rels)
    enrich_nodes_with_course_lanes(nodes, owner_order=owner)
    mastery, due_ids = _optional_mastery_and_due()
    nodes, day_route = enrich_nodes_with_day_route(
        nodes,
        mastery_vector=mastery,
        due_concept_ids=due_ids,
        k=6,
    )
    transfers = list_transfer_tiles(nodes)
    route = list_route_tiles(nodes, day_route)
    catalog = list_catalog_course_tiles(index_stats, owner_order=owner)
    non_lesson = sum(1 for n in nodes if not n.get("is_lesson"))
    summary = build_area_summary_tile(
        index_stats=index_stats,
        course_count=len(courses),
        concept_count=non_lesson,
        transfer_count=len(transfers),
        route_stop_count=len(route),
    )
    return {
        "summary": summary,
        "catalog": catalog,
        "transfers": transfers,
        "route": route,
        "courses": courses,
        "owner_order": owner,
    }


def _render_course_order_panel(available: list[str], *, owner_order: list[str]) -> None:
    """Explicit owner order for hall lanes (does not write precedes)."""
    if len(available) < 2:
        return
    with st.expander("Порядок курсов (линии в зале)", expanded=False):
        st.caption(
            "Влияет на цвет линий в 3D (local/all) и порядок плиток. "
            "Не создаёт межкурсовые precedes — только presentation / recommend."
        )
        for i, rel in enumerate(owner_order):
            c1, c2, c3 = st.columns([0.15, 0.7, 0.15])
            with c1:
                st.caption(f"#{i + 1}")
            with c2:
                st.markdown(f"**{rel}**")
            with c3:
                up, down = st.columns(2)
                with up:
                    if st.button("↑", key=f"lib_ord_up_{i}", disabled=i == 0, help="Выше"):
                        new_order = move_course_in_order(owner_order, rel, delta=-1)
                        write_course_owner_order(st.session_state, new_order)
                        st.rerun()
                with down:
                    if st.button(
                        "↓",
                        key=f"lib_ord_dn_{i}",
                        disabled=i >= len(owner_order) - 1,
                        help="Ниже",
                    ):
                        new_order = move_course_in_order(owner_order, rel, delta=1)
                        write_course_owner_order(st.session_state, new_order)
                        st.rerun()
        if st.button("Сбросить порядок", key="lib_ord_reset"):
            write_course_owner_order(st.session_state, [])
            st.rerun()


def _render_tile_card(tile: ScheduleTile, *, key_prefix: str) -> None:
    """Single-column readable tile: quant → address → title → status → chips → CTA."""
    pinned = set(st.session_state.get(_PIN_KEY) or [])
    pin_key = tile.concept_id or tile.meta or tile.title
    is_pin = pin_key in pinned
    pin_mark = "★ " if is_pin else "☆ "
    quant_e, addr_e = _esc(tile.quant), _esc(tile.address)
    title_e, status_e = _esc(tile.title), _esc(tile.status)
    st.markdown(
        (
            '<div class="lib-sched-tile" style="'
            "border:1px solid rgba(120,130,150,0.28);border-radius:14px;"
            "padding:0.75rem 0.9rem;margin:0.35rem 0 0.55rem 0;"
            'background:rgba(120,130,150,0.06);">'
            f'<div style="font-size:0.72rem;opacity:0.75;letter-spacing:0.02em">{quant_e}</div>'
            f'<div style="font-size:0.78rem;margin-top:0.15rem;opacity:0.9">📍 {addr_e}</div>'
            f'<div style="font-size:1.02rem;font-weight:600;margin-top:0.2rem">{title_e}</div>'
            f'<div style="font-size:0.8rem;margin-top:0.2rem;opacity:0.85">{status_e}</div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )
    # Course chips (text + ask CTA) — status also as text above (not color-only).
    if tile.courses:
        chip_cols = st.columns(min(len(tile.courses), 4))
        for i, course in enumerate(tile.courses[:4]):
            with chip_cols[i]:
                st.caption(f"📂 {course}")
    c1, c2, c3 = st.columns(3)
    with c1:
        if tile.cta in {"ask", "ask_all"} and st.button(
            "Спросить",
            key=f"{key_prefix}_ask",
            width="stretch",
        ):
            folder = "" if tile.cta == "ask_all" else (tile.courses[0] if tile.courses else "")
            navigate_to_ask(folder)
            st.rerun()
    with c2:
        if tile.cta == "open_kg" and tile.concept_id and st.button(
            "В граф",
            key=f"{key_prefix}_kg",
            width="stretch",
        ):
            st.session_state["kg_selected_concept"] = tile.concept_id
            st.session_state["kg_action_concept"] = tile.concept_id
            st.session_state[PENDING_CURRENT_VIEW_KEY] = "Knowledge Graph"
            st.rerun()
        elif tile.cta == "activate" and tile.meta and st.button(
            "Активным",
            key=f"{key_prefix}_act",
            width="stretch",
            help="Сделать курс активным (явное действие).",
        ):
            from app.library_catalog_read import LibraryCourse

            activate_course_from_library(
                LibraryCourse(
                    folder_rel=tile.meta,
                    title=tile.title,
                    source_paths=tuple(tile.source_paths),
                )
            )
            st.rerun()
    with c3:
        label = f"{pin_mark}Снять" if is_pin else f"{pin_mark}Закрепить"
        if st.button(label, key=f"{key_prefix}_pin", width="stretch"):
            pins = set(st.session_state.get(_PIN_KEY) or [])
            if pin_key in pins:
                pins.discard(pin_key)
            else:
                pins.add(pin_key)
            st.session_state[_PIN_KEY] = sorted(pins)
            st.rerun()


def _esc(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_empty(segment: str) -> None:
    messages = {
        "Каталог": "Курсов в области пока нет. Добавьте материалы и обновите индекс.",
        "Пересадки": "Общих тем между курсами пока нет (нужен граф с multi-course concepts).",
        "Маршрут": "Маршрут дня пуст: нет due/frontier остановок. Пройдите квиз или откройте Knowledge Graph.",
    }
    st.info(messages.get(segment, "Ничего не найдено."))


def _render_tile_list(tiles: list[ScheduleTile], *, key_prefix: str) -> None:
    if not tiles:
        return
    for i, tile in enumerate(tiles):
        _render_tile_card(tile, key_prefix=f"{key_prefix}_{i}")


def _render_schedule_segment(
    segment: str,
    ctx: dict[str, Any],
    *,
    query: str,
    index_stats: dict,
) -> None:
    if segment == "Каталог":
        tiles = filter_tiles(ctx["catalog"], query)
        if query:
            if not tiles:
                st.warning("По запросу в каталоге ничего не найдено.")
            else:
                st.caption(f"Найдено курсов: {len(tiles)}")
                _render_tile_list(tiles, key_prefix="lib_cat_t")
        elif not ctx["catalog"]:
            _render_empty("Каталог")
        else:
            render_library_catalog_body(index_stats)
        return
    if segment == "Пересадки":
        tiles = filter_tiles(ctx["transfers"], query)
        if not tiles:
            _render_empty("Пересадки") if not query else st.warning(
                "По запросу пересадок не найдено."
            )
        else:
            st.caption(f"Общих тем: {len(tiles)}")
            _render_tile_list(tiles, key_prefix="lib_tr")
        return
    tiles = filter_tiles(ctx["route"], query)
    if not tiles:
        _render_empty("Маршрут") if not query else st.warning(
            "По запросу остановок не найдено."
        )
    else:
        st.caption(f"Остановок маршрута: {len(tiles)}")
        _render_tile_list(tiles, key_prefix="lib_rt")


def render_library_schedule(index_stats: dict | None = None) -> None:
    """Full schedule surface: summary + search + 3 segments."""
    if index_stats is None:
        index_stats = load_index_stats()
    if not isinstance(index_stats, dict):
        index_stats = {}

    st.markdown('<div class="panel lib-schedule">', unsafe_allow_html=True)
    render_panel_header(
        "Расписание области",
        "Каталог · пересадки · маршрут — одна поверхность без смены scope",
    )
    st.caption(
        "Поиск фильтрует плитки. Адрес «курс · урок» — тот же, что в Memory Run. "
        "Просмотр не активирует курс."
    )

    raw_owner = read_course_owner_order(st.session_state)
    courses_preview = list_library_courses(index_stats)
    available = [c.folder_rel for c in courses_preview]
    owner_order = merge_owner_order_with_available(available, owner_order=raw_owner)
    if owner_order and owner_order != raw_owner:
        write_course_owner_order(st.session_state, owner_order)

    _render_course_order_panel(available, owner_order=owner_order)
    ctx = _build_schedule_context(index_stats, owner_order=owner_order)
    _render_tile_card(ctx["summary"], key_prefix="lib_sum")

    query = st.text_input(
        "Поиск по расписанию",
        key=_SEARCH_KEY,
        placeholder="курс, тема, адрес…",
        help="Скрывает плитки, которые не содержат запрос.",
    ).strip()
    if _SEG_KEY not in st.session_state:
        st.session_state[_SEG_KEY] = SCHEDULE_SEGMENTS[0]
    segment = st.radio(
        "Сегмент",
        list(SCHEDULE_SEGMENTS),
        key=_SEG_KEY,
        horizontal=True,
        label_visibility="collapsed",
    )
    _render_schedule_segment(segment, ctx, query=query, index_stats=index_stats)
    st.markdown("</div>", unsafe_allow_html=True)


__all__ = [
    "render_library_schedule",
]
