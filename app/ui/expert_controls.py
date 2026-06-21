"""Shared expert-layer widgets for Mission Critical Streamlit views."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import streamlit as st

from app.ui.continuity_bridge import expert_controls_expander_label_ru
from app.ui.widgets import render_chip_row, render_metric_card


MetricRow = Sequence[tuple[str, str, str]]


def render_expert_metric_row(metrics: MetricRow) -> None:
    """Render compact metric cards without exposing raw internals first."""
    visible_metrics = [item for item in metrics if item]
    if not visible_metrics:
        return
    cols = st.columns(min(4, len(visible_metrics)))
    for idx, (label, value, subtext) in enumerate(visible_metrics):
        with cols[idx % len(cols)]:
            render_metric_card(label, value, subtext)


def render_raw_debug_expander(label: str, payload: Any) -> None:
    """Keep raw debug data one click deeper than trust-building summaries."""
    if payload in (None, {}, [], ""):
        return
    with st.expander(label, expanded=False):
        st.json(payload)


def render_expert_controls(
    *,
    intro: str,
    metrics: MetricRow = (),
    signals: Iterable[str] = (),
    safe_actions: Iterable[str] = (),
    raw_debug_label: str | None = None,
    raw_debug_payload: Any = None,
    expanded: bool = False,
) -> None:
    """Render the common collapsed expert layer used by core learning flows."""
    with st.expander(expert_controls_expander_label_ru(), expanded=expanded):
        st.caption(intro)
        render_expert_metric_row(metrics)
        signal_list = [item for item in signals if str(item).strip()]
        if signal_list:
            st.caption("Сигналы")
            render_chip_row(signal_list)
        action_list = [item for item in safe_actions if str(item).strip()]
        if action_list:
            st.caption("Безопасные действия")
            for action in action_list:
                st.markdown(f"- {action}")
        if raw_debug_label:
            render_raw_debug_expander(raw_debug_label, raw_debug_payload)


def summarize_question_types(questions: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Count quiz question types for the expert summary."""
    counts: dict[str, int] = {}
    for question in questions:
        qtype = str(question.get("type") or "unknown")
        counts[qtype] = counts.get(qtype, 0) + 1
    return counts
