"""Streamlit scene-DSL panel for MnemoPolis (presentation-only, size extract)."""

from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

SCENE_PRESENTATION_KEY = "kg_3d_scene_presentation"
SCENE_NL_ERROR_KEY = "kg_3d_scene_nl_error"


def consume_scene_presentation() -> dict[str, Any] | None:
    """Return pending presentation for the next hall bake (does not clear)."""
    raw = st.session_state.get(SCENE_PRESENTATION_KEY)
    return dict(raw) if isinstance(raw, dict) else None


def render_scene_dsl_panel(
    *,
    node_ids: list[str],
    payload: Mapping[str, Any] | None = None,
) -> None:
    """Host NL + status for presentation-only scene commands (W5b.2)."""
    from app.mnemo_scene_dsl import empty_presentation, nl_to_presentation

    labels: dict[str, str] = {}
    for n in (payload or {}).get("nodes") or []:
        if isinstance(n, Mapping):
            cid = str(n.get("id") or "").strip()
            if cid:
                labels[cid] = str(n.get("label") or cid)

    err = str(st.session_state.pop(SCENE_NL_ERROR_KEY, "") or "").strip()
    with st.expander("🎛 Сцена (presentation only)", expanded=False):
        st.caption(
            "Команды меняют **только вид** зала. Маршрут дня в данных не "
            "переписывается. Без eval/JS; неизвестные фразы отклоняются."
        )
        col_in, col_btn = st.columns([4, 1])
        with col_in:
            text = st.text_input(
                "Команда",
                key="kg_3d_scene_nl_input",
                placeholder="слабое · маршрут · созвездие · спокойный · фокус RAG · сброс",
                label_visibility="collapsed",
            )
        with col_btn:
            apply = st.button("Применить", key="kg_3d_scene_nl_apply", use_container_width=True)
        if apply:
            allowed = {str(x).strip() for x in node_ids if str(x).strip()}
            pres, reason = nl_to_presentation(
                text, node_ids=allowed, node_labels=labels
            )
            if pres is None:
                st.session_state[SCENE_NL_ERROR_KEY] = (
                    f"Не распознано: {reason or 'unrecognized'}"
                )
            else:
                st.session_state[SCENE_PRESENTATION_KEY] = pres
                st.session_state.pop(SCENE_NL_ERROR_KEY, None)
            st.rerun()
        if st.button("Сбросить presentation", key="kg_3d_scene_nl_clear"):
            st.session_state[SCENE_PRESENTATION_KEY] = empty_presentation()
            st.session_state.pop(SCENE_NL_ERROR_KEY, None)
            st.rerun()
        if err:
            st.warning(err)
        cur = consume_scene_presentation()
        if cur and (
            cur.get("filter")
            or cur.get("scene_mode")
            or cur.get("overlay")
            or cur.get("focus_id")
            or cur.get("route_override")
        ):
            bits = []
            if cur.get("scene_mode"):
                bits.append(f"mode={cur['scene_mode']}")
            if cur.get("filter"):
                bits.append(f"filter={cur['filter']}")
            if cur.get("overlay"):
                bits.append(f"overlay={cur['overlay']}")
            if cur.get("focus_id"):
                bits.append(f"focus={cur['focus_id']}")
            if cur.get("route_override"):
                bits.append(f"highlight={len(cur['route_override'])}")
            st.caption("Активно: " + " · ".join(bits) + " · day_route не изменён")
