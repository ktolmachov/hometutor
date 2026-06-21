"""Build privacy-safe SSR ML datasets from local app storage."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import get_settings
from app.ssr_ai.eval_harness import HINT_KINDS, REQUIRED_FEATURE_KEYS, TEST_DATA_PATH, TRAIN_DATA_PATH

RERANKING_DATA_PATH = TRAIN_DATA_PATH.parent / "ssr_reranking_features.parquet"

_NUMERIC_RERANKING_FEATURES = [
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


def _read_sql(conn: sqlite3.Connection, sql: str) -> pd.DataFrame:
    try:
        return pd.read_sql_query(sql, conn)
    except (pd.errors.DatabaseError, sqlite3.Error):
        return pd.DataFrame()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                rows.append(data)
    return rows


def _collect_auxiliary_inputs(data_dir: Path) -> dict[str, int]:
    settings = get_settings()
    session_events = 0
    sessions_dir = data_dir / "sessions"
    if sessions_dir.exists():
        for path in sessions_dir.glob("*.jsonl"):
            session_events += len(_read_jsonl(path))
    metrics_events = len(_read_jsonl(Path(settings.metrics_store_path)))
    feedback_events = len(_read_jsonl(Path(settings.feedback_path)))
    return {
        "session_events": session_events,
        "metrics_events": metrics_events,
        "feedback_events": feedback_events,
    }


def build_forgetting_curve_dataset(conn: sqlite3.Connection) -> pd.DataFrame:
    reviews = _read_sql(
        conn,
        """
        SELECT
            id, card_id, deck_id, quality, easiness_before, easiness_after,
            interval_before, interval_after, repetitions, reviewed_at
        FROM flashcard_review_log
        ORDER BY datetime(reviewed_at) ASC, id ASC
        """,
    )
    if reviews.empty:
        return pd.DataFrame(
            columns=[
                "review_id",
                "card_id",
                "deck_id",
                "reviewed_at",
                "time_since_last_review_hours",
                "quality",
                "easiness_before",
                "interval_before",
                "repetitions",
                "card_age_days",
                "review_sequence_position",
                "recalled",
            ]
        )
    cards = _read_sql(conn, "SELECT id AS card_id, created_at FROM flashcards")
    df = reviews.rename(columns={"id": "review_id"}).copy()
    df["reviewed_at"] = pd.to_datetime(df["reviewed_at"], utc=True, errors="coerce")
    if not cards.empty:
        cards["created_at"] = pd.to_datetime(cards["created_at"], utc=True, errors="coerce")
        df = df.merge(cards, on="card_id", how="left")
    else:
        df["created_at"] = pd.NaT
    df["previous_reviewed_at"] = df.groupby("card_id")["reviewed_at"].shift(1)
    df["time_since_last_review_hours"] = (
        (df["reviewed_at"] - df["previous_reviewed_at"]).dt.total_seconds() / 3600.0
    )
    df["time_since_last_review_hours"] = df["time_since_last_review_hours"].fillna(0.0)
    df["card_age_days"] = ((df["reviewed_at"] - df["created_at"]).dt.total_seconds() / 86400.0).fillna(0.0)
    df["review_sequence_position"] = df.groupby("card_id").cumcount() + 1
    df["recalled"] = (pd.to_numeric(df["quality"], errors="coerce").fillna(0) >= 3).astype(int)
    cols = [
        "review_id",
        "card_id",
        "deck_id",
        "reviewed_at",
        "time_since_last_review_hours",
        "quality",
        "easiness_before",
        "interval_before",
        "repetitions",
        "card_age_days",
        "review_sequence_position",
        "recalled",
    ]
    return df[cols].sort_values("reviewed_at").reset_index(drop=True)


def chronological_split(df: pd.DataFrame, *, test_fraction: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df.copy(), df.copy()
    ordered = df.sort_values("reviewed_at").reset_index(drop=True)
    test_n = max(1, int(round(len(ordered) * test_fraction))) if len(ordered) > 1 else 0
    if test_n <= 0:
        return ordered.copy(), ordered.iloc[0:0].copy()
    split_at = max(1, len(ordered) - test_n)
    return ordered.iloc[:split_at].copy(), ordered.iloc[split_at:].copy()


def _latest_counts_before(conn: sqlite3.Connection, ts: str) -> tuple[int, int]:
    try:
        fc = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM flashcards
            WHERE next_review IS NULL OR datetime(next_review) <= datetime(?)
            """,
            (ts,),
        ).fetchone()
        sm2 = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM spaced_repetition
            WHERE next_review IS NULL OR datetime(next_review) <= datetime(?)
            """,
            (ts,),
        ).fetchone()
        return int(fc["n"] if fc else 0), int(sm2["n"] if sm2 else 0)
    except sqlite3.Error:
        return 0, 0


def _quiz_last_3_avg(conn: sqlite3.Connection, ts: str) -> float:
    try:
        rows = conn.execute(
            """
            SELECT score FROM quiz_results
            WHERE timestamp <= ?
            ORDER BY datetime(timestamp) DESC, id DESC
            LIMIT 3
            """,
            (ts,),
        ).fetchall()
    except sqlite3.Error:
        return 0.72
    vals = [float(row["score"]) for row in rows if row["score"] is not None]
    return float(sum(vals) / len(vals)) if vals else 0.72


def _action_for_impression(feedback: pd.DataFrame, impression: pd.Series) -> str:
    if feedback.empty:
        return "none"
    candidates = feedback
    sk = str(impression.get("session_key_prefix") or "").strip()
    if sk:
        same_session = candidates[candidates["session_key_prefix"].fillna("").astype(str) == sk]
        if not same_session.empty:
            candidates = same_session
    else:
        same_route = candidates[
            (candidates["hint_kind"] == impression.get("hint_kind"))
            & (candidates["primary_nav"] == impression.get("primary_nav"))
        ]
        if not same_route.empty:
            candidates = same_route
    created = impression.get("created_at")
    if pd.notna(created) and "created_at" in candidates:
        after = candidates[candidates["created_at"] >= created]
        if not after.empty:
            candidates = after
    row = candidates.sort_values("created_at").head(1)
    if row.empty:
        return "none"
    return str(row.iloc[0].get("action") or "none").strip().lower() or "none"


def build_reranking_features(conn: sqlite3.Connection) -> pd.DataFrame:
    impressions = _read_sql(
        conn,
        """
        SELECT id, hint_kind, primary_nav, session_key_prefix, created_at
        FROM ssr_route_impressions
        ORDER BY datetime(created_at) ASC, id ASC
        """,
    )
    if impressions.empty:
        return pd.DataFrame(columns=["impression_id", *_NUMERIC_RERANKING_FEATURES, "prior_rule_top_hint_kind", "action"])
    feedback = _read_sql(
        conn,
        """
        SELECT action, hint_kind, primary_nav, session_key_prefix, created_at
        FROM ssr_recommendation_feedback
        ORDER BY datetime(created_at) ASC, id ASC
        """,
    )
    for frame in (impressions, feedback):
        if not frame.empty and "created_at" in frame:
            frame["created_at"] = pd.to_datetime(frame["created_at"], utc=True, errors="coerce")
    rows: list[dict[str, Any]] = []
    for _, imp in impressions.iterrows():
        created = imp.get("created_at")
        ts_iso = created.isoformat() if pd.notna(created) else ""
        fc_due, sm2_due = _latest_counts_before(conn, ts_iso)
        hour = float(created.hour) if pd.notna(created) else 12.0
        dow = float(created.dayofweek) if pd.notna(created) else 0.0
        hint = str(imp.get("hint_kind") or "safe_default").strip()
        primary_nav = str(imp.get("primary_nav") or "").strip()
        rows.append(
            {
                "impression_id": int(imp["id"]),
                "hint_kind": hint,
                "primary_nav": primary_nav,
                "session_key_prefix": str(imp.get("session_key_prefix") or ""),
                "created_at": created,
                "time_since_last_review_hours": 48.0,
                "quiz_score_last_3_avg": _quiz_last_3_avg(conn, ts_iso),
                "concept_difficulty": 0.5,
                "session_duration_avg_minutes": 28.0,
                "time_of_day_hour": hour,
                "day_of_week": dow,
                "cards_due_count": float(fc_due),
                "sm2_due_count": float(sm2_due),
                "quiz_failed_recent": 1.0 if hint == "quiz_failed" else 0.0,
                "session_fatigue": 0.45,
                "mastery_gap_score": 0.74 if hint == "mastery_stale" else 0.28,
                "adaptive_plan_backlog_signals": 5.0 if hint == "adaptive_plan" else 0.0,
                "tutor_stub_active": 1.0 if hint == "tutor_resume" else 0.0,
                "prior_rule_top_hint_kind": hint if hint in HINT_KINDS else "safe_default",
                "action": _action_for_impression(feedback, imp),
            }
        )
    df = pd.DataFrame(rows)
    missing = REQUIRED_FEATURE_KEYS - set(df.columns)
    if missing:
        raise RuntimeError(f"reranking feature builder missing keys: {sorted(missing)}")
    return df


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def build_datasets(db_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        forgetting = build_forgetting_curve_dataset(conn)
        train, test = chronological_split(forgetting)
        reranking = build_reranking_features(conn)
    finally:
        conn.close()
    train_path = output_dir / TRAIN_DATA_PATH.name
    test_path = output_dir / TEST_DATA_PATH.name
    reranking_path = output_dir / RERANKING_DATA_PATH.name
    write_parquet(train, train_path)
    write_parquet(test, test_path)
    write_parquet(reranking, reranking_path)
    aux = _collect_auxiliary_inputs(db_path.parent)
    return {
        "train_rows": len(train),
        "test_rows": len(test),
        "reranking_rows": len(reranking),
        "train_path": str(train_path),
        "test_path": str(test_path),
        "reranking_path": str(reranking_path),
        **aux,
    }


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path(settings.user_state_db))
    parser.add_argument("--output", type=Path, default=TRAIN_DATA_PATH.parent)
    args = parser.parse_args()
    summary = build_datasets(args.db, args.output)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
