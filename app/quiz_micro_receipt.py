"""Pure micro-quiz progress receipt (baseline capture, diff lines, HTML)."""

from __future__ import annotations

import html as html_stdlib
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

MICRO_QUIZ_RECEIPT_BASELINE_TTL_SEC = 600


def _micro_quiz_status_ru(status: str | None) -> str:
    """US-5.1 status labels (mirror ``tutor_chat_actions.micro_quiz_status_ru``)."""
    s = str(status or "").strip().lower()
    return {"correct": "Верно", "incorrect": "Неверно", "partial": "Частично"}.get(s, s or "—")


def _read_fc_due_global() -> int:
    from app.user_state import count_due_flashcards

    try:
        return int(count_due_flashcards())
    except Exception as exc:  # noqa: BLE001
        logger.debug("micro quiz receipt fc_due read failed: %s", exc)
        return 0


def _read_sm2_due_global() -> int:
    from app.spaced_repetition import count_due_reviews

    try:
        return int(count_due_reviews())
    except Exception as exc:  # noqa: BLE001
        logger.debug("micro quiz receipt sm2_due read failed: %s", exc)
        return 0


def _read_weak_top() -> str | None:
    from app.quiz_adaptive import get_weak_concepts

    try:
        weak = list(get_weak_concepts(limit=1))
        return weak[0] if weak else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("micro quiz receipt weak_top read failed: %s", exc)
        return None


def _read_plan_teaser() -> str:
    try:
        from app.adaptive_plan_progress import adaptive_plan_progress_teaser_caption

        cap = adaptive_plan_progress_teaser_caption()
        return str(cap or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("micro quiz receipt plan_teaser read failed: %s", exc)
        return ""


def build_micro_quiz_metric_dict_live(*, topic: str = "") -> dict[str, Any]:
    """Build live metrics dict for baseline or after snapshot."""
    return {
        "fc_due": _read_fc_due_global(),
        "sm2_due": _read_sm2_due_global(),
        "weak_top": _read_weak_top(),
        "plan_teaser": _read_plan_teaser(),
        "topic": (topic or "").strip(),
        "ts": time.time(),
    }


def capture_micro_quiz_receipt_baseline(scope_key: str, *, topic: str = "") -> dict[str, Any]:
    """Capture baseline at question render for receipt diff."""
    snap = build_micro_quiz_metric_dict_live(topic=topic)
    snap["scope_key"] = (scope_key or "").strip()
    return snap


def build_micro_quiz_receipt_lines(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    feedback_status: str | None = None,
) -> tuple[list[str], bool]:
    del feedback_status  # reserved for sp2/html; lines are metric-only
    lines: list[str] = []
    measurable = False

    if not before and not after:
        return lines, measurable

    b_fc = int(before.get("fc_due") or 0)
    a_fc = int(after.get("fc_due") or 0)
    if b_fc != a_fc:
        measurable = True
        lines.append(f"Карточки к повторению: было {b_fc} → стало {a_fc}.")

    b_sm = int(before.get("sm2_due") or 0)
    a_sm = int(after.get("sm2_due") or 0)
    if b_sm != a_sm:
        measurable = True
        lines.append(f"Очередь SM-2 по графу: было {b_sm} → стало {a_sm}.")

    b_w = str(before.get("weak_top") or "").strip()
    a_w = str(after.get("weak_top") or "").strip()
    if b_w or a_w:
        if b_w != a_w:
            measurable = True
            lines.append(f'Верх слабых концептов: было «{b_w or "—"}» → «{a_w or "—"}».')

    b_plan = str(before.get("plan_teaser") or "").strip()
    a_plan = str(after.get("plan_teaser") or "").strip()
    if b_plan != a_plan and (b_plan or a_plan):
        measurable = True
        lines.append(f'Следующий шаг плана: было «{b_plan or "—"}» → «{a_plan or "—"}».')

    return lines, measurable


def build_micro_quiz_receipt_html(
    lines: list[str],
    *,
    measurable: bool,
    feedback_status: str | None = None,
) -> str:
    """Render receipt card HTML; CTA wiring is sp2-only."""
    status_cap = html_stdlib.escape(_micro_quiz_status_ru(feedback_status))
    status_block = ""
    if feedback_status:
        status_block = (
            f'<p style="margin:0 0 0.35rem 0;font-size:0.9rem;">'
            f"Статус ответа: <b>{status_cap}</b></p>"
        )

    if lines:
        items_li = "".join(
            f'<li style="margin:0.12rem 0;">{html_stdlib.escape(line)}</li>' for line in lines
        )
        body = f'<ul style="margin:0;padding-left:1.2rem;">{items_li}</ul>'
    else:
        body = ""

    if not measurable:
        body += (
            '<p style="margin:0.35rem 0 0 0;font-size:0.9rem;">'
            "Локальные метрики без изменений — подробности на вкладке Progress.</p>"
        )

    return (
        '<div class="micro-quiz-progress-receipt home-dash-card" '
        'data-testid="e2e-micro-quiz-progress-receipt">'
        '<div class="home-dash-head"><h4 style="margin:0;">📋 Локальный прогресс после ответа</h4></div>'
        f'<div class="home-dash-body">{status_block}{body}</div></div>'
    )


__all__ = [
    "MICRO_QUIZ_RECEIPT_BASELINE_TTL_SEC",
    "build_micro_quiz_metric_dict_live",
    "build_micro_quiz_receipt_html",
    "build_micro_quiz_receipt_lines",
    "capture_micro_quiz_receipt_baseline",
]
