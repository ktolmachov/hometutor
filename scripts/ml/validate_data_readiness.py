"""Validate local SSR ML data readiness thresholds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.ssr_ai.eval_harness import TRAIN_DATA_PATH

RERANKING_DATA_PATH = TRAIN_DATA_PATH.parent / "ssr_reranking_features.parquet"


def _frame_report(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"rows": 0, "null_rates": {}, "time_span": None}
    null_rates = {col: round(float(df[col].isna().mean()), 4) for col in df.columns}
    time_span = None
    for col in ("reviewed_at", "created_at"):
        if col in df.columns:
            ts = pd.to_datetime(df[col], utc=True, errors="coerce").dropna()
            if not ts.empty:
                time_span = {"start": ts.min().isoformat(), "end": ts.max().isoformat()}
                break
    return {"rows": int(len(df)), "null_rates": null_rates, "time_span": time_span}


def validate(data_dir: Path) -> dict[str, Any]:
    train_path = data_dir / "ssr_forgetting_curve_train.parquet"
    test_path = data_dir / "ssr_forgetting_curve_test.parquet"
    reranking_path = data_dir / "ssr_reranking_features.parquet"
    forgetting = pd.concat(
        [
            pd.read_parquet(path)
            for path in (train_path, test_path)
            if path.exists()
        ],
        ignore_index=True,
    ) if train_path.exists() or test_path.exists() else pd.DataFrame()
    reranking = pd.read_parquet(reranking_path) if reranking_path.exists() else pd.DataFrame()
    concept_diversity = int(forgetting["deck_id"].nunique()) if "deck_id" in forgetting else 0
    report = {
        "forgetting_curve": {
            **_frame_report(forgetting),
            "ready": int(len(forgetting)) >= 50,
            "minimum_rows": 50,
            "concept_diversity": concept_diversity,
        },
        "reranking": {
            **_frame_report(reranking),
            "ready": int(len(reranking)) >= 100,
            "minimum_rows": 100,
            "action_distribution": (
                reranking["action"].value_counts(dropna=False).to_dict()
                if "action" in reranking
                else {}
            ),
        },
    }
    report["ready"] = bool(report["forgetting_curve"]["ready"] and report["reranking"]["ready"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=TRAIN_DATA_PATH.parent)
    args = parser.parse_args()
    print(json.dumps(validate(args.data_dir), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
