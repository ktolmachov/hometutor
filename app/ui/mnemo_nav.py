"""Мнемополис navigation helpers (W4a/W4b/W4d).

Deep links use ``PENDING_CURRENT_VIEW_KEY`` only — never write ``current_view``
after the main selectbox is instantiated (StreamlitAPIException).
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

# Session UI-state keys (not domain / user_state DB).
KG_OPEN_3D_HALL_KEY = "kg_open_3d_hall"
KG_RETURN_FROM_KEY = "kg_return_from"
KG_SURFACE_TAB_KEY = "kg_surface_tab"
KG_SURFACE_TAB_REVISION_KEY = "kg_surface_tab_revision"
KG_GRAPH_TAB_LABEL = "🕸 Граф знаний"
KG_MNEMO_TAB_LABEL = "🌆 Мнемополис"


def knowledge_surface_tab_key(*, state: Any | None = None) -> str:
    """Return the stable widget key for the current Knowledge Graph visit."""
    target = st.session_state if state is None else state
    try:
        revision = max(0, int(target.get(KG_SURFACE_TAB_REVISION_KEY, 0) or 0))
    except (TypeError, ValueError):
        revision = 0
    return f"{KG_SURFACE_TAB_KEY}:{revision}"


def open_mnemo_polis(
    *,
    state: Any | None = None,
    return_from: str | None = None,
) -> None:
    """Navigate to Knowledge Graph / 3D hall (ceremonial hub, not home).

    Parameters
    ----------
    return_from:
        Optional channel tag for honest arrival copy (``quiz``, ``flashcards``, …).
    """
    target = st.session_state if state is None else state
    target[PENDING_CURRENT_VIEW_KEY] = "Knowledge Graph"
    target[KG_OPEN_3D_HALL_KEY] = True
    try:
        revision = int(target.get(KG_SURFACE_TAB_REVISION_KEY, 0) or 0) + 1
    except (TypeError, ValueError):
        revision = 1
    target[KG_SURFACE_TAB_REVISION_KEY] = revision
    target[knowledge_surface_tab_key(state=target)] = KG_MNEMO_TAB_LABEL
    if return_from:
        target[KG_RETURN_FROM_KEY] = str(return_from).strip()
    if "home_breadcrumb_origin" not in target:
        from app.ui.constants import HOME_VIEW

        target["home_breadcrumb_origin"] = HOME_VIEW


def arrival_banner_message() -> str | None:
    """Consume deep-link flags and return one-shot success text, or None."""
    opened = bool(st.session_state.pop(KG_OPEN_3D_HALL_KEY, False))
    if not opened:
        st.session_state.pop(KG_RETURN_FROM_KEY, None)
        return None
    channel = str(st.session_state.pop(KG_RETURN_FROM_KEY, "") or "").strip()
    if channel == "quiz":
        return (
            "🌆 Мир обновился по quiz-каналу: ✓ на остановках и небо/фонари "
            "(mastery_history). Mission Control остаётся главным экраном."
        )
    if channel == "flashcards":
        return (
            "🌆 Мир обновился по SR-каналу: туман/retention (decay_vector). "
            "Mission Control остаётся главным экраном."
        )
    if channel == "collect":
        return (
            "🌆 Мир обновился: ◆ в кузнице (workbench / корзина конспекта). "
            "Mission Control остаётся главным экраном."
        )
    return (
        "🌆 Мнемополис · Memory Run (3D-зал). "
        "Mission Control остаётся главным экраном."
    )


def _default_help(return_from: str) -> str:
    if return_from == "quiz":
        return (
            "Открыть 3D-зал: честный quiz-след (✓ / рассвет). "
            "Не заменяет Mission Control."
        )
    if return_from == "flashcards":
        return (
            "Открыть 3D-зал: честный SR-след (туман/retention). "
            "Не заменяет Mission Control."
        )
    if return_from == "collect":
        return (
            "Открыть 3D-зал: ◆ на остановках (workbench). "
            "Не заменяет Mission Control."
        )
    return "Открыть 3D-зал (Мнемополис)."


def render_return_to_mnemo_cta(
    *,
    key: str,
    label: str = "🌆 Вернуться в Мнемополис",
    help_text: str | None = None,
    return_from: str = "quiz",
    caption: str | None = None,
) -> bool:
    """Render return CTA. Returns True if clicked (after open + will need rerun)."""
    if caption:
        st.caption(caption)
    help_default = _default_help(return_from)
    if st.button(
        label,
        key=key,
        width="stretch",
        help=help_text or help_default,
    ):
        open_mnemo_polis(return_from=return_from)
        return True
    return False
