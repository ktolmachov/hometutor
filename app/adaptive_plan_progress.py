"""Backend-safe Adaptive Daily Plan progress captions."""
from __future__ import annotations

from typing import Any

from app.adaptive_plan import AdaptiveDailyPlan
from app.adaptive_plan_step_text import (
    BLOCK_TYPE_LABEL_RU as _BLOCK_LABEL,
    is_placeholder_plan_concept as _is_placeholder_concept,
)
from app.learning_plan_service import get_saved_adaptive_daily_plan


def _load_adaptive_daily_plan(
    user_id: str | None = None,
    *,
    plan_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if plan_override is not None:
        return plan_override
    saved = get_saved_adaptive_daily_plan()
    if saved:
        return saved
    uid = (user_id or "local").strip() or "local"
    return AdaptiveDailyPlan(user_id=uid).build_adaptive_daily_plan()


def get_primary_plan_block(blocks: list[Any]) -> tuple[int, dict[str, Any]] | None:
    """Return the first actionable plan block; ``auto_loop`` remains fallback-only."""
    rendered = [(idx, block) for idx, block in enumerate(blocks or []) if isinstance(block, dict)]
    for item in rendered:
        bt = str(item[1].get("type") or "").strip()
        if bt != "auto_loop":
            return item
    return rendered[0] if rendered else None


def adaptive_plan_progress_teaser_caption(
    user_id: str | None = None,
    *,
    plan_override: dict[str, Any] | None = None,
) -> str | None:
    """One-line progress teaser for receipts and non-UI surfaces."""
    plan = _load_adaptive_daily_plan(user_id, plan_override=plan_override)
    blocks = plan.get("blocks") or []
    primary = get_primary_plan_block(blocks)
    if not primary:
        return None
    _, block = primary
    bt = str(block.get("type") or "").strip()
    lab = _BLOCK_LABEL.get(bt, (bt or "шаг").replace("_", " "))
    c_raw = str(block.get("concept") or "").strip()
    if _is_placeholder_plan_concept(c_raw):
        return f"Adaptive plan: следующий акцент — {lab}"
    return f"Adaptive plan: следующий акцент — {lab} — «{c_raw[:72]}»"
