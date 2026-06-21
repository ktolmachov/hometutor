"""Weekly study narrative UI block for Progress surfaces (US-20.1 secondary context)."""

from __future__ import annotations

import time

import streamlit as st

from app.ssr_weekly_narrative import WeeklyStudyNarrativeViewModel, build_weekly_study_narrative_snapshot

_ERROR_MESSAGE_RU = (
    "Срез недели временно недоступен. Основные метрики и подсказка Smart Study работают как обычно."
)
_SPINNER_THRESHOLD_MS = 25.0


def _safe_key_prefix(key_prefix: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in key_prefix)[:40] or "weekly_narrative"


def _render_view_model(vm: WeeklyStudyNarrativeViewModel) -> None:
    if vm.state == "empty":
        st.caption(vm.message_ru)
        return
    for bullet in vm.bullets:
        st.caption(f"• {bullet}")


def render_weekly_study_narrative_block(*, key_prefix: str) -> None:
    """Collapsed expander «Неделя в обучении»; SSR and primary CTA stay above."""
    safe_pre = _safe_key_prefix(key_prefix)
    started = time.perf_counter()
    vm: WeeklyStudyNarrativeViewModel | None = None
    build_err: Exception | None = None
    try:
        vm = build_weekly_study_narrative_snapshot()
    except Exception as exc:  # noqa: BLE001 - narrative must not break Progress surfaces
        build_err = exc
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    st.markdown('<div data-testid="e2e-weekly-study-narrative">', unsafe_allow_html=True)
    with st.expander("Неделя в обучении", expanded=False, key=f"{safe_pre}_weekly_narrative_expander"):
        if build_err is not None:
            st.caption(_ERROR_MESSAGE_RU)
        elif vm is not None:
            if elapsed_ms > _SPINNER_THRESHOLD_MS:
                with st.spinner("Собираем срез недели…"):
                    _render_view_model(vm)
            else:
                _render_view_model(vm)
    st.markdown("</div>", unsafe_allow_html=True)


__all__ = ["render_weekly_study_narrative_block"]
