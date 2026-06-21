"""Adaptive Daily Plan (19.5): обёртки для Streamlit; разметка — ``adaptive_plan_card``."""

from __future__ import annotations

from typing import Any

import streamlit as st

_BLOCK_LABEL = {
    "review": "Повторение",
    "gap": "Пробел",
    "new": "Новая тема",
    "motivation": "Мотивация",
    "auto_loop": "Auto-loop",
}


def render_adaptive_plan_block_cards(blocks: list[Any]) -> None:
    """Карточки по блокам плана (без JSON)."""
    if not blocks:
        st.caption("Нет блоков в плане.")
        return
    for i, raw in enumerate(blocks):
        if not isinstance(raw, dict):
            continue
        bt = str(raw.get("type") or "").strip()
        title = _BLOCK_LABEL.get(bt, bt or "шаг")
        line = str(raw.get("description") or raw.get("concept") or "").strip()
        dur = raw.get("duration_min")
        extra = f" · ~{dur} мин" if dur is not None else ""
        agent = raw.get("agent") or raw.get("recommended_agent")
        ag = f" · агент: `{agent}`" if agent else ""
        st.markdown(f"**{i + 1}. {title}**{extra}{ag}")
        if line:
            st.caption(line)


def render_adaptive_daily_plan_section(
    *,
    key_prefix: str = "adp",
    plan_override: dict[str, Any] | None = None,
) -> None:
    """
    Заголовок, кнопка пересчёта, карточки блоков, свёрнутый JSON.

    ``plan_override`` — если передан (например из ``generate_personalized_plan``), показываем его;
    иначе кэш KV за сегодня или пересчёт (см. ``adaptive_plan_card._effective_plan``).
    """
    from app.ui.adaptive_plan_card import render_adaptive_daily_plan

    uid = str(st.session_state.get("user_id") or "local").strip() or "local"
    render_adaptive_daily_plan(
        uid,
        show_buttons=True,
        compact=False,
        key_prefix=key_prefix,
        plan_override=plan_override,
        show_json_expander=True,
    )


__all__ = [
    "render_adaptive_daily_plan_section",
    "render_adaptive_plan_block_cards",
]
