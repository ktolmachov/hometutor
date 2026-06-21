"""Streamlit page: SSR explanation feedback insights.

Real-time analytics on explanation quality. Shows:
- Overall thumbs distribution (👍 vs 👎)
- Helpful vs unhelpful by hint_kind (cards_due, quiz_opportunity, etc.)
- Helpful vs unhelpful by primary_nav (flashcards, quiz, tutor, etc.)
- Correlation with explanation length (do longer explanations help more?)
"""
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="SSR Feedback Insights", layout="wide")
st.title("✨ SSR Explanation Quality — Real-Time Feedback")


@st.cache_data(ttl=60)
def _load_feedback(log_dir: Path, days: int = 7) -> list[dict]:
    """Load feedback records from the last N days."""
    rows: list[dict] = []
    if not log_dir.exists():
        return rows

    today = date.today()
    target_dates = {(today - timedelta(days=i)).isoformat() for i in range(days)}

    for f in sorted(log_dir.glob("ssr_feedback_*.jsonl")):
        date_part = f.stem.replace("ssr_feedback_", "")
        if date_part not in target_dates:
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def _feedback_log_dir() -> Path:
    """Get the feedback log directory."""
    try:
        from app.config import get_settings

        s = get_settings()
        base = getattr(s, "base_dir", None) or Path(".")
        return Path(base) / "logs" / "ssr_feedback"
    except Exception:  # noqa: BLE001
        return Path("logs") / "ssr_feedback"


# ────────────────────────────────────────────────────────────────────────────────

log_dir = _feedback_log_dir()

# Controls
col1, col2, col3 = st.columns(3)
with col1:
    days = st.slider("Days", 1, 30, 7)
with col2:
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()
with col3:
    st.caption(f"Log dir: {log_dir.name}")

# Load data
rows = _load_feedback(log_dir, days=days)

if not rows:
    st.info("No feedback records yet. Users will start rating explanations soon!")
    st.stop()

total = len(rows)
up = sum(1 for r in rows if r.get("rating") == 1)
down = total - up
pct = round(up / total * 100, 1) if total else 0

# ────────────────────────────────────────────────────────────────────────────────
# Summary cards

st.markdown("### Overall Statistics")
mc1, mc2, mc3, mc4 = st.columns(4)
with mc1:
    st.metric("Total Ratings", total)
with mc2:
    st.metric("👍 Helpful", f"{up} ({pct}%)", delta=f"-{down} unhelpful")
with mc3:
    st.metric("👎 Not Helpful", down)
with mc4:
    avg_len = round(sum(r.get("why_now_len", 0) for r in rows) / total) if total else 0
    st.metric("Avg Length", f"{avg_len} chars")

# ────────────────────────────────────────────────────────────────────────────────
# By hint_kind

st.markdown("### Quality by Recommendation Type (hint_kind)")

by_hint: dict[str, dict[str, int]] = defaultdict(lambda: {"up": 0, "down": 0})
for r in rows:
    hk = str(r.get("hint_kind") or "unknown")
    rating = r.get("rating")
    if rating == 1:
        by_hint[hk]["up"] += 1
    else:
        by_hint[hk]["down"] += 1

hint_data = []
for hk in sorted(by_hint.keys()):
    counts = by_hint[hk]
    total_hk = counts["up"] + counts["down"]
    pct_hk = round(counts["up"] / total_hk * 100, 1) if total_hk else 0
    hint_data.append({
        "hint_kind": hk,
        "👍": counts["up"],
        "👎": counts["down"],
        "Total": total_hk,
        "Helpful %": pct_hk,
    })

import pandas as pd

if hint_data:
    df_hint = pd.DataFrame(hint_data)
    st.dataframe(df_hint, width='stretch', hide_index=True)

    # Bar chart
    chart_data = [
        {"Type": hk, "Helpful": by_hint[hk]["up"]} for hk in sorted(by_hint.keys())
    ]
    if chart_data:
        st.bar_chart(pd.DataFrame(chart_data).set_index("Type"))

# ────────────────────────────────────────────────────────────────────────────────
# By primary_nav

st.markdown("### Quality by Navigation (primary_nav)")

by_nav: dict[str, dict[str, int]] = defaultdict(lambda: {"up": 0, "down": 0})
for r in rows:
    nav = str(r.get("primary_nav") or "unknown")
    rating = r.get("rating")
    if rating == 1:
        by_nav[nav]["up"] += 1
    else:
        by_nav[nav]["down"] += 1

nav_data = []
for nav in sorted(by_nav.keys()):
    counts = by_nav[nav]
    total_nav = counts["up"] + counts["down"]
    pct_nav = round(counts["up"] / total_nav * 100, 1) if total_nav else 0
    nav_data.append({
        "primary_nav": nav,
        "👍": counts["up"],
        "👎": counts["down"],
        "Total": total_nav,
        "Helpful %": pct_nav,
    })

if nav_data:
    df_nav = pd.DataFrame(nav_data)
    st.dataframe(df_nav, width='stretch', hide_index=True)

# ────────────────────────────────────────────────────────────────────────────────
# Explanation length correlation

st.markdown("### Explanation Length Correlation")

up_lens = [r.get("why_now_len", 0) for r in rows if r.get("rating") == 1]
down_lens = [r.get("why_now_len", 0) for r in rows if r.get("rating") != 1]

if up_lens and down_lens:
    col1, col2 = st.columns(2)
    with col1:
        avg_up = round(sum(up_lens) / len(up_lens))
        st.metric("Avg length (👍 Helpful)", f"{avg_up} chars")
    with col2:
        avg_down = round(sum(down_lens) / len(down_lens))
        st.metric("Avg length (👎 Not helpful)", f"{avg_down} chars")

    # Histogram
    lens_data = pd.DataFrame({
        "Helpful": up_lens + down_lens,
        "Rating": ["👍"] * len(up_lens) + ["👎"] * len(down_lens),
    })
    st.histogram(lens_data, x="Helpful", color="Rating", nbins=20)

# ────────────────────────────────────────────────────────────────────────────────
# Recent feedback

st.markdown("### Recent Feedback (last 10)")
recent = sorted(rows, key=lambda r: r.get("timestamp", ""), reverse=True)[:10]
for r in recent:
    emoji = "👍" if r.get("rating") == 1 else "👎"
    ts = r.get("timestamp", "—")[:19]
    hint = r.get("hint_kind", "—")
    nav = r.get("primary_nav", "—")
    length = r.get("why_now_len", 0)
    st.caption(f"{emoji} **{ts}** | {hint} → {nav} | {length} chars")

st.divider()
st.caption(f"Data from: {log_dir} | Refreshes every 60s")
