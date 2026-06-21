"""Train local SSR forgetting-curve model and optional reranking weights."""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.ssr_ai.eval_harness import HINT_KINDS, MODEL_PATH, REQUIRED_FEATURE_KEYS, TRAIN_DATA_PATH

RERANKING_DATA_PATH = TRAIN_DATA_PATH.parent / "ssr_reranking_features.parquet"
WEIGHTS_PATH = Path(__file__).resolve().parents[2] / "app" / "ssr_ml_reranking_weights.json"

FORGETTING_FEATURES = [
    "time_since_last_review_hours",
    "quality",
    "easiness_before",
    "interval_before",
    "repetitions",
    "card_age_days",
    "review_sequence_position",
]

RERANKING_NUMERIC_FEATURES = [
    "time_since_last_review_hours",
    "quiz_score_last_3_avg",
    "concept_difficulty",
    "session_duration_avg_minutes",
    "time_of_day_hour",
    "day_of_week",
    "cards_due_count",
    "sm2_due_count",
    "quiz_failed_recent",
    "session_fatigue",
    "mastery_gap_score",
    "adaptive_plan_backlog_signals",
    "tutor_stub_active",
]


def _require_sklearn() -> Any:
    try:
        from sklearn.linear_model import LogisticRegression
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit("Install ML extras first: pip install -e .[ml]") from exc
    return LogisticRegression


def train_forgetting_model(train_path: Path, model_path: Path) -> dict[str, Any]:
    LogisticRegression = _require_sklearn()
    df = pd.read_parquet(train_path)
    if df.empty:
        raise SystemExit(f"No forgetting-curve rows in {train_path}")
    missing = [col for col in FORGETTING_FEATURES + ["recalled"] if col not in df.columns]
    if missing:
        raise SystemExit(f"Missing forgetting columns: {missing}")
    y = df["recalled"].astype(int)
    if y.nunique() < 2:
        raise SystemExit("Need at least two recalled classes to train forgetting model")
    x = df[FORGETTING_FEATURES].astype(float).fillna(0.0)
    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(x, y)
    artifact = {
        "kind": "ssr_forgetting_curve_v1",
        "feature_names": FORGETTING_FEATURES,
        "model": model,
        "train_rows": int(len(df)),
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    with model_path.open("wb") as handle:
        pickle.dump(artifact, handle)
    return {"model_path": str(model_path), "train_rows": int(len(df))}


def _encoded_reranking_matrix(df: pd.DataFrame, hint_classes: list[str]) -> np.ndarray:
    prior_map = {name: i for i, name in enumerate(hint_classes)}
    x = df[RERANKING_NUMERIC_FEATURES].astype(float).fillna(0.0).to_numpy(dtype=np.float64)
    prior = (
        df["prior_rule_top_hint_kind"]
        .fillna("safe_default")
        .astype(str)
        .map(lambda value: prior_map.get(value, prior_map.get("safe_default", 0)))
        .astype(float)
        .to_numpy(dtype=np.float64)
    )
    prior = prior / max(1.0, float(len(hint_classes) - 1))
    return np.column_stack([x, prior])


def train_reranking_weights(reranking_path: Path, weights_path: Path) -> dict[str, Any]:
    LogisticRegression = _require_sklearn()
    if not reranking_path.exists():
        return {"weights_path": str(weights_path), "updated": False, "reason": "missing_reranking_dataset"}
    df = pd.read_parquet(reranking_path)
    if df.empty:
        return {"weights_path": str(weights_path), "updated": False, "reason": "empty_reranking_dataset"}
    missing = sorted((REQUIRED_FEATURE_KEYS | {"hint_kind"}) - set(df.columns))
    if missing:
        raise SystemExit(f"Missing reranking columns: {missing}")
    y = df["hint_kind"].fillna("safe_default").astype(str)
    y = y.where(y.isin(HINT_KINDS), "safe_default")
    if y.nunique() < 2:
        return {"weights_path": str(weights_path), "updated": False, "reason": "single_reranking_class"}
    hint_classes = sorted(HINT_KINDS)
    x = _encoded_reranking_matrix(df, hint_classes)
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std < 1e-9] = 1.0
    xn = (x - mean) / std
    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(xn, y)
    coef_by_class: dict[str, tuple[np.ndarray, float]] = {}
    if len(model.classes_) == 2 and model.coef_.shape[0] == 1:
        neg, pos = str(model.classes_[0]), str(model.classes_[1])
        coef_by_class[neg] = (-model.coef_[0], -float(model.intercept_[0]))
        coef_by_class[pos] = (model.coef_[0], float(model.intercept_[0]))
    else:
        for idx, cls in enumerate(model.classes_):
            coef_by_class[str(cls)] = (model.coef_[idx], float(model.intercept_[idx]))
    zeros = np.zeros(x.shape[1], dtype=np.float64)
    weights = {
        "hint_classes": hint_classes,
        "feature_dim": int(x.shape[1]),
        "mean": mean.round(8).tolist(),
        "std": std.round(8).tolist(),
        "W": [coef_by_class.get(cls, (zeros, 0.0))[0].round(8).tolist() for cls in hint_classes],
        "b": [coef_by_class.get(cls, (zeros, 0.0))[1] for cls in hint_classes],
        "source": "scripts/ml/train_ssr_forgetting_curve.py",
        "train_rows": int(len(df)),
    }
    weights_path.write_text(json.dumps(weights, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"weights_path": str(weights_path), "updated": True, "reranking_rows": int(len(df))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=TRAIN_DATA_PATH)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--reranking", type=Path, default=RERANKING_DATA_PATH)
    parser.add_argument("--weights", type=Path, default=WEIGHTS_PATH)
    args = parser.parse_args()
    summary = train_forgetting_model(args.train, args.model)
    summary["reranking_weights"] = train_reranking_weights(args.reranking, args.weights)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
