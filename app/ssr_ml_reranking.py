"""Локальный logistic regression (numpy) для reranking Smart Study Router (US-20.1 Level 1).

Веса: ``app/ssr_ml_reranking_weights.json`` (генерация: ``scripts/ml/train_ssr_forgetting_curve_export.py``).
Без sklearn на inference; задержка контролируется вызывающим кодом.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import numpy as np

_WEIGHTS_PATH = Path(__file__).resolve().parent / "ssr_ml_reranking_weights.json"
_LOCK = threading.Lock()
_CACHE: dict[str, Any] | None = None


def _load_weights_unlocked() -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    raw = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
    _CACHE = {
        "hint_classes": list(raw["hint_classes"]),
        "mean": np.array(raw["mean"], dtype=np.float64),
        "std": np.array(raw["std"], dtype=np.float64),
        "W": np.array(raw["W"], dtype=np.float64),
        "b": np.array(raw["b"], dtype=np.float64),
    }
    return _CACHE


def load_ssr_ml_weights() -> dict[str, Any]:
    with _LOCK:
        return _load_weights_unlocked()


def feature_vector_from_dict(feats: dict[str, Any], *, prior_rule_top_hint_kind: str) -> np.ndarray:
    """14 признаков в том же порядке, что при обучении (см. train_ssr_forgetting_curve_export.py)."""
    hint_classes = tuple(load_ssr_ml_weights()["hint_classes"])
    prior_map = {h: i for i, h in enumerate(hint_classes)}
    prior = prior_map.get(str(prior_rule_top_hint_kind), prior_map["safe_default"])
    return np.array(
        [
            float(feats["time_since_last_review_hours"]),
            float(feats["quiz_score_last_3_avg"]),
            float(feats["concept_difficulty"]),
            float(feats["session_duration_avg_minutes"]),
            float(feats["time_of_day_hour"]),
            float(feats["day_of_week"]),
            float(feats["cards_due_count"]),
            float(feats["sm2_due_count"]),
            1.0 if feats["quiz_failed_recent"] else 0.0,
            float(feats["session_fatigue"]),
            float(feats["mastery_gap_score"]),
            float(feats["adaptive_plan_backlog_signals"]),
            1.0 if feats["tutor_stub_active"] else 0.0,
            float(prior) / max(1.0, float(len(hint_classes) - 1)),
        ],
        dtype=np.float64,
    )


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - float(np.max(z))
    e = np.exp(z)
    s = float(np.sum(e))
    return e / max(s, 1e-12)


def predict_hint_probability_map(
    feats: dict[str, Any],
    *,
    prior_rule_top_hint_kind: str,
) -> dict[str, float]:
    w = load_ssr_ml_weights()
    x = feature_vector_from_dict(feats, prior_rule_top_hint_kind=prior_rule_top_hint_kind)
    xn = (x - w["mean"]) / w["std"]
    p = _softmax(w["W"] @ xn + w["b"])
    return {h: float(p[i]) for i, h in enumerate(w["hint_classes"])}


def predict_hint_probability_map_or_empty(
    feats: dict[str, Any],
    *,
    prior_rule_top_hint_kind: str,
) -> dict[str, float]:
    try:
        if not _WEIGHTS_PATH.exists():
            return {}
        return predict_hint_probability_map(feats, prior_rule_top_hint_kind=prior_rule_top_hint_kind)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return {}
