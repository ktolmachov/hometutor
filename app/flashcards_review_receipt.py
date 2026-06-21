"""Pure flashcard review progress receipt (baseline capture, diff lines, HTML)."""

from __future__ import annotations

import html as html_stdlib
import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

FC_REVIEW_RECEIPT_BASELINE_TTL_SEC = 600


def _format_next_review_caption(iso: str | None) -> str:
    """Local ISO formatter (mirror ``flashcards_ui._format_next_review_caption``)."""
    if not iso:
        return ""
    try:
        raw = str(iso).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return str(iso).strip()


def _read_fc_due_global() -> int:
    from app.user_state import count_due_flashcards

    try:
        return int(count_due_flashcards())
    except Exception as exc:  # noqa: BLE001
        logger.debug("fc receipt fc_due read failed: %s", exc)
        return 0


def _read_gamification_snapshot() -> dict[str, Any]:
    from app.gamification_service import get_snapshot

    try:
        snap = get_snapshot()
        return snap if isinstance(snap, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("fc receipt gamification read failed: %s", exc)
        return {}


def _read_weekly_goals_state() -> dict[str, Any]:
    from app.user_state import get_weekly_goals_state

    try:
        state = get_weekly_goals_state()
        return state if isinstance(state, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("fc receipt weekly goals read failed: %s", exc)
        return {}


def build_fc_review_metric_dict_live(*, scope_signature: str = "") -> dict[str, Any]:
    """Build live metrics dict for baseline or after snapshot."""
    weekly = _read_weekly_goals_state()
    done = weekly.get("done") if isinstance(weekly.get("done"), dict) else {}
    targets = weekly.get("targets") if isinstance(weekly.get("targets"), dict) else {}
    gam = _read_gamification_snapshot()
    try:
        weekly_target = max(1, int(targets.get("reviews") or 0))
    except (TypeError, ValueError):
        weekly_target = 1
    return {
        "fc_due": _read_fc_due_global(),
        "daily_streak": int(gam.get("daily_streak") or 0),
        "weekly_done_reviews": int(done.get("reviews") or 0),
        "weekly_target_reviews": weekly_target,
        "week_id": str(weekly.get("week_id") or ""),
        "scope_signature": (scope_signature or "").strip(),
        "ts": time.time(),
    }


def capture_fc_review_receipt_baseline(scope_signature: str) -> dict[str, Any]:
    """Capture baseline at queue load for receipt diff."""
    return build_fc_review_metric_dict_live(scope_signature=scope_signature)


def build_fc_review_receipt_lines(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    next_review_min: str | None = None,
) -> tuple[list[str], bool]:
    lines: list[str] = []
    measurable = False

    if not before and not after:
        return lines, measurable

    b_fc = int(before.get("fc_due") or 0)
    a_fc = int(after.get("fc_due") or 0)
    if b_fc != a_fc:
        measurable = True
        lines.append(f"Карточки к повторению: было {b_fc} → стало {a_fc}.")
    elif before or after:
        lines.append("Очередь due без изменений.")

    b_streak = int(before.get("daily_streak") or 0)
    a_streak = int(after.get("daily_streak") or 0)
    if b_streak != a_streak:
        measurable = True
        lines.append(f"Стрик: {b_streak} → {a_streak} дн.")

    b_week_id = str(before.get("week_id") or "")
    a_week_id = str(after.get("week_id") or "")
    b_reviews = int(before.get("weekly_done_reviews") or 0)
    a_reviews = int(after.get("weekly_done_reviews") or 0)
    if b_week_id and a_week_id and b_week_id == a_week_id and a_reviews > b_reviews:
        measurable = True
        try:
            target = max(1, int(after.get("weekly_target_reviews") or before.get("weekly_target_reviews") or 1))
        except (TypeError, ValueError):
            target = 1
        lines.append(f"Повторения за неделю: {a_reviews}/{target}.")

    if next_review_min:
        cap = _format_next_review_caption(next_review_min)
        if cap:
            lines.append(f"📅 Ближайшее повторение: {cap}")

    return lines, measurable


def build_fc_review_receipt_html(
    lines: list[str],
    *,
    measurable: bool,
    next_review_min: str | None = None,
) -> str:
    """Render receipt card HTML; CTA wiring is sp2-only."""
    nr_block = ""
    if next_review_min:
        cap = html_stdlib.escape(_format_next_review_caption(next_review_min))
        if cap:
            nr_block = (
                f'<p style="margin:0.35rem 0 0 0;">📅 Ближайшее повторение: <b>{cap}</b></p>'
            )

    content_lines = [ln for ln in lines if not ln.startswith("📅 Ближайшее повторение:")]

    if content_lines:
        items_li = "".join(
            f'<li style="margin:0.12rem 0;">{html_stdlib.escape(line)}</li>' for line in content_lines
        )
        body = f'<ul style="margin:0;padding-left:1.2rem;">{items_li}</ul>'
    else:
        body = ""

    if nr_block and not any(ln.startswith("📅") for ln in lines):
        body = body + nr_block
    elif nr_block and measurable:
        body = body + nr_block

    if not measurable:
        body += (
            '<p style="margin:0.35rem 0 0 0;font-size:0.9rem;">'
            "Стрик и цели недели — на вкладке Progress.</p>"
        )

    return (
        '<div class="fc-review-progress-receipt home-dash-card" '
        'data-testid="e2e-fc-review-progress-receipt">'
        '<div class="home-dash-head"><h4 style="margin:0;">📊 Прогресс после повторения</h4></div>'
        f'<div class="home-dash-body">{body}</div></div>'
    )


__all__ = [
    "FC_REVIEW_RECEIPT_BASELINE_TTL_SEC",
    "build_fc_review_metric_dict_live",
    "build_fc_review_receipt_html",
    "build_fc_review_receipt_lines",
    "capture_fc_review_receipt_baseline",
]
