"""
Plotly + streamlit-agraph helpers для Knowledge Graph и дашборда прогресса (UI).
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Set, Tuple

import plotly.express as px
import plotly.graph_objects as go
try:
    from streamlit_agraph import Edge, Node
except ImportError:  # not installed in test/API-only environments
    Edge = Node = None  # type: ignore[assignment,misc]

from app.knowledge_graph import JsonKnowledgeGraph, get_mastery_vector, knowledge_graph
from app.learner_state_scope import filter_due_reviews_for_kg, get_quiz_mastery_rows_for_kg
from app.quiz_adaptive import LEVELS
from app.user_state import _with_db, get_weekly_goals_state, list_topic_reading_rows


def _truncate_desc(text: str, max_len: int = 120) -> str:
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def _quiz_level_to_kg_band(qm: str) -> str:
    """Сопоставление quiz_mastery (recognition/…) с фильтром KG (beginner/…)."""
    x = (qm or "").strip().lower()
    if x == "transfer":
        return "advanced"
    if x == "recall":
        return "intermediate"
    return "beginner"


class VisualizationService:
    """Фабрики фигур и узлов/рёбер для UI (без Streamlit-состояния)."""

    @staticmethod
    def _kg_nodes_from_quiz_mastery(filter_level: str, learned_ids: Set[str]) -> Tuple[List[Node], List[Edge]]:
        """Если ``concept_graph.json`` без концептов — показать узлы из quiz_mastery (рёбер нет)."""
        rows = _fetch_quiz_mastery_rows()
        nodes: List[Node] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("concept") or "").strip()
            if not name:
                continue
            qm = str(row.get("current_level") or "recognition").strip().lower()
            if qm not in LEVELS:
                qm = "recognition"
            band = _quiz_level_to_kg_band(qm)
            if filter_level != "all" and band != filter_level:
                continue
            learned = name in learned_ids
            color = "#4CAF50" if learned else "#2196F3"
            size = 35 if learned else 25
            ss = int(row.get("success_streak") or 0)
            title = f"{name}\nуровень quiz: {qm} · streak {ss}"
            nodes.append(
                Node(
                    id=name,
                    label=name,
                    color=color,
                    size=size,
                    title=title,
                )
            )
        return nodes, []

    @staticmethod
    def get_knowledge_graph_nodes_edges(
        kg: JsonKnowledgeGraph,
        filter_level: str,
        learned_ids: Set[str],
    ) -> Tuple[List[Node], List[Edge]]:
        concepts = kg.get_concepts()
        if not concepts:
            return VisualizationService._kg_nodes_from_quiz_mastery(filter_level, learned_ids)

        nodes: List[Node] = []
        edges: List[Edge] = []

        for name, data in concepts.items():
            if not isinstance(data, dict):
                continue
            level = (data.get("level") or "intermediate")
            if isinstance(level, str):
                level = level.strip().lower()
            else:
                level = "intermediate"
            if filter_level != "all" and level != filter_level:
                continue

            learned = name in learned_ids or bool(data.get("learned"))
            color = "#4CAF50" if learned else "#2196F3"
            size = 35 if learned else 25
            desc = _truncate_desc(str(data.get("description") or ""))
            title = f"{name}\n{desc}" if desc else str(name)
            nodes.append(
                Node(
                    id=name,
                    label=name,
                    color=color,
                    size=size,
                    title=title,
                )
            )

        visible = {n.id for n in nodes}
        for src, data in concepts.items():
            if src not in visible or not isinstance(data, dict):
                continue
            for target in data.get("prerequisites") or []:
                t = str(target)
                if t in visible:
                    edges.append(
                        Edge(
                            source=t,
                            target=src,
                            label="→",
                            color="#FF9800",
                        )
                    )

        return nodes, edges

    @staticmethod
    def create_mastery_gauge(mastery: float) -> go.Figure:
        val = float(mastery)
        val = max(0.0, min(100.0, val))
        return go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=val,
                number={"suffix": "%"},
                title={"text": "Mastery"},
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar": {"color": "#4CAF50"},
                    "steps": [
                        {"range": [0, 50], "color": "rgba(255,152,0,0.35)"},
                        {"range": [50, 100], "color": "rgba(76,175,80,0.2)"},
                    ],
                },
            )
        )

    @staticmethod
    def create_mastery_vector_radar(
        mastery_vector: Dict[str, float],
        *,
        top_n: int = 10,
        title: str = "Mastery по концептам (0–100%)",
    ) -> go.Figure:
        """Radar по вектору освоения (``get_mastery_vector``): ключ ``avg`` исключается."""
        items = [
            (str(k).strip(), float(v))
            for k, v in (mastery_vector or {}).items()
            if str(k).strip() and str(k).strip().lower() != "avg"
        ]
        items.sort(key=lambda x: -x[1])
        n = max(3, min(int(top_n), 24))
        items = items[:n]
        if not items:
            fig = go.Figure()
            fig.add_annotation(
                text="Нет данных mastery_vector",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            fig.update_layout(margin=dict(l=40, r=40, t=40, b=40))
            return fig
        labels = [k for k, _ in items]
        values = [max(0.0, min(100.0, v * 100.0)) for _, v in items]
        fig = go.Figure(
            go.Scatterpolar(
                r=values + values[:1],
                theta=labels + labels[:1],
                fill="toself",
                line_color="#5C6BC0",
                name="mastery",
            )
        )
        fig.update_layout(
            title=title,
            polar={"radialaxis": {"visible": True, "range": [0, 100]}},
            showlegend=False,
            margin=dict(l=40, r=40, t=50, b=40),
        )
        return fig

    @staticmethod
    def create_radar_chart(levels: Dict[str, int]) -> go.Figure:
        categories = list(levels.keys())
        values = [int(levels.get(k, 0)) for k in categories]
        vmax = max(values) if values else 0
        rmax = max(4, vmax + 1)
        fig = go.Figure(
            go.Scatterpolar(
                r=values + values[:1],
                theta=categories + categories[:1],
                fill="toself",
                line_color="#2196F3",
                name="Концепты",
            )
        )
        fig.update_layout(
            polar={
                "radialaxis": {"visible": True, "range": [0, rmax]},
            },
            showlegend=False,
            margin=dict(l=40, r=40, t=40, b=40),
        )
        return fig

    @staticmethod
    def create_treemap(levels: Dict[str, int]) -> go.Figure:
        names = list(levels.keys())
        vals = [int(levels.get(k, 0)) for k in names]
        if not names or sum(vals) == 0:
            fig = go.Figure()
            fig.add_annotation(
                text="Нет данных по level",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            fig.update_layout(margin=dict(l=20, r=20, t=40, b=20))
            return fig
        root_label = "Все уровни"
        labels = [root_label] + names
        parents = [""] + [root_label] * len(names)
        values = [sum(vals)] + vals
        return px.treemap(
            names=labels,
            parents=parents,
            values=values,
            title="Распределение по level",
        )

    @staticmethod
    def get_mastery_nodes_edges(
        kg: JsonKnowledgeGraph,
        mastery_overlay: Dict[str, Dict[str, Any]],
        *,
        palette: str = "level",
    ) -> Tuple[List[Node], List[Edge]]:
        """Узлы/рёбра графа: ``palette=level`` — золото/оранж/зелень по уровню; ``ryg`` — красный/жёлтый/зелёный (слабый/в работе/mastered)."""
        concepts = kg.get_concepts()
        nodes: List[Node] = []
        edges: List[Edge] = []

        ryg = {
            "recognition": "#e53935",
            "recall": "#fbc02d",
            "transfer": "#2e7d32",
        }

        for name, data in concepts.items():
            if not isinstance(data, dict):
                continue
            ov = mastery_overlay.get(name) or {}
            level = str(ov.get("level") or "recognition")
            if palette == "ryg":
                color = ryg.get(level, "#9E9E9E")
            else:
                color = str(ov.get("color_hex") or "#9E9E9E")
            due = bool(ov.get("due"))
            desc = _truncate_desc(str(data.get("description") or ""))
            title = f"{name}\n{level}" + (f"\n{desc}" if desc else "")
            if due:
                title += "\n(повтор по расписанию)"
            size = 38 if due else 28
            nodes.append(
                Node(
                    id=name,
                    label=name,
                    color=color,
                    size=size,
                    title=title,
                )
            )

        visible = {n.id for n in nodes}
        for src, data in concepts.items():
            if src not in visible or not isinstance(data, dict):
                continue
            for target in data.get("prerequisites") or []:
                t = str(target)
                if t in visible:
                    edges.append(
                        Edge(
                            source=t,
                            target=src,
                            label="→",
                            color="#FF9800",
                        )
                    )

        return nodes, edges


LEVEL_COLOR_HEX: Dict[str, str] = {
    "recognition": "#FFD700",
    "recall": "#FF9800",
    "transfer": "#27AE60",
}

LEVEL_COLOR_NAME: Dict[str, str] = {
    "recognition": "yellow",
    "recall": "orange",
    "transfer": "green",
}


def _normalize_level(raw: str | None) -> str:
    lv = (raw or "recognition").strip().lower()
    return lv if lv in LEVELS else "recognition"


def _fetch_quiz_mastery_rows() -> List[Dict[str, Any]]:
    def _work(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT concept, current_level, success_streak, last_updated
            FROM quiz_mastery
            """
        ).fetchall()
        return [dict(r) for r in rows]

    return _with_db(_work)


def _build_prerequisite_graph_payload(kg: JsonKnowledgeGraph) -> Dict[str, Any]:
    concepts = kg.get_concepts()
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, str]] = []
    for cid, data in concepts.items():
        if not isinstance(data, dict):
            continue
        nodes.append(
            {
                "id": cid,
                "label": cid,
                "description": (str(data.get("description") or ""))[:240],
                "learned": bool(data.get("learned")),
            }
        )
        for p in data.get("prerequisites") or []:
            ps = str(p)
            edges.append({"from": ps, "to": cid})
    return {"nodes": nodes, "edges": edges}


def _build_mastery_overlay(
    concept_ids: List[str],
    quiz_rows: List[Dict[str, Any]],
    due_reviews: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    by_concept = {str(r.get("concept") or ""): r for r in quiz_rows}
    due_set = {str(d.get("concept") or "") for d in due_reviews}
    out: Dict[str, Dict[str, Any]] = {}
    for cid in concept_ids:
        row = by_concept.get(cid)
        level = _normalize_level(str(row.get("current_level")) if row else None)
        out[cid] = {
            "level": level,
            "color_name": LEVEL_COLOR_NAME.get(level, "gray"),
            "color_hex": LEVEL_COLOR_HEX.get(level, "#9E9E9E"),
            "due": cid in due_set,
            "success_streak": int(row.get("success_streak") or 0) if row else 0,
        }
    return out


def _next_topic_recommendation(
    kg: JsonKnowledgeGraph,
    overlay: Dict[str, Dict[str, Any]],
    due_reviews: List[Dict[str, Any]],
    reading_topics: List[Dict[str, Any]],
) -> Dict[str, Any]:
    concepts = kg.get_concepts()
    all_ids = [cid for cid, c in concepts.items() if isinstance(c, dict)]
    if not all_ids:
        return {
            "topic": None,
            "reason": "empty_graph",
            "message": "В графе нет концептов — заполните data/concept_graph.json.",
        }

    topo = kg.topological_sort(all_ids)
    due_set = {str(d.get("concept") or "") for d in due_reviews}

    for tid in topo:
        if tid in due_set:
            return {"topic": tid, "reason": "spaced_repetition_due", "message": None}

    for tid in topo:
        lv = overlay.get(tid, {}).get("level", "recognition")
        if str(lv) != "transfer":
            return {"topic": tid, "reason": "quiz_mastery_path", "message": None}

    concept_set = set(all_ids)
    for row in reading_topics:
        tid = str(row.get("topic_id") or "").strip()
        if tid in concept_set:
            prog = row.get("progress")
            if prog is None or float(prog) < 1.0:
                return {"topic": tid, "reason": "reading_incomplete", "message": None}

    return {"topic": None, "reason": "all_done", "message": "Всё освоено!"}


class MasteryDashboard:
    """Агрегация quiz_mastery, spaced repetition, reading_status и prerequisite-графа."""

    def __init__(self, kg: JsonKnowledgeGraph | None = None) -> None:
        self._kg = kg or knowledge_graph

    def get_mastery_data(self, user_id: str = "default") -> Dict[str, Any]:
        """Сводка для вкладки «Прогресс» и GET ``/dashboard/mastery``.

        Контракт Progress surface (без новых эндпоинтов): ``concepts_mastered``,
        ``quiz_mastery_rows``, ``due_reviews`` / ``due_count``, ``mastery_vector``,
        ``prerequisite_graph`` (nodes, edges, mastery_overlay), ``weekly_goals``
        (``get_weekly_goals_state``), ``gamification`` (``get_snapshot``: в т.ч.
        ``daily_streak`` и ``quiz_streak`` геймификации — не путать со стриком
        дней в UI-квизах из ``quiz_stats``).
        """
        _ = user_id  # один локальный пользователь; поле зарезервировано
        quiz_rows = get_quiz_mastery_rows_for_kg(self._kg)
        due = filter_due_reviews_for_kg(self._kg, limit=300)
        reading = list_topic_reading_rows(limit=200)

        counts: Dict[str, int] = {"recognition": 0, "recall": 0, "transfer": 0}
        for row in quiz_rows:
            lv = _normalize_level(str(row.get("current_level")))
            counts[lv] = counts.get(lv, 0) + 1

        graph_payload = _build_prerequisite_graph_payload(self._kg)
        concept_ids = [n["id"] for n in graph_payload["nodes"]]
        overlay = _build_mastery_overlay(concept_ids, quiz_rows, due)
        rec = _next_topic_recommendation(self._kg, overlay, due, reading)

        from app.gamification_service import get_snapshot

        mv_ids = concept_ids if concept_ids else None
        mastery_vector = get_mastery_vector(user_id=None, concept_ids=mv_ids)

        return {
            "concepts_mastered": counts,
            "quiz_mastery_rows": quiz_rows,
            "due_reviews": due,
            "due_count": len(due),
            "reading_topics": reading,
            "next_recommendation": rec,
            "gamification": get_snapshot(),
            "weekly_goals": get_weekly_goals_state(),
            "mastery_vector": mastery_vector,
            "prerequisite_graph": {
                **graph_payload,
                "mastery_overlay": overlay,
            },
        }


vis_service = VisualizationService()
dashboard = MasteryDashboard()

__all__ = [
    "MasteryDashboard",
    "VisualizationService",
    "dashboard",
    "vis_service",
]
