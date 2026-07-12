"""Визуализации для страницы «Мой прогресс»: Emotional Heatmap, подграф KG + эмоции."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import plotly.express as px
import plotly.graph_objects as go
from streamlit_agraph import Config, Edge, Node

from app.knowledge_service import JsonKnowledgeGraph, get_personalized_subgraph
from app.learner_model_service import (
    PersonalizedLearnerModel,
    emotional_state_to_score,
    get_emotional_heatmap_pivot,
    load_emotional_heatmap_rows,
)


def _emoji_for_state(state: str | None) -> str:
    s = (state or "neutral").strip().lower()
    return {
        "frustrated": "😓",
        "engaged": "😊",
        "bored": "😴",
        "confident": "😎",
        "neutral": "😐",
    }.get(s, "😐")


def _last_state_by_concept(rows: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in sorted(rows, key=lambda x: str(x.get("date") or "")):
        c = str(r.get("concept") or "global").strip() or "global"
        st = str(r.get("state") or "neutral").strip().lower()
        out[c] = st
    return out


def build_course_filter_label(scope: dict[str, Any] | None) -> str:
    """Human label for the active-course progress filter."""
    if not isinstance(scope, dict) or not scope.get("active"):
        return "Весь прогресс"
    title = str(scope.get("title") or scope.get("folder_rel") or "активный курс").strip()
    return f"Только активный курс: {title}"


def build_emotional_heatmap_figure(
    *,
    profile: PersonalizedLearnerModel,
    seed_concepts: list[str],
    last_days: int = 30,
):
    """
    Возвращает (fig, used_synthetic).
    Если в KV нет истории — синтетическая матрица от текущего ``emotional_state`` по концептам подграфа.
    """
    pivot = get_emotional_heatmap_pivot(last_days=last_days)
    if pivot is not None and not pivot.empty:
        fig = px.imshow(
            pivot,
            text_auto=".2f",
            color_continuous_scale="RdYlGn",
            aspect="auto",
            title="Эмоциональное состояние по темам (0–1, выше — комфортнее)",
        )
        fig.update_layout(margin=dict(l=40, r=40, t=50, b=80))
        return fig, False

    concepts = [c for c in seed_concepts if str(c).strip()][:12]
    if not concepts:
        concepts = ["global"]
    score = emotional_state_to_score(str(profile.emotional_state))
    days = [
        (datetime.now(timezone.utc).date() - timedelta(days=i)).isoformat()
        for i in range(min(last_days, 14) - 1, -1, -1)
    ]
    data = []
    for c in concepts:
        for d in days:
            data.append({"concept": c, "date": d, "emotional_score": score})
    import pandas as pd

    df = pd.DataFrame(data)
    pt = df.pivot(index="concept", columns="date", values="emotional_score")
    fig = px.imshow(
        pt,
        text_auto=".2f",
        color_continuous_scale="RdYlGn",
        aspect="auto",
        title="Нет сохранённой истории эмоций — показан текущий срез (после tutor/quiz появятся реальные точки)",
    )
    fig.update_layout(margin=dict(l=40, r=40, t=60, b=80))
    return fig, True


def build_quiz_activity_timeline(quiz_rows: list[dict[str, Any]] | None) -> go.Figure | None:
    """Простая линия: число обновлений quiz_mastery по дням."""
    if not quiz_rows:
        return None
    from collections import Counter

    days: Counter[str] = Counter()
    for row in quiz_rows:
        raw = row.get("last_updated")
        if not raw:
            continue
        try:
            d = str(raw).replace("Z", "+00:00")
            dt = datetime.fromisoformat(d)
            days[dt.date().isoformat()] += 1
        except (TypeError, ValueError):
            continue
    if not days:
        return None
    xs = sorted(days.keys())
    ys = [days[k] for k in xs]
    fig = go.Figure(go.Scatter(x=xs, y=ys, mode="lines+markers", line_color="#7E57C2"))
    fig.update_layout(
        title="Активность quiz (обновления по дням)",
        margin=dict(l=40, r=40, t=50, b=60),
        xaxis_title="Дата",
        yaxis_title="События",
    )
    return fig


def build_personalized_subgraph_elements(
    kg: JsonKnowledgeGraph,
    *,
    seed_topic: str | None,
    profile: PersonalizedLearnerModel,
    limit: int = 20,
) -> tuple[list[Node], list[Edge]]:
    """Узлы/рёбра для agraph: mastery из ``profile.mastery_vector``, эмодзи — последний снимок по концепту или глобальный профиль."""
    sub = get_personalized_subgraph(seed_topic=seed_topic, limit=limit, kg=kg)
    node_entries = sub.get("nodes") or []
    ids = [str(n.get("id") or "").strip() for n in node_entries if str(n.get("id") or "").strip()]
    if not ids:
        return [], []

    rows = load_emotional_heatmap_rows()
    last_st = _last_state_by_concept(rows)
    mv = profile.mastery_vector or {}
    global_emo = str(profile.emotional_state)

    nodes: list[Node] = []
    for cid in ids:
        m = float(mv.get(cid, mv.get("avg") or 0.0))
        m = max(0.0, min(1.0, m))
        if m >= 0.66:
            color = "#00c853"
        elif m >= 0.33:
            color = "#ffcc00"
        else:
            color = "#ff5252"
        st = last_st.get(cid) or last_st.get("global") or global_emo
        emo = _emoji_for_state(st)
        label = f"{cid} {emo}\n{m:.0%}"
        title = f"{cid}\nmastery≈{m:.2f}\nэмоция: {st}"
        nodes.append(
            Node(
                id=cid,
                label=label,
                color=color,
                size=22 + int(m * 34),
                title=title,
            )
        )
    visible = {n.id for n in nodes}
    edges: list[Edge] = []
    concepts = kg.get_concepts()
    for cid in ids:
        if cid not in visible:
            continue
        data = concepts.get(cid)
        if not isinstance(data, dict):
            continue
        for target in data.get("prerequisites") or []:
            t = str(target).strip()
            if t in visible:
                edges.append(Edge(source=t, target=cid, color="#888888"))

    return nodes, edges


__all__ = [
    "build_course_filter_label",
    "build_emotional_heatmap_figure",
    "build_personalized_subgraph_elements",
    "build_quiz_activity_timeline",
]
