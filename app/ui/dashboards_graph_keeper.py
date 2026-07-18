"""Streamlit Keeper control strip + VM build for the KG 3D hall."""

from __future__ import annotations

from typing import Any

import streamlit as st


def build_keeper_view_models(payload: Any) -> dict:
    """Keeper hall VMs (offline first; LLM on explicit session flags)."""
    snap_date = ""
    try:
        hist = payload.get("mastery_history") or []
        if hist and isinstance(hist[-1], dict):
            snap_date = str(hist[-1].get("date") or "")
    except Exception:  # noqa: BLE001 - malformed mastery history must not block keeper build
        snap_date = ""
    try:
        from app.mnemo_keeper_views import assemble_keeper_hall_vms

        vms = assemble_keeper_hall_vms(
            payload,
            session_state=st.session_state,
            allow_guide_llm=bool(st.session_state.pop("kg_3d_keeper_guide_llm_once", False)),
            allow_threats_llm=bool(
                st.session_state.pop("kg_3d_keeper_threats_llm_once", False)
            ),
            allow_quest_llm=bool(st.session_state.pop("kg_3d_keeper_quest_llm_once", False)),
            allow_voices_llm=bool(
                st.session_state.pop("kg_3d_keeper_voices_llm_once", False)
            ),
            allow_chronicle_llm=bool(
                st.session_state.pop("kg_3d_keeper_chronicle_llm_once", False)
            ),
            snapshot_date=snap_date,
        )
        for key, src_key in (
            ("guide", "kg_3d_keeper_guide_source"),
            ("threats", "kg_3d_keeper_threats_source"),
            ("quest", "kg_3d_keeper_quest_source"),
            ("voices", "kg_3d_keeper_voices_source"),
            ("chronicle", "kg_3d_keeper_chronicle_source"),
        ):
            st.session_state[src_key] = str((vms.get(key) or {}).get("source") or "")
        st.session_state["kg_3d_keeper_threats_count"] = int(
            (vms.get("threats") or {}).get("count") or 0
        )
        return vms
    except Exception:  # noqa: BLE001 - keeper is optional; hall must still render
        return {}


def render_keeper_control_panel() -> None:
    """Keeper offline/LLM toggles: guide, threats, quest, voices, chronicle."""
    k_src = str(st.session_state.get("kg_3d_keeper_guide_source") or "")
    t_src = str(st.session_state.get("kg_3d_keeper_threats_source") or "")
    t_n = int(st.session_state.get("kg_3d_keeper_threats_count") or 0)
    q_src = str(st.session_state.get("kg_3d_keeper_quest_source") or "")
    v_src = str(st.session_state.get("kg_3d_keeper_voices_source") or "")
    c_src = str(st.session_state.get("kg_3d_keeper_chronicle_source") or "")

    def _clear_keeper_cache() -> None:
        try:
            from app.mnemo_keeper import KEEPER_CACHE_SESSION_KEY

            st.session_state.pop(KEEPER_CACHE_SESSION_KEY, None)
        except Exception:  # noqa: BLE001 - cache clear is best-effort
            pass

    r1 = st.columns([1, 1, 1, 1, 1, 1])
    with r1[0]:
        if st.button("📖 Экскурсия", key="kg_3d_keeper_static", help="Офлайн-рассказ (W3b)."):
            _clear_keeper_cache()
            st.session_state["kg_3d_keeper_guide_llm_once"] = False
            st.rerun()
    with r1[1]:
        if st.button("✨ Экскурсия LLM", key="kg_3d_keeper_llm", help="LLM-экскурсовод."):
            st.session_state["kg_3d_keeper_guide_llm_once"] = True
            st.rerun()
    with r1[2]:
        if st.button("🌫 Угрозы", key="kg_3d_threats_static", help="Список забывания (W3c)."):
            _clear_keeper_cache()
            st.session_state["kg_3d_keeper_threats_llm_once"] = False
            st.rerun()
    with r1[3]:
        if st.button("✨ Угрозы LLM", key="kg_3d_threats_llm", help="Проза угроз."):
            st.session_state["kg_3d_keeper_threats_llm_once"] = True
            st.rerun()
    with r1[4]:
        if st.button("🎯 Цель", key="kg_3d_quest_static", help="Офлайн «N из M» (W3d)."):
            _clear_keeper_cache()
            st.session_state["kg_3d_keeper_quest_llm_once"] = False
            st.rerun()
    with r1[5]:
        if st.button("✨ Цель LLM", key="kg_3d_quest_llm", help="Квестмейстер."):
            st.session_state["kg_3d_keeper_quest_llm_once"] = True
            st.rerun()

    r2 = st.columns([1, 1, 1, 1, 2])
    with r2[0]:
        if st.button("🗣 Голоса", key="kg_3d_voices_static", help="Static bank антагонистов (H)."):
            _clear_keeper_cache()
            st.session_state["kg_3d_keeper_voices_llm_once"] = False
            st.rerun()
    with r2[1]:
        if st.button("✨ Голоса LLM", key="kg_3d_voices_llm", help="Реплики (бюджет)."):
            st.session_state["kg_3d_keeper_voices_llm_once"] = True
            st.rerun()
    with r2[2]:
        if st.button("📜 Летопись", key="kg_3d_chronicle_static", help="Quiz-снимки (W6c)."):
            _clear_keeper_cache()
            st.session_state["kg_3d_keeper_chronicle_llm_once"] = False
            st.rerun()
    with r2[3]:
        if st.button("✨ Летопись LLM", key="kg_3d_chronicle_llm", help="Проза летописца."):
            st.session_state["kg_3d_keeper_chronicle_llm_once"] = True
            st.rerun()
    with r2[4]:
        bits = []
        if k_src:
            bits.append(f"экскурсия:**{k_src}**")
        if t_src:
            bits.append(f"угрозы:**{t_src}**({t_n})")
        if q_src:
            bits.append(f"цель:**{q_src}**")
        if v_src:
            bits.append(f"голоса:**{v_src}**")
        if c_src:
            bits.append(f"летопись:**{c_src}**")
        if bits:
            st.caption(" · ".join(bits))
