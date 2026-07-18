"""P0-2b «Расписание области»: Каталог | Пересадки | Маршрут.

Streamlit shell over pure read-models (library_catalog_read + library_schedule_read
+ concept_address). Search filters tiles; empty states in every segment.
"""

from __future__ import annotations

import base64
import hashlib
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
)
from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
from app.ui.source_address import library_card_html, normalize_source_address, status_with_icon
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
_COMPACT_KEY = "library_schedule_compact"

_COURSE_THUMB_PALETTE: tuple[tuple[str, str, str], ...] = (
    ("#4338ca", "#22c55e", "#f8fafc"),
    ("#0f766e", "#f59e0b", "#f8fafc"),
    ("#be123c", "#38bdf8", "#fff7ed"),
    ("#7c2d12", "#a7f3d0", "#fff7ed"),
    ("#1d4ed8", "#fb7185", "#f8fafc"),
    ("#581c87", "#facc15", "#faf5ff"),
)


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


def _primary_cta_for_tile(tile: ScheduleTile) -> str:
    """Single primary action id for the card (W8)."""
    cta = str(tile.cta or "").strip()
    if cta in {"ask", "ask_all", "open_kg", "activate"}:
        return cta
    if tile.kind == "course" or tile.meta:
        return "activate"
    if tile.concept_id:
        return "open_kg"
    return "ask"


def _render_primary_cta(tile: ScheduleTile, *, key_prefix: str, primary: str) -> None:
    """One primary button (activate requires confirm checkbox)."""
    if primary in {"ask", "ask_all"}:
        label = "Спросить по области" if primary == "ask_all" else "Спросить"
        if st.button(label, key=f"{key_prefix}_primary", type="primary", width="stretch"):
            folder = "" if primary == "ask_all" else (
                tile.meta or (tile.courses[0] if tile.courses else "")
            )
            navigate_to_ask(folder)
            st.rerun()
        return
    if primary == "open_kg" and tile.concept_id:
        if st.button("В граф", key=f"{key_prefix}_primary", type="primary", width="stretch"):
            st.session_state["kg_selected_concept"] = tile.concept_id
            st.session_state["kg_action_concept"] = tile.concept_id
            st.session_state[PENDING_CURRENT_VIEW_KEY] = "Knowledge Graph"
            st.rerun()
        return
    if primary == "activate" and tile.meta:
        confirmed = st.checkbox(
            "Подтверждаю смену активного курса",
            key=f"{key_prefix}_confirm_act",
            help="Browse сам по себе scope не меняет — только после подтверждения.",
        )
        if st.button(
            "Сделать активным",
            key=f"{key_prefix}_primary",
            type="primary",
            width="stretch",
            disabled=not confirmed,
            help="Явное действие: активирует study scope.",
        ):
            from app.library_catalog_read import LibraryCourse

            activate_course_from_library(
                LibraryCourse(
                    folder_rel=tile.meta,
                    title=tile.title,
                    source_paths=tuple(tile.source_paths),
                )
            )
            st.success(f"Активный курс: {tile.title}")
            st.rerun()


def _render_secondary_menu(
    tile: ScheduleTile,
    *,
    key_prefix: str,
    primary: str,
    pin_key: str,
    is_pin: bool,
) -> None:
    """Secondary actions under «Ещё» (not competing with primary)."""
    pin_mark = "★ " if is_pin else "☆ "
    with st.expander("Ещё", expanded=False):
        st.caption(status_with_icon(tile.status, kind=tile.kind))
        if primary != "ask" and tile.courses:
            if st.button("Спросить по курсу", key=f"{key_prefix}_sec_ask", width="stretch"):
                navigate_to_ask(tile.courses[0] if tile.courses else tile.meta)
                st.rerun()
        if primary != "ask_all":
            if st.button("Спросить по всей области", key=f"{key_prefix}_sec_ask_all", width="stretch"):
                navigate_to_ask("")
                st.rerun()
        if primary != "open_kg" and tile.concept_id:
            if st.button("Открыть в графе", key=f"{key_prefix}_sec_kg", width="stretch"):
                st.session_state["kg_selected_concept"] = tile.concept_id
                st.session_state["kg_action_concept"] = tile.concept_id
                st.session_state[PENDING_CURRENT_VIEW_KEY] = "Knowledge Graph"
                st.rerun()
        pin_label = f"{pin_mark}Снять закрепление" if is_pin else f"{pin_mark}Закрепить"
        if st.button(pin_label, key=f"{key_prefix}_pin", width="stretch"):
            pins = set(st.session_state.get(_PIN_KEY) or [])
            if pin_key in pins:
                pins.discard(pin_key)
            else:
                pins.add(pin_key)
            st.session_state[_PIN_KEY] = sorted(pins)
            st.rerun()
        if tile.kind in {"course", "catalog"} and tile.meta:
            _render_course_detail_disclosure(tile.meta, key_prefix=key_prefix)


def _render_unified_card(tile: ScheduleTile, *, key_prefix: str, show_thumb: bool = False) -> None:
    """Unified anatomy: address → title → status → one primary CTA; secondary in menu."""
    pin_key = tile.concept_id or tile.meta or tile.title
    is_pin = pin_key in set(st.session_state.get(_PIN_KEY) or [])
    thumb = None
    if show_thumb and (tile.kind in {"course", "catalog"} or tile.cta == "activate"):
        thumb = course_thumbnail_data_uri(
            tile.title,
            tile.meta or (tile.courses[0] if tile.courses else ""),
        )
    st.markdown(
        library_card_html(
            title=tile.title,
            address=normalize_source_address(tile.address),
            status=tile.status,
            kind=tile.kind or "course",
            quant=tile.quant,
            thumb_uri=thumb,
        ),
        unsafe_allow_html=True,
    )
    if tile.courses:
        st.caption("📂 " + " · ".join(tile.courses[:6]))
    primary = _primary_cta_for_tile(tile)
    _render_primary_cta(tile, key_prefix=key_prefix, primary=primary)
    _render_secondary_menu(
        tile,
        key_prefix=key_prefix,
        primary=primary,
        pin_key=pin_key,
        is_pin=is_pin,
    )


def _render_course_detail_disclosure(folder_rel: str, *, key_prefix: str) -> None:
    """Optional hierarchy (konspekts/sections) without changing card model."""
    from app.library_catalog_read import list_library_konspekts, list_library_sections

    konspekts = list_library_konspekts(folder_rel)
    if not konspekts:
        st.caption("Конспектов type:konspekt в папке нет.")
        return
    st.markdown(f"**Конспекты** ({len(konspekts)})")
    for km in konspekts[:12]:
        badge = f" · {km.badge}" if km.badge else ""
        with st.expander(f"📄 {km.title}{badge}", expanded=False):
            st.caption(km.path_rel)
            sections = list_library_sections(km.path_abs)
            for sec in sections[:20]:
                st.caption(
                    f"L{sec.level} {sec.heading_text} · стр. {sec.line_start}–{sec.line_end}"
                )
            if len(sections) > 20:
                st.caption(f"… и ещё {len(sections) - 20}")
    if len(konspekts) > 12:
        st.caption(f"… и ещё {len(konspekts) - 12} конспектов")


def _render_empty(segment: str) -> None:
    messages = {
        "Каталог": "Курсов в области пока нет. Добавьте материалы и обновите индекс.",
        "Пересадки": "Общих тем между курсами пока нет (нужен граф с multi-course concepts).",
        "Маршрут": "Маршрут дня пуст: нет due/frontier остановок. Пройдите квиз или откройте Knowledge Graph.",
    }
    st.info(messages.get(segment, "Ничего не найдено."))


def _course_initials(title: str) -> str:
    words = [
        "".join(ch for ch in part if ch.isalnum())
        for part in str(title or "").replace("_", " ").replace("-", " ").split()
    ]
    letters = [word[0].upper() for word in words if word]
    return "".join(letters[:2]) or "К"


def course_thumbnail_data_uri(title: str, folder_rel: str = "") -> str:
    """Small deterministic SVG cover for a course card (no network / storage)."""
    seed = f"{title}|{folder_rel}".encode("utf-8", errors="ignore")
    digest = hashlib.sha256(seed).digest()
    c1, c2, fg = _COURSE_THUMB_PALETTE[digest[0] % len(_COURSE_THUMB_PALETTE)]
    angle = 15 + int(digest[1] % 55)
    initials = _course_initials(title)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient></defs>
<rect width="96" height="96" rx="18" fill="url(#g)"/>
<circle cx="{24 + digest[2] % 18}" cy="{18 + digest[3] % 20}" r="{14 + digest[4] % 12}" fill="rgba(255,255,255,.22)"/>
<circle cx="{62 + digest[5] % 16}" cy="{58 + digest[6] % 18}" r="{18 + digest[7] % 10}" fill="rgba(255,255,255,.16)"/>
<path d="M-8 {70 - digest[8] % 20} L104 {28 + digest[9] % 24}" stroke="rgba(255,255,255,.30)" stroke-width="10" transform="rotate({angle} 48 48)"/>
<text x="48" y="57" text-anchor="middle" font-family="Arial, sans-serif" font-size="28" font-weight="800" fill="{fg}">{initials}</text>
</svg>"""
    data = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{data}"


def _render_card_grid(
    tiles: list[ScheduleTile],
    *,
    key_prefix: str,
    show_thumb: bool = False,
) -> None:
    """Responsive 3→2→1 grid (CSS flex-wrap on horizontal blocks + 280px min)."""
    if not tiles:
        return
    st.markdown(
        '<div data-testid="e2e-lib-card-grid" data-lib-grid="3-2-1"></div>',
        unsafe_allow_html=True,
    )
    for row_start in range(0, len(tiles), 3):
        chunk = tiles[row_start : row_start + 3]
        cols = st.columns(len(chunk), gap="medium")
        for col, tile in zip(cols, chunk):
            with col:
                _render_unified_card(
                    tile,
                    key_prefix=f"{key_prefix}_{row_start}_{tile.meta or tile.concept_id or tile.title}",
                    show_thumb=show_thumb,
                )


def _render_tile_list(
    tiles: list[ScheduleTile],
    *,
    key_prefix: str,
    compact: bool = False,
) -> None:
    """List or grid of the same card model (search does not change anatomy)."""
    if not tiles:
        return
    if compact:
        _render_card_grid(tiles, key_prefix=key_prefix, show_thumb=True)
        return
    for i, tile in enumerate(tiles):
        _render_unified_card(
            tile,
            key_prefix=f"{key_prefix}_{i}",
            show_thumb=False,
        )


def _render_schedule_segment(
    segment: str,
    ctx: dict[str, Any],
    *,
    query: str,
    index_stats: dict,
    compact: bool,
) -> None:
    del index_stats  # catalog tiles already built in ctx; browse never mutates scope here
    if segment == "Каталог":
        tiles = filter_tiles(ctx["catalog"], query)
        if not tiles:
            if query:
                st.warning("По запросу в каталоге ничего не найдено.")
            else:
                _render_empty("Каталог")
            return
        st.caption(
            f"{'Найдено курсов' if query else 'Курсов'}: {len(tiles)}. "
            "Одна модель карточки; поиск только фильтрует. "
            "Активация — только с подтверждением."
        )
        # Same card model for filtered and full catalog (W8).
        _render_card_grid(tiles, key_prefix="lib_cat", show_thumb=True)
        return
    if segment == "Пересадки":
        tiles = filter_tiles(ctx["transfers"], query)
        if not tiles:
            _render_empty("Пересадки") if not query else st.warning(
                "По запросу пересадок не найдено."
            )
        else:
            st.caption(f"Общих тем: {len(tiles)}")
            _render_tile_list(tiles, key_prefix="lib_tr", compact=compact)
        return
    tiles = filter_tiles(ctx["route"], query)
    if not tiles:
        _render_empty("Маршрут") if not query else st.warning(
            "По запросу остановок не найдено."
        )
    else:
        st.caption(f"Остановок маршрута: {len(tiles)}")
        _render_tile_list(tiles, key_prefix="lib_rt", compact=compact)


def render_library_schedule(index_stats: dict | None = None) -> None:
    """Full schedule surface: summary + search + 3 segments (no split panel wrapper)."""
    if index_stats is None:
        index_stats = load_index_stats()
    if not isinstance(index_stats, dict):
        index_stats = {}

    render_panel_header(
        "Расписание области",
        "Каталог · пересадки · маршрут — одна поверхность без смены scope",
    )
    st.caption(
        "Поиск фильтрует ту же модель карточек. Адрес «курс · урок» — SourceAddress "
        "(как Memory Run). Просмотр не активирует курс; «Сделать активным» — только "
        "с подтверждением."
    )

    raw_owner = read_course_owner_order(st.session_state)
    courses_preview = list_library_courses(index_stats)
    available = [c.folder_rel for c in courses_preview]
    owner_order = merge_owner_order_with_available(available, owner_order=raw_owner)
    if owner_order and owner_order != raw_owner:
        write_course_owner_order(st.session_state, owner_order)

    _render_course_order_panel(available, owner_order=owner_order)
    ctx = _build_schedule_context(index_stats, owner_order=owner_order)
    _render_unified_card(ctx["summary"], key_prefix="lib_sum", show_thumb=False)

    c_search, c_compact = st.columns([0.72, 0.28])
    with c_search:
        query = st.text_input(
            "Поиск по расписанию",
            key=_SEARCH_KEY,
            placeholder="курс, тема, адрес…",
            help="Скрывает карточки, которые не содержат запрос (анатомия та же).",
        ).strip()
    with c_compact:
        compact = st.toggle(
            "Сетка 3→2→1",
            key=_COMPACT_KEY,
            value=True,
            help="Плотная сетка с мини-обложками; на узком экране — 2, затем 1 колонка.",
        )
    if _SEG_KEY not in st.session_state:
        st.session_state[_SEG_KEY] = SCHEDULE_SEGMENTS[0]
    segment = st.radio(
        "Сегмент",
        list(SCHEDULE_SEGMENTS),
        key=_SEG_KEY,
        horizontal=True,
        label_visibility="collapsed",
    )
    _render_schedule_segment(segment, ctx, query=query, index_stats=index_stats, compact=compact)


__all__ = [
    "course_thumbnail_data_uri",
    "render_library_schedule",
]
