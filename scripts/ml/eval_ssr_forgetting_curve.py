"""Evaluate the local SSR forgetting-curve model."""

from __future__ import annotations

import argparse
import pickle
from pathlib import Path
from typing import Any

import pandas as pd

from app.ssr_ai.eval_harness import MODEL_PATH, REPORT_PATH, TEST_DATA_PATH


def _metrics(y_true: Any, y_pred: Any, y_prob: Any) -> dict[str, Any]:
    try:
        from sklearn.metrics import (
            accuracy_score,
            brier_score_loss,
            precision_recall_fscore_support,
            roc_auc_score,
        )
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit("Install ML extras first: pip install -e .[ml]") from exc
    out: dict[str, Any] = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "brier_score": float(brier_score_loss(y_true, y_prob)),
    }
    try:
        out["auc_roc"] = float(roc_auc_score(y_true, y_prob))
    except ValueError:
        out["auc_roc"] = None
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=[0, 1],
        zero_division=0,
    )
    out["per_class"] = {
        str(label): {
            "precision": float(precision[idx]),
            "recall": float(recall[idx]),
            "f1": float(f1[idx]),
            "support": int(support[idx]),
        }
        for idx, label in enumerate([0, 1])
    }
    return out


def evaluate(test_path: Path, model_path: Path, report_path: Path) -> dict[str, Any]:
    df = pd.read_parquet(test_path)
    if df.empty:
        raise SystemExit(f"No test rows in {test_path}")
    with model_path.open("rb") as handle:
        artifact = pickle.load(handle)
    feature_names = artifact["feature_names"]
    model = artifact["model"]
    x = df[feature_names].astype(float).fillna(0.0)
    y_true = df["recalled"].astype(int)
    y_pred = model.predict(x)
    y_prob = model.predict_proba(x)[:, 1]
    metrics = _metrics(y_true, y_pred, y_prob)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# SSR Forgetting Curve v1 Report",
        "",
        f"- Test rows: {len(df)}",
        f"- Accuracy: {metrics['accuracy']:.4f}",
        f"- AUC-ROC: {metrics['auc_roc'] if metrics['auc_roc'] is not None else 'n/a'}",
        f"- Calibration Brier score: {metrics['brier_score']:.4f}",
        "",
        "## Per-Class Precision/Recall",
        "",
        "| class | precision | recall | f1 | support |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, values in metrics["per_class"].items():
        lines.append(
            f"| {label} | {values['precision']:.4f} | {values['recall']:.4f} | "
            f"{values['f1']:.4f} | {values['support']} |"
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"report_path": str(report_path), "test_rows": int(len(df)), **metrics}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", type=Path, default=TEST_DATA_PATH)
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    summary = evaluate(args.test, args.model, args.report)
    print(summary)


if __name__ == "__main__":
    main()
