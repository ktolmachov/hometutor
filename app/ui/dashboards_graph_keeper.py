"""Streamlit Keeper control strip for the KG 3D hall (size-budget extract)."""

from __future__ import annotations

import streamlit as st


def render_keeper_control_panel() -> None:
    """W3b/c/d: offline / LLM for guide, threats, quest + status caption."""
    k_src = str(st.session_state.get("kg_3d_keeper_guide_source") or "")
    t_src = str(st.session_state.get("kg_3d_keeper_threats_source") or "")
    t_n = int(st.session_state.get("kg_3d_keeper_threats_count") or 0)
    q_src = str(st.session_state.get("kg_3d_keeper_quest_source") or "")
    k_cols = st.columns([1, 1, 1, 1, 1, 1, 2])

    def _clear_keeper_cache() -> None:
        try:
            from app.mnemo_keeper import KEEPER_CACHE_SESSION_KEY

            st.session_state.pop(KEEPER_CACHE_SESSION_KEY, None)
        except Exception:  # noqa: BLE001 - cache clear is best-effort
            pass

    with k_cols[0]:
        if st.button("📖 Экскурсия", key="kg_3d_keeper_static", help="Офлайн-рассказ (W3b)."):
            _clear_keeper_cache()
            st.session_state["kg_3d_keeper_guide_llm_once"] = False
            st.rerun()
    with k_cols[1]:
        if st.button("✨ Экскурсия LLM", key="kg_3d_keeper_llm", help="LLM-экскурсовод (бюджет)."):
            st.session_state["kg_3d_keeper_guide_llm_once"] = True
            st.rerun()
    with k_cols[2]:
        if st.button("🌫 Угрозы", key="kg_3d_threats_static", help="Список забывания (W3c)."):
            _clear_keeper_cache()
            st.session_state["kg_3d_keeper_threats_llm_once"] = False
            st.rerun()
    with k_cols[3]:
        if st.button("✨ Угрозы LLM", key="kg_3d_threats_llm", help="Проза угроз (бюджет)."):
            st.session_state["kg_3d_keeper_threats_llm_once"] = True
            st.rerun()
    with k_cols[4]:
        if st.button("🎯 Цель", key="kg_3d_quest_static", help="Офлайн «N из M» (W3d)."):
            _clear_keeper_cache()
            st.session_state["kg_3d_keeper_quest_llm_once"] = False
            st.rerun()
    with k_cols[5]:
        if st.button("✨ Цель LLM", key="kg_3d_quest_llm", help="Квестмейстер (бюджет)."):
            st.session_state["kg_3d_keeper_quest_llm_once"] = True
            st.rerun()
    with k_cols[6]:
        bits = []
        if k_src:
            bits.append(f"экскурсия: **{k_src}**")
        if t_src:
            bits.append(f"угрозы: **{t_src}** ({t_n})")
        if q_src:
            bits.append(f"цель: **{q_src}**")
        if bits:
            st.caption(" · ".join(bits))
