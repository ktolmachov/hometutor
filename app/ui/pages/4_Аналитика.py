"""Расширенная аналитика: heatmap quiz, кривая удержания, ROI, рекомендации."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.analytics_service import get_advanced_analytics
from app.ui.adaptive_plan_widgets import render_adaptive_daily_plan_section
from app.ui.auth_gate import require_ui_auth_or_stop

st.set_page_config(page_title="Аналитика", layout="wide")
require_ui_auth_or_stop()

st.title("Аналитика")

render_adaptive_daily_plan_section(key_prefix="analytics_adp")

data = get_advanced_analytics()

st.subheader("ROI времени (эвристика)")
st.markdown(data.get("time_roi_text") or "—")

st.subheader("Рекомендация")
st.write(data.get("weekly_ai_recommendation") or "—")

gam = data.get("gamification") or {}
if gam:
    c1, c2, c3 = st.columns(3)
    c1.metric("XP", gam.get("total_xp", 0))
    c2.metric("Стрик", f"{gam.get('daily_streak', 0)} дн.")
    c3.metric("Квиз-стрик", gam.get("quiz_streak", 0))

hm = data.get("heatmap") or {}
z, x, y = hm.get("z") or [], hm.get("x") or [], hm.get("y") or []
if z and x and y:
    st.subheader("Heatmap: средний score по дням и концептам")
    fig_h = px.imshow(
        z,
        x=x,
        y=y,
        aspect="auto",
        color_continuous_scale="Viridis",
        labels=dict(x="Дата", y="Концепт", color="score"),
    )
    fig_h.update_layout(margin=dict(l=20, r=20, t=40, b=20))
    st.plotly_chart(fig_h, width='stretch')
else:
    st.info("Недостаточно строк в quiz_results для heatmap.")

fc = data.get("forgetting_curve") or []
if fc:
    st.subheader("Кривая удержания (по интервалам повторений)")
    fig_c = go.Figure()
    fig_c.add_trace(
        go.Scatter(
            x=[p["day"] for p in fc],
            y=[p["retention"] for p in fc],
            mode="lines+markers",
            name="retention",
        )
    )
    fig_c.update_layout(
        xaxis_title="День",
        yaxis_title="Удержание (модель)",
        margin=dict(l=20, r=20, t=30, b=20),
    )
    st.plotly_chart(fig_c, width='stretch')

wc = data.get("weak_concepts") or []
if wc:
    st.caption("Слабые концепты: " + ", ".join(str(w) for w in wc[:12]))

diag = data.get("learner_state_diagnostics") or {}
if diag:
    st.subheader("Lineage и Archive")
    cur = diag.get("current_lineage") or {}
    synced = diag.get("synced_lineage") or {}
    archive_counts = diag.get("archive_counts") or {}
    c1, c2, c3 = st.columns(3)
    c1.metric("Текущий generation", cur.get("generation_id") or "—")
    c2.metric("Archive rows", int(archive_counts.get("total") or 0))
    c3.metric("Миграция", synced.get("migrated_at") or "—")

    live_counts = diag.get("live_counts") or {}
    st.caption(
        "Live state: "
        f"quiz_results={int(live_counts.get('quiz_results') or 0)}, "
        f"quiz_mastery={int(live_counts.get('quiz_mastery') or 0)}, "
        f"spaced_repetition={int(live_counts.get('spaced_repetition') or 0)}"
    )

    if diag.get("has_archived_state"):
        reasons = diag.get("archive_reasons") or {}
        if reasons:
            st.write(
                "Архивные причины: "
                + ", ".join(f"{key}={int(value)}" for key, value in reasons.items())
            )
        recent = diag.get("recent_archive") or []
        if recent:
            st.dataframe(recent, width='stretch', hide_index=True)
