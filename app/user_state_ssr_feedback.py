"""SSR misroute feedback — local SQLite persistence (US-20.10 / L5 data foundation)."""

from __future__ import annotations

import sqlite3
from typing import Any, Literal, get_args

from app.smart_study_recommendation import SmartStudyPrimaryNav, SmartStudyRouterHintKind
from app.user_state_core import _utc_now_iso, _with_db

_HINT_SET = frozenset(get_args(SmartStudyRouterHintKind))
_NAV_SET = frozenset(get_args(SmartStudyPrimaryNav))

SsrRecommendationFeedbackAction = Literal["accept", "reject", "defer"]

_VALID_ACTIONS = frozenset({"accept", "reject", "defer"})


def record_ssr_recommendation_feedback(
    *,
    action: SsrRecommendationFeedbackAction,
    hint_kind: str,
    primary_nav: str,
    weak_concept_sha256: str | None = None,
    why_now_len: int = 0,
    explanation_outcome: str | None = None,
    latency_ms: float | None = None,
    session_key_prefix: str | None = None,
) -> int:
    """Insert one privacy-safe feedback row; returns new row id."""
    act = str(action or "").strip().lower()
    if act not in _VALID_ACTIONS:
        raise ValueError(f"invalid feedback action: {action!r}")
    hk = str(hint_kind or "").strip()
    pn = str(primary_nav or "").strip()
    if not hk or not pn:
        raise ValueError("hint_kind and primary_nav required")
    wcd = str(weak_concept_sha256 or "").strip() or None
    sk = str(session_key_prefix or "").strip()[:24] or None
    eo = str(explanation_outcome or "").strip() or None
    wlen = max(0, int(why_now_len or 0))
    lat: float | None
    try:
        lat = float(latency_ms) if latency_ms is not None else None
    except (TypeError, ValueError):
        lat = None
    ts = _utc_now_iso()

    def _work(conn: sqlite3.Connection) -> int:
        cur = conn.execute(
            """
            INSERT INTO ssr_recommendation_feedback (
                action, hint_kind, primary_nav, weak_concept_sha256,
                why_now_len, explanation_outcome, latency_ms, session_key_prefix, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (act, hk, pn, wcd, wlen, eo, lat, sk, ts),
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    return _with_db(_work, write=True)


def list_ssr_recommendation_feedback_recent(*, limit: int = 50) -> list[dict[str, Any]]:
    """Test helper / introspection — newest first."""
    lim = max(1, min(500, int(limit)))

    def _work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT id, action, hint_kind, primary_nav, weak_concept_sha256,
                   why_now_len, explanation_outcome, latency_ms, session_key_prefix, created_at
            FROM ssr_recommendation_feedback
            ORDER BY id DESC
            LIMIT ?
            """,
            (lim,),
        ).fetchall()
        return [dict(r) for r in rows]

    return _with_db(_work)


def _sanitize_router_row(row: dict[str, Any]) -> dict[str, Any] | None:
    hk = str(row.get("hint_kind") or "").strip()
    pn = str(row.get("primary_nav") or "").strip()
    if hk not in _HINT_SET or pn not in _NAV_SET:
        return None
    act = str(row.get("action") or "").strip().lower()
    if act not in _VALID_ACTIONS:
        return None
    wcd = str(row.get("weak_concept_sha256") or "").strip() or None
    return {
        "id": row.get("id"),
        "action": act,
        "hint_kind": hk,
        "primary_nav": pn,
        "weak_concept_sha256": wcd,
        "why_now_len": row.get("why_now_len"),
        "explanation_outcome": str(row.get("explanation_outcome") or "").strip() or None,
        "latency_ms": row.get("latency_ms"),
        "session_key_prefix": row.get("session_key_prefix"),
        "created_at": str(row.get("created_at") or ""),
    }


def aggregate_ssr_misroute_feedback_buckets(*, since_iso: str, limit: int = 500) -> list[dict[str, Any]]:
    """Read-only bucket aggregates for offline misroute policy (privacy-safe hashes only)."""
    since = str(since_iso or "").strip()
    if not since:
        raise ValueError("since_iso required")
    lim = max(1, min(500, int(limit)))

    def _work(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT id, action, hint_kind, primary_nav, weak_concept_sha256,
                   why_now_len, explanation_outcome, latency_ms, session_key_prefix, created_at
            FROM ssr_recommendation_feedback
            WHERE created_at >= ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (since, lim),
        ).fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for raw in rows:
            clean = _sanitize_router_row(dict(raw))
            if clean is None:
                continue
            bkey = f"{clean['hint_kind']}|{clean['primary_nav']}|{clean['weak_concept_sha256'] or ''}"
            bucket = grouped.get(bkey)
            if bucket is None:
                bucket = {
                    "bucket_key": bkey,
                    "hint_kind": clean["hint_kind"],
                    "primary_nav": clean["primary_nav"],
                    "weak_concept_sha256": clean["weak_concept_sha256"],
                    "rows": [],
                }
                grouped[bkey] = bucket
            bucket["rows"].append(clean)
        return list(grouped.values())

    return _with_db(_work)


__all__ = [
    "SsrRecommendationFeedbackAction",
    "aggregate_ssr_misroute_feedback_buckets",
    "list_ssr_recommendation_feedback_recent",
    "record_ssr_recommendation_feedback",
]
