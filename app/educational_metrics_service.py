"""Aggregated educational outcomes and mastery-validation signals (local SQLite via ``_with_db``)."""

from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.knowledge_graph import get_active_knowledge_graph
from app.quiz_adaptive import LEVEL_TO_MASTERY_PCT, SUCCESS_THRESHOLD
from app.user_state import _with_db
from app.user_state_lineage import get_current_learner_state_lineage


def _parse_ts(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _generation_filter(_conn: sqlite3.Connection, column: str = "generation_id") -> tuple[str, list[Any]]:
    """Filter by active index generation without DB-mutating lineage sync (metrics are read-only)."""
    lineage = get_current_learner_state_lineage()
    gid = str(lineage.get("generation_id") or "").strip()
    if not gid:
        return "", []
    return f" AND ({column} = ? OR {column} IS NULL)", [gid]


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    deny = math.sqrt(sum((y - my) ** 2 for y in ys))
    if denx <= 0 or deny <= 0:
        return None
    return round(num / (denx * deny), 4)


def _mean(vals: list[float]) -> float | None:
    if not vals:
        return None
    return round(sum(vals) / len(vals), 4)


def _std(vals: list[float]) -> float | None:
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    var = sum((x - m) ** 2 for x in vals) / (len(vals) - 1)
    return round(math.sqrt(var), 4)


def get_educational_metrics_report(*, limit_quiz_rows: int = 5000) -> dict[str, Any]:
    lim = max(1, min(int(limit_quiz_rows), 50_000))

    def _work(conn: sqlite3.Connection) -> dict[str, Any]:
        qf, qp = _generation_filter(conn, "generation_id")
        rows = conn.execute(
            f"""
            SELECT concept, level, score, timestamp
            FROM quiz_results
            WHERE 1=1 {qf}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (*qp, lim),
        ).fetchall()
        quiz = [dict(r) for r in rows]

        by_level: dict[str, list[float]] = defaultdict(list)
        scores_all: list[float] = []
        transfer_scores: list[float] = []
        for r in quiz:
            sc = float(r.get("score") or 0.0)
            scores_all.append(sc)
            lv = str(r.get("level") or "").strip().lower()
            if lv in {"transfer", "application"}:
                transfer_scores.append(sc)
                by_level.setdefault("transfer", []).append(sc)
            elif lv in {"recognition", "recall"}:
                by_level.setdefault(lv, []).append(sc)
            else:
                by_level.setdefault(lv or "unknown", []).append(sc)

        success_n = sum(1 for s in scores_all if s >= SUCCESS_THRESHOLD)
        attempts = len(scores_all)

        # Retention: same concept, two attempts at least RETENTION_GAP_DAYS apart
        by_concept_ts: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
        for r in quiz:
            ts = _parse_ts(str(r.get("timestamp") or ""))
            if ts is None:
                continue
            c = str(r.get("concept") or "").strip() or "general"
            by_concept_ts[c].append((ts, float(r.get("score") or 0.0)))
        for c in by_concept_ts:
            by_concept_ts[c].sort(key=lambda x: x[0])

        gap = timedelta(days=7)
        retention_pairs = 0
        retention_both_ok = 0
        for _c, series in by_concept_ts.items():
            for i in range(len(series)):
                t0, s0 = series[i]
                for j in range(i + 1, len(series)):
                    t1, s1 = series[j]
                    if t1 - t0 >= gap:
                        retention_pairs += 1
                        if s0 >= SUCCESS_THRESHOLD and s1 >= SUCCESS_THRESHOLD:
                            retention_both_ok += 1
                        break

        sf, sp = _generation_filter(conn, "generation_id")
        sr_rows = conn.execute(
            f"SELECT concept, easiness, interval_days, repetitions FROM spaced_repetition WHERE 1=1 {sf}",
            sp,
        ).fetchall()
        intervals = [int(r["interval_days"] or 1) for r in sr_rows]
        reps = [int(r["repetitions"] or 0) for r in sr_rows]
        stable_like = sum(
            1
            for iv, rp in zip(intervals, reps)
            if iv >= 3 and rp >= 2
        )

        micro_total = 0
        micro_ok = 0
        ev_rows = conn.execute(
            "SELECT feedback_json FROM micro_quiz_events ORDER BY id DESC LIMIT 500",
        ).fetchall()
        for er in ev_rows:
            raw = er["feedback_json"]
            try:
                fb = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                continue
            if not isinstance(fb, dict):
                continue
            micro_total += 1
            st = str(fb.get("status") or "").strip().lower()
            if st == "correct":
                micro_ok += 1

        level_summary = {
            lv: {
                "attempts": len(vals),
                "mean_score": _mean(vals),
                "success_rate": round(sum(1 for x in vals if x >= SUCCESS_THRESHOLD) / len(vals), 4) if vals else None,
            }
            for lv, vals in sorted(by_level.items())
        }

        return {
            "schema_version": 1,
            "quiz_correctness": {
                "attempts": attempts,
                "mean_score": _mean(scores_all),
                "success_rate": round(success_n / attempts, 4) if attempts else None,
                "success_threshold": SUCCESS_THRESHOLD,
                "by_level": level_summary,
            },
            "transfer_outcomes": {
                "attempts": len(transfer_scores),
                "mean_score": _mean(transfer_scores),
                "success_rate": (
                    round(sum(1 for x in transfer_scores if x >= SUCCESS_THRESHOLD) / len(transfer_scores), 4)
                    if transfer_scores
                    else None
                ),
            },
            "retention_after_7d": {
                "pairs_ge_7d": retention_pairs,
                "both_successful_rate": (
                    round(retention_both_ok / retention_pairs, 4) if retention_pairs else None
                ),
            },
            "srs_stability": {
                "concepts_tracked": len(intervals),
                "interval_days_mean": _mean([float(x) for x in intervals]) if intervals else None,
                "interval_days_std": _std([float(x) for x in intervals]) if intervals else None,
                "stable_concept_share": (
                    round(stable_like / len(intervals), 4) if intervals else None
                ),
            },
            "micro_quiz_events": {
                "parsed_attempts": micro_total,
                "correct_rate": round(micro_ok / micro_total, 4) if micro_total else None,
            },
        }

    return _with_db(_work)


def get_mastery_validation_report(*, limit_quiz_rows: int = 5000) -> dict[str, Any]:
    lim = max(1, min(int(limit_quiz_rows), 50_000))

    def _work(conn: sqlite3.Connection) -> dict[str, Any]:
        gf, gp = _generation_filter(conn, "generation_id")
        mastery_rows = conn.execute(
            f"""
            SELECT concept, current_level, success_streak, last_updated
            FROM quiz_mastery
            WHERE 1=1 {gf}
            """,
            gp,
        ).fetchall()

        spaced = conn.execute(
            f"SELECT concept, interval_days FROM spaced_repetition WHERE 1=1 {gf}",
            gp,
        ).fetchall()
        iv_by_concept = {str(r["concept"] or "").strip(): int(r["interval_days"] or 1) for r in spaced}

        xs: list[float] = []
        ys: list[float] = []
        transfer_concepts = 0
        for r in mastery_rows:
            c = str(r["concept"] or "").strip()
            if not c:
                continue
            lv = str(r["current_level"] or "recognition").strip().lower()
            pct = float(LEVEL_TO_MASTERY_PCT.get(lv, LEVEL_TO_MASTERY_PCT["recognition"]))
            if lv == "transfer":
                transfer_concepts += 1
            if c in iv_by_concept:
                xs.append(pct)
                ys.append(float(iv_by_concept[c]))

        kg = get_active_knowledge_graph()
        graduated: set[str] = set()
        try:
            graduated = kg.graduated_concept_ids()
        except Exception:  # noqa: BLE001 - graph backend optional; degraded empty set.
            graduated = set()

        qrows = conn.execute(
            f"""
            SELECT concept, level, score, timestamp
            FROM quiz_results
            WHERE 1=1 {gf}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (*gp, lim),
        ).fetchall()
        by_concept_transfer: dict[str, list[float]] = defaultdict(list)
        for r in qrows:
            c = str(r["concept"] or "").strip() or "general"
            lv = str(r["level"] or "").strip().lower()
            if lv in {"transfer", "application"}:
                by_concept_transfer[c].append(float(r["score"] or 0.0))

        checks: list[dict[str, Any]] = []
        weak_graduated = 0
        for cid in sorted(graduated):
            recent = by_concept_transfer.get(cid, [])[:8]
            mscore = _mean(recent) if recent else None
            flag = "ok"
            if not recent:
                flag = "no_transfer_quiz_evidence"
            elif mscore is not None and mscore < SUCCESS_THRESHOLD:
                flag = "weak_recent_transfer"
                weak_graduated += 1
            checks.append(
                {
                    "concept": cid,
                    "graduated": True,
                    "recent_transfer_attempts": len(recent),
                    "recent_transfer_mean_score": mscore,
                    "flag": flag,
                }
            )
            if len(checks) >= 24:
                break

        return {
            "schema_version": 1,
            "mastery_correlation": {
                "pearson_mastery_pct_vs_interval_days": _pearson(xs, ys),
                "paired_concepts": len(xs),
            },
            "transfer_level_state": {
                "concepts_at_transfer_in_quiz_mastery": transfer_concepts,
                "quiz_mastery_rows": len(mastery_rows),
            },
            "false_positive_graduation": {
                "graduated_concepts_checked": len(checks),
                "weak_recent_transfer_count": weak_graduated,
                "checks": checks,
            },
        }

    return _with_db(_work)
