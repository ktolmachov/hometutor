"""SSR AI local dataset / artifact path helpers (delegates to eval_harness)."""

from __future__ import annotations

from pathlib import Path

from app.ssr_ai.eval_harness import (
    EVAL_SCRIPT_PATH,
    ML_PACKAGE_PATH,
    MODEL_PATH,
    ROOT,
    TEST_DATA_PATH,
    TRAIN_DATA_PATH,
    TRAIN_SCRIPT_PATH,
)


def ssr_ml_forgetting_curve_train_path() -> Path:
    return TRAIN_DATA_PATH


def ssr_ml_forgetting_curve_test_path() -> Path:
    return TEST_DATA_PATH


def ssr_ml_forgetting_curve_model_path() -> Path:
    return MODEL_PATH


def ssr_ml_train_script_path() -> Path:
    return TRAIN_SCRIPT_PATH


def ssr_ml_eval_script_path() -> Path:
    return EVAL_SCRIPT_PATH


def ssr_ml_l1_package_yaml_path() -> Path:
    return ML_PACKAGE_PATH


def repo_root() -> Path:
    return ROOT
