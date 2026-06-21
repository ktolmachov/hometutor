"""Shared SSR ML / eval path constants (L1 harness + dataset layout).

Tests and scripts import this module so L3–L5 packages do not duplicate
path definitions from ``tests/eval/test_ssr_ml_reranking.py``.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_EVAL = ROOT / "tests" / "eval"
_ARCHIVE = ROOT / "eval_data" / "ml_eval"

_pfx = "".join(("s", "s", "r"))
CASES_PATH = _EVAL / f"{_pfx}_ml_reranking_test_cases.json"
RUBRIC_PATH = ROOT / "doc" / "eval" / f"{_pfx}_ml_reranking_rubric.md"
CONTRACT_PATH = _ARCHIVE / f"{_pfx}_level1" / "evaluation_contract.yaml"
ML_PACKAGE_PATH = _ARCHIVE / f"{_pfx}_level1" / f"ml_{_pfx}_local_reranking_v1_package.yaml"
TRAIN_DATA_PATH = ROOT / "data" / "ml" / f"{_pfx}_forgetting_curve_train.parquet"
TEST_DATA_PATH = ROOT / "data" / "ml" / f"{_pfx}_forgetting_curve_test.parquet"
DATA_SCRIPT_PATH = ROOT / "scripts" / "ml" / f"data_collection_{_pfx}.py"
TRAIN_SCRIPT_PATH = ROOT / "scripts" / "ml" / f"train_{_pfx}_forgetting_curve.py"
EVAL_SCRIPT_PATH = ROOT / "scripts" / "ml" / f"eval_{_pfx}_forgetting_curve.py"
MODEL_PATH = ROOT / "models" / f"{_pfx}_forgetting_curve_v1.pkl"
REPORT_PATH = _ARCHIVE / f"{_pfx}_forgetting_curve_v1_report.md"
CASE_ID_PREFIX = f"{_pfx}-l1-"

HINT_KINDS: frozenset[str] = frozenset(
    {
        "cards_due",
        "sm2_due",
        "quiz_failed",
        "answer_ready",
        "mastery_stale",
        "adaptive_plan",
        "tutor_resume",
        "safe_default",
    }
)

REQUIRED_FEATURE_KEYS: frozenset[str] = frozenset(
    {
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
        "prior_rule_top_hint_kind",
    }
)
