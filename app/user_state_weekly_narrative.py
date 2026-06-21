"""Read helpers for weekly study narrative (7d UTC aggregation, due baseline)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app.knowledge_service import get_active_knowledge_graph
from app.learner_state_scope import count_due_reviews_for_kg
from app.user_state_core import _utc_now_iso, _with_db, get_kv, set_kv
from app.user_state_flashcards import get_flashcard_progress_stats
from app.user_state_ssr_feedback import _sanitize_router_row

_DUE_BASELINE_KV_KEY = "ssr_narrative_due_baseline_v1"
_BASELINE_MAX_AGE = timedelta(days=7)


def _utc_now(now_utc: datetime | None = None) -> datetime:
    if now_utc is not None:
        if now_utc.tzinfo is None:
            return now_utc.replace(tzinfo=timezone.utc)
        return now_utc.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _since_iso_7d(now_utc: datetime | None = None) -> str:
    now = _utc_now(now_utc)
    since = now - timedelta(days=7)
    return since.replace(microsecond=0).isoformat()


def _day_key(iso_ts: str) -> str | None:
    raw = str(iso_ts or "").strip()
    if not raw:
        return None
    if "T" in raw:
        return raw.split("T", 1)[0]
    return raw[:10] if len(raw) >= 10 else None


def count_learning_events_7d(*, now_utc: datetime | None = None) -> int:
    """Canonical learning events in rolling 7×24h UTC, deduped per architect table."""
    since = _since_iso_7d(now_utc)
    days: set[str] = set()

    def _work(conn: sqlite3.Connection) -> int:
        for row in conn.execute(
            "SELECT timestamp FROM quiz_results WHERE timestamp >= ? LIMIT 500",
            (since,),
        ).fetchall():
            dk = _day_key(str(row["timestamp"] or ""))
            if dk:
                days.add(f"quiz:{dk}")

        for row in conn.execute(
            "SELECT created_at FROM micro_quiz_events WHERE created_at >= ? LIMIT 500",
            (since,),
        ).fetchall():
            dk = _day_key(str(row["created_at"] or ""))
            if dk:
                days.add(f"micro:{dk}")

        for row in conn.execute(
            """
            SELECT DISTINCT date(last_review) AS review_day
            FROM flashcards
            WHERE last_review IS NOT NULL AND last_review >= ?
            LIMIT 500
            """,
            (since,),
        ).fetchall():
            dk = str(row["review_day"] or "").strip()
            if dk:
                days.add(f"fc:{dk}")

        for row in conn.execute(
            """
            SELECT created_at FROM ssr_recommendation_feedback
            WHERE created_at >= ?
            LIMIT 500
            """,
            (since,),
        ).fetchall():
            dk = _day_key(str(row["created_at"] or ""))
            if dk:
                days.add(f"ssr_fb:{dk}")

        try:
            impr_rows = conn.execute(
                """
                SELECT created_at FROM ssr_route_impressions
                WHERE created_at >= ?
                LIMIT 500
                """,
                (since,),
            ).fetchall()
        except sqlite3.OperationalError:
            impr_rows = []
        for row in impr_rows:
            dk = _day_key(str(row["created_at"] or ""))
            if dk:
                days.add(f"ssr_impr:{dk}")

        return len(days)

    try:
        return _with_db(_work)
    except sqlite3.OperationalError:
        return 0


def _collect_route_pairs(conn: sqlite3.Connection, since: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    fb_rows = conn.execute(
        """
        SELECT hint_kind, primary_nav, action, weak_concept_sha256,
               why_now_len, explanation_outcome, latency_ms, session_key_prefix, created_at
        FROM ssr_recommendation_feedback
        WHERE created_at >= ?
        LIMIT 500
        """,
        (since,),
    ).fetchall()
    for raw in fb_rows:
        clean = _sanitize_router_row(dict(raw))
        if clean is None:
            continue
        pairs.append((clean["hint_kind"], clean["primary_nav"]))

    try:
        impr_rows = conn.execute(
            """
            SELECT hint_kind, primary_nav, session_key_prefix, created_at
            FROM ssr_route_impressions
            WHERE created_at >= ?
            LIMIT 500
            """,
            (since,),
        ).fetchall()
    except sqlite3.OperationalError:
        impr_rows = []
    for raw in impr_rows:
        hk = str(raw["hint_kind"] or "").strip()
        pn = str(raw["primary_nav"] or "").strip()
        if hk and pn:
            pairs.append((hk, pn))
    return pairs


def aggregate_dominant_ssr_routes_7d(
    *,
    now_utc: datetime | None = None,
) -> tuple[str, str] | None:
    """Return dominant (hint_kind, primary_nav) or None when sparse / no data."""
    since = _since_iso_7d(now_utc)

    def _work(conn: sqlite3.Connection) -> tuple[str, str] | None:
        pairs = _collect_route_pairs(conn, since)
        if not pairs:
            return None
        counts: dict[tuple[str, str], int] = {}
        for hk, pn in pairs:
            key = (hk, pn)
            counts[key] = counts.get(key, 0) + 1
        ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0][0]))
        top_key, top_count = ranked[0]
        second_count = ranked[1][1] if len(ranked) > 1 else 0
        if top_count >= 2 and top_count > second_count:
            return top_key
        return None

    try:
        return _with_db(_work)
    except sqlite3.OperationalError:
        return None


def get_current_due_counts() -> tuple[int, int]:
    """fc_due + sm2_due using same semantics as SSR context (read-only)."""
    fc_due = 0
    try:
        stats = get_flashcard_progress_stats()
        fc_due = int(stats.get("due") or 0)
    except Exception:  # noqa: BLE001 — graceful empty when flashcard tables missing
        fc_due = 0
    sm2_due = 0
    try:
        kg = get_active_knowledge_graph()
        sm2_due = count_due_reviews_for_kg(kg)
    except Exception:  # noqa: BLE001 — KG unavailable in minimal test env
        sm2_due = 0
    return fc_due, sm2_due


def get_or_refresh_due_baseline_snapshot(
    *,
    now_utc: datetime | None = None,
) -> dict[str, Any] | None:
    """Return stored due baseline JSON or None if missing / unparsable."""
    raw = get_kv(_DUE_BASELINE_KV_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    captured = str(data.get("captured_at") or "").strip()
    if not captured:
        return None
    try:
        cap_dt = datetime.fromisoformat(captured.replace("Z", "+00:00"))
        if cap_dt.tzinfo is None:
            cap_dt = cap_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    now = _utc_now(now_utc)
    if now - cap_dt.astimezone(timezone.utc) > _BASELINE_MAX_AGE:
        return None
    try:
        return {
            "fc_due": int(data.get("fc_due") or 0),
            "sm2_due": int(data.get("sm2_due") or 0),
            "captured_at": captured,
        }
    except (TypeError, ValueError):
        return None


def capture_due_baseline_if_stale(*, now_utc: datetime | None = None) -> None:
    """Persist due baseline when missing or older than 7d."""
    if get_or_refresh_due_baseline_snapshot(now_utc=now_utc) is not None:
        return
    fc_due, sm2_due = get_current_due_counts()
    payload = {
        "fc_due": fc_due,
        "sm2_due": sm2_due,
        "captured_at": _utc_now(now_utc).replace(microsecond=0).isoformat(),
    }
    set_kv(_DUE_BASELINE_KV_KEY, json.dumps(payload, ensure_ascii=False))


def compute_due_trend(
    *,
    now_utc: datetime | None = None,
) -> str:
    """Return due trend bucket: up | down | flat | neutral."""
    capture_due_baseline_if_stale(now_utc=now_utc)
    baseline = get_or_refresh_due_baseline_snapshot(now_utc=now_utc)
    if baseline is None:
        return "neutral"
    fc_due, sm2_due = get_current_due_counts()
    current_sum = fc_due + sm2_due
    base_sum = int(baseline["fc_due"]) + int(baseline["sm2_due"])
    if current_sum > base_sum + 1:
        return "up"
    if current_sum < base_sum - 1:
        return "down"
    return "flat"


def record_ssr_route_impression(
    *,
    hint_kind: str,
    primary_nav: str,
    session_key_prefix: str | None = None,
) -> int:
    """Append-only SSR route impression (sp2 writer; schema owned by sp1)."""
    hk = str(hint_kind or "").strip()
    pn = str(primary_nav or "").strip()
    if not hk or not pn:
        raise ValueError("hint_kind and primary_nav required")
    sk = str(session_key_prefix or "").strip()[:24] or None
    ts = _utc_now_iso()

    def _work(conn: sqlite3.Connection) -> int:
        cur = conn.execute(
            """
            INSERT INTO ssr_route_impressions (
                hint_kind, primary_nav, session_key_prefix, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (hk, pn, sk, ts),
        )
        conn.commit()
        return int(cur.lastrowid or 0)

    return _with_db(_work, write=True)


__all__ = [
    "aggregate_dominant_ssr_routes_7d",
    "capture_due_baseline_if_stale",
    "compute_due_trend",
    "count_learning_events_7d",
    "get_current_due_counts",
    "get_or_refresh_due_baseline_snapshot",
    "record_ssr_route_impression",
]
