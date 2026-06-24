"""
Расширенная аналитика по локальным данным (quiz_results, spaced_repetition, геймификация).

Без внешних LLM: эвристики и простые графики (Plotly JSON).
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from app.knowledge_graph import get_active_knowledge_graph
from app.learner_state_scope import active_concept_ids, weak_concepts_for_kg
from app.user_state import _with_db, get_learner_state_diagnostics

logger = logging.getLogger(__name__)


def _quiz_result_rows(limit: int = 2000, *, concept_ids: set[str] | None = None) -> list[dict[str, Any]]:

    def _work(conn):
        rows = conn.execute(
            """
            SELECT concept, level, score, timestamp
            FROM quiz_results
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        data = [dict(r) for r in rows]
        if not concept_ids:
            return data
        return [row for row in data if str(row.get("concept") or "").strip() in concept_ids]

    return _with_db(_work)


def _spaced_rows(*, concept_ids: set[str] | None = None) -> list[dict[str, Any]]:

    def _work(conn):
        rows = conn.execute(
            "SELECT concept, easiness, interval_days, repetitions, next_review, last_review FROM spaced_repetition"
        ).fetchall()
        data = [dict(r) for r in rows]
        if not concept_ids:
            return data
        return [row for row in data if str(row.get("concept") or "").strip() in concept_ids]

    return _with_db(_work)


def _today_utc_date() -> str:
    return datetime.now(tz=timezone.utc).date().isoformat()


def build_forgetting_curve_points(*, concept_ids: set[str] | None = None) -> list[dict[str, float]]:
    """
    Эвристика «кривая забывания»: средняя оценка удержания по SM-2 интервалам (0..14 дней).
    Не нейромодель — для тренда в UI.
    """
    rows = _spaced_rows(concept_ids=concept_ids)
    if not rows:
        return [{"day": float(d), "retention": max(0.05, 1.0 - d * 0.06)} for d in range(15)]

    points: list[dict[str, float]] = []
    for d in range(15):
        acc = 0.0
        for r in rows:
            ef = float(r.get("easiness") or 2.5)
            iv = max(1, int(r.get("interval_days") or 1))
            lam = max(0.3, iv * ef * 0.15)
            acc += math.exp(-d / lam)
        acc /= len(rows)
        points.append({"day": float(d), "retention": round(min(1.0, max(0.0, acc)), 4)})
    return points


def get_advanced_analytics() -> dict[str, Any]:
    """Сводка для API и Streamlit: heatmap-данные, кривая, ROI-текст, рекомендация."""
    import pandas as pd

    kg = get_active_knowledge_graph()
    concept_ids = active_concept_ids(kg)
    rows = _quiz_result_rows(concept_ids=concept_ids)
    gam: dict[str, Any] = {}
    try:
        from app.gamification_service import get_snapshot

        gam = get_snapshot()
    except Exception as exc:  # noqa: BLE001 - gamification is optional enrichment; degrade to empty
        logger.error("advanced_analytics_gamification_unavailable: %s", exc, exc_info=True)

    weak = weak_concepts_for_kg(kg, threshold=60, limit=8)
    today = _today_utc_date()
    diagnostics = get_learner_state_diagnostics()

    time_roi = "Нет данных quiz_results за сегодня."
    n_today = 0
    heatmap = {"z": [], "x": [], "y": []}
    if rows:
        try:
            df = pd.DataFrame(rows)
            df["ts"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.dropna(subset=["ts"])
            if not df.empty:
                df["date"] = df["ts"].dt.date.astype(str)
                n_today = int((df["date"] == today).sum())
                est_min = max(5, n_today * 4)
                roi_guess = min(25, 8 + n_today * 3)
                time_roi = (
                    f"Сегодня зафиксировано **{n_today}** попыток в quiz_results (~{est_min} мин) "
                    f"— оценка вклада в удержание ~**+{roi_guess}%** к «чувству прогресса» (эвристика)."
                )

                top_c = (
                    df.groupby(["date", "concept"], as_index=False)["score"]
                    .mean()
                    .sort_values("date")
                    .tail(200)
                )
                if not top_c.empty:
                    pivot = top_c.pivot_table(
                        index="concept", columns="date", values="score", aggfunc="mean"
                    )
                    heatmap = {
                        "z": pivot.fillna(0).values.tolist(),
                        "x": [str(c) for c in pivot.columns],
                        "y": [str(i) for i in pivot.index],
                    }
        except Exception as exc:  # noqa: BLE001 - pandas/groupby may fail on odd rows; keep ROI text only
            logger.error("advanced_analytics_heatmap_build_failed: %s", exc, exc_info=True)
            time_roi = "Не удалось построить heatmap (проверьте формат timestamp в quiz_results)."

    fc = build_forgetting_curve_points(concept_ids=concept_ids)

    if weak:
        rec = (
            f"Слабее всего сейчас: {', '.join(weak[:4])}. "
            f"Добавьте 1–2 interleaved quiz в неделю по этим концептам."
        )
    else:
        rec = "Слабых концептов ниже порога нет — поддерживайте стрик и интервальные повторения."

    return {
        "heatmap": heatmap,
        "forgetting_curve": fc,
        "time_roi_text": time_roi,
        "quiz_attempts_today": n_today,
        "weekly_ai_recommendation": rec,
        "gamification": gam,
        "weak_concepts": weak,
        "learner_state_diagnostics": diagnostics,
    }


__all__ = ["build_forgetting_curve_points", "get_advanced_analytics"]
