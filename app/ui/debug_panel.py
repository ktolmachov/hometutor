"""Компактный debug/trace для вкладки «Быстрый ответ»."""
from __future__ import annotations

from typing import Any

import streamlit as st

from app.ui.helpers import (
    graph_expansion_skip_reason_label,
    llm_source_badge_text,
    llm_source_debug_rows,
    llm_source_privacy_notice,
    retrieval_route_debug_rows,
    retrieval_route_demotion_badge,
)
from app.ui.widgets import render_chip_row, render_metric_card


def graph_expansion_rows_for_ui(ge: dict[str, Any] | None) -> list[tuple[str, str]]:
    """
    Пары подпись/значение для блока graph expansion в debug (без длинных списков id).
    """
    if not isinstance(ge, dict) or not ge:
        return []
    rows: list[tuple[str, str]] = []
    ms = ge.get("graph_expansion_ms")
    if ms is not None:
        try:
            rows.append(("Время (ms)", f"{float(ms):.1f}"))
        except (TypeError, ValueError):
            rows.append(("Время (ms)", str(ms)))
    if ge.get("skipped"):
        rows.append(("Режим", "пропуск"))
        if ge.get("reason"):
            skip_label = graph_expansion_skip_reason_label(str(ge.get("reason") or ""))
            rows.append(("Причина", (skip_label or str(ge["reason"]))[:100]))
    elif ge.get("ok") is False:
        rows.append(("Режим", "ошибка"))
        if ge.get("error"):
            rows.append(("Деталь", str(ge["error"])[:160]))
    elif ge.get("ok") is True:
        rows.append(("Режим", "добавлены чанки"))
        if ge.get("extra_chunk_count") is not None:
            rows.append(("Доп. чанков", str(ge["extra_chunk_count"])))
        if ge.get("concepts_touched") is not None:
            rows.append(("Концептов", str(ge["concepts_touched"])))
        if ge.get("hops_applied") is not None:
            rows.append(("Волн обхода", str(ge["hops_applied"])))
        if ge.get("max_hops") is not None:
            rows.append(("Лимит волн", str(ge["max_hops"])))
    elif ms is not None:
        rows.append(("Режим", "частичный trace"))
    return rows


def graph_expansion_chip_labels_for_ui(ge: dict[str, Any] | None) -> list[str]:
    if not isinstance(ge, dict) or not ge:
        return []
    chips: list[str] = []
    for doc_id in (ge.get("seed_doc_ids") or [])[:4]:
        chips.append(f"seed: {doc_id}")
    for doc_id in (ge.get("added_doc_ids") or [])[:4]:
        chips.append(f"+doc: {doc_id}")
    return chips


def graph_expansion_provenance_lines_for_ui(ge: dict[str, Any] | None) -> list[str]:
    if not isinstance(ge, dict) or not ge:
        return []
    out: list[str] = []
    route_sample = ge.get("concept_route_sample") or []
    for item in route_sample[:4]:
        if not isinstance(item, dict):
            continue
        concept_id = str(item.get("concept_id") or "").strip()
        if not concept_id:
            continue
        hop = int(item.get("hop") or 0)
        relation = str(item.get("relation") or "seed").strip() or "seed"
        via = str(item.get("via_concept") or "").strip()
        if relation == "seed" or not via:
            out.append(f"Концепт `{concept_id}` взят как seed")
        else:
            out.append(f"Концепт `{concept_id}` найден через `{relation}` от `{via}` (hop {hop})")
    reason_sample = ge.get("added_doc_reason_sample") or []
    for item in reason_sample[:4]:
        if not isinstance(item, dict):
            continue
        doc_id = str(item.get("doc_id") or "").strip()
        reasons = item.get("reasons") or []
        if not doc_id or not reasons:
            continue
        first = reasons[0] if isinstance(reasons[0], dict) else {}
        concept_id = str(first.get("concept_id") or "").strip()
        relation = str(first.get("relation") or "seed").strip() or "seed"
        via = str(first.get("via_concept") or "").strip()
        hop = int(first.get("hop") or 0)
        if relation == "seed" or not via:
            out.append(f"Документ `{doc_id}` добавлен через seed-концепт `{concept_id}`")
        else:
            out.append(f"Документ `{doc_id}` добавлен через `{concept_id}` ← `{relation}` ← `{via}` (hop {hop})")
    return out


def confidence_reason_labels(reasons: list[str]) -> list[str]:
    mapping = {
        "low_classify_confidence": "тип запроса определён неуверенно",
        "no_sources": "нет источников",
        "too_few_sources": "мало источников",
        "low_source_scores": "источники слабовато совпадают с запросом",
        "low_document_coverage": "ответ опирается на слишком малое число документов",
    }
    labels = []
    for reason in reasons:
        labels.append(mapping.get(reason, reason.replace("_", " ")))
    return labels


def render_debug_summary(debug: dict[str, Any]) -> None:
    if not debug:
        return
    routing_rows = retrieval_route_debug_rows(debug)
    routing_map = {label: value for label, value in routing_rows}
    cols = st.columns(6)
    with cols[0]:
        render_metric_card("Тип запроса", str(debug.get("query_type") or "n/a"), "маршрутизатор")
    with cols[1]:
        render_metric_card("Выбранный профиль", str(routing_map.get("Выбранный профиль") or "n/a"), "requested")
    with cols[2]:
        render_metric_card("Эффективный профиль", str(routing_map.get("Эффективный профиль") or "n/a"), "effective")
    with cols[3]:
        render_metric_card("Подбор", str(debug.get("retrieval_mode") or "n/a"), "режим")
    with cols[4]:
        render_metric_card("Latency", f"{debug.get('total_answer_ms', 'n/a')} ms", "end-to-end")
    with cols[5]:
        render_metric_card("Cache", "yes" if debug.get("cache_hit") else "no", "query engine")
    route_reason = str(routing_map.get("Причина маршрута") or "").strip()
    route_source = str(routing_map.get("Источник решения") or "").strip()
    if route_reason or route_source:
        parts: list[str] = []
        if route_reason:
            parts.append(route_reason)
        if route_source:
            parts.append(f"источник: {route_source}")
        st.caption("Почему выбран этот маршрут: " + " · ".join(parts))
    demotion_badge = retrieval_route_demotion_badge(debug)
    if demotion_badge:
        render_chip_row([demotion_badge])
    source_badge = llm_source_badge_text(debug)
    if source_badge:
        st.caption(source_badge)
    source_notice = llm_source_privacy_notice(debug)
    if source_notice:
        st.caption(source_notice)
    source_rows = llm_source_debug_rows(debug)
    if source_rows:
        with st.expander("Источник модели ответа", expanded=False):
            ncols = min(3, len(source_rows))
            cols = st.columns(ncols)
            for i, (label, val) in enumerate(source_rows):
                with cols[i % ncols]:
                    st.metric(label, val)
    chips = []
    if debug.get("homework_mode"):
        level = debug.get("assistance_level") or "hint"
        chips.append(f"homework: {level}")
    if debug.get("rewritten_question"):
        chips.append(f"rewrite: {debug['rewritten_question']}")
    chips.extend(f"subq: {item}" for item in (debug.get("subquestions") or []))
    render_chip_row(chips)

    pt = debug.get("pipeline_trace") if isinstance(debug.get("pipeline_trace"), dict) else {}
    ge_raw = pt.get("graph_expansion")
    ge = ge_raw if isinstance(ge_raw, dict) else None
    gx_rows = graph_expansion_rows_for_ui(ge)
    if gx_rows:
        with st.expander("Расширение графа знаний (подробно)", expanded=False):
            ncols = min(4, len(gx_rows))
            cols = st.columns(ncols)
            for i, (label, val) in enumerate(gx_rows):
                with cols[i % ncols]:
                    st.metric(label, val)
            gx_chips = graph_expansion_chip_labels_for_ui(ge)
            if gx_chips:
                render_chip_row(gx_chips)
            gx_lines = graph_expansion_provenance_lines_for_ui(ge)
            if gx_lines:
                st.caption("Почему были добавлены чанки")
                for line in gx_lines:
                    st.markdown(f"- {line}")


def graph_expansion_trust_caption_ru(debug: dict[str, Any] | None) -> str | None:
    """E9.6 / US-3.2: одна строка у слоя доверия, если graph expansion реально добавил чанки."""
    if not isinstance(debug, dict):
        return None
    routing = debug.get("retrieval_routing")
    if isinstance(routing, dict) and routing.get("effective_graph_augmented") is False:
        return None
    pt = debug.get("pipeline_trace") if isinstance(debug.get("pipeline_trace"), dict) else {}
    ge_raw = pt.get("graph_expansion")
    ge = ge_raw if isinstance(ge_raw, dict) else None
    if not ge or ge.get("ok") is not True:
        return None
    parts: list[str] = ["К отбору источников добавлены связанные фрагменты через граф знаний"]
    ec = ge.get("extra_chunk_count")
    if ec is not None:
        try:
            parts.append(f"+{int(ec)} чанков")
        except (TypeError, ValueError):
            parts.append(f"+{ec} чанков")
    hops = ge.get("hops_applied")
    if hops is not None:
        try:
            parts.append(f"{int(hops)} волн обхода")
        except (TypeError, ValueError):
            parts.append(f"{hops} волн обхода")
    return " · ".join(parts)
