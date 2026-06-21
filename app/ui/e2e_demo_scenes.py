"""Offline-only query-param surfaces for Smart Demo Playwright captures."""

from __future__ import annotations

import html as html_stdlib
from typing import Any

import streamlit as st

from app.config import get_settings
from app.ui.breadcrumb import HOME_VIEW


def e2e_qp_flag(name: str) -> bool:
    raw = st.query_params.get(name)
    if raw is None:
        return False
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def e2e_cockpit_enabled(settings: Any | None = None) -> bool:
    s = settings or get_settings()
    if bool(getattr(s, "rag_course_cockpit_v2", False)):
        return True
    return bool(getattr(s, "home_rag_e2e_offline", False)) and e2e_qp_flag("e2e_cockpit")


def render_e2e_reindex_badge_demo() -> None:
    from app.ui.learner_profile_panel import render_us_8_2_reindex_badge

    render_us_8_2_reindex_badge(
        state_migration={
            "history_rehydrated": True,
            "index_changed": True,
            "history_rehydrated_row_timestamp": "2026-06-20T09:15:00+00:00",
        },
        index_context={
            "generation_id": "demo-reindex-gen",
            "activated_at": "2026-06-20T09:15:00+00:00",
        },
    )


def render_e2e_graduation_celebration_demo() -> None:
    from app.ui.graduation_overlay import render_skippable_graduation_celebration

    render_skippable_graduation_celebration(
        concept_title="Градиентный спуск",
        mastery_pct=87.0,
        session_count=4,
        minutes_spent=32.5,
    )


def render_e2e_ssr_outcome_receipt_demo(*, variant: str = "changed") -> None:
    if variant == "none":
        body = (
            "По локальным очередям измеримого сдвига пока не видно — "
            "без фальшивого «прогресса»."
        )
        title = "ℹ️ Честный чек после шага"
    else:
        lines = [
            "К повторению: было 12 → стало 8",
            "SM-2 due по графу: −2",
            "Слабый концепт отработан в tutor/quiz",
        ]
        items = "".join(
            f'<li style="margin:0.12rem 0;">{html_stdlib.escape(line)}</li>' for line in lines
        )
        body = (
            '<p style="margin:0 0 0.35rem 0;">Локальные метрики изменились:</p>'
            f'<ul style="margin:0;padding-left:1.2rem;">{items}</ul>'
        )
        title = "✅ Чек после шага роутера"
    st.markdown(
        f'<div class="home-dash-card" data-testid="e2e-ssr-outcome-receipt" '
        'style="margin-bottom:0.6rem;">'
        f'<div class="home-dash-head home-dash-head-continue"><h4 style="margin:0;">{title}</h4></div>'
        f'<div class="home-dash-body">{body}</div></div>',
        unsafe_allow_html=True,
    )


def render_e2e_demo_scene_for_view(view: str) -> None:
    """Inject deterministic demo-only UI blocks when offline e2e flags are set."""
    settings = get_settings()
    if not settings.home_rag_e2e_offline:
        return

    if e2e_qp_flag("e2e_reindex_badge") and view in {"Прогресс обучения", "Темы", "Быстрый ответ"}:
        render_e2e_reindex_badge_demo()

    if e2e_qp_flag("e2e_graduation_celebration") and view in {
        "Прогресс обучения",
        "Курс",
        "Чат с тьютором",
    }:
        render_e2e_graduation_celebration_demo()

    if e2e_qp_flag("e2e_ssr_outcome_receipt") and view in {
        HOME_VIEW,
        "Прогресс обучения",
        "Flashcards",
    }:
        render_e2e_ssr_outcome_receipt_demo()


__all__ = [
    "e2e_cockpit_enabled",
    "e2e_qp_flag",
    "render_e2e_demo_scene_for_view",
    "render_e2e_graduation_celebration_demo",
    "render_e2e_reindex_badge_demo",
    "render_e2e_ssr_outcome_receipt_demo",
]
