"""Control panel for UI visibility levels and feature overrides."""
from __future__ import annotations

from collections import defaultdict

import streamlit as st
from streamlit.errors import StreamlitAPIException

from app.ui.feature_registry import FEATURES
from app.ui.theme_presets import (
    THEME_META,
    THEME_TOKENS,
    VALID_UI_THEMES,
    get_theme_title,
)
from app.ui_preferences import (
    LEVEL_ALL,
    clear_overrides,
    feature_visible,
    get_overrides,
    get_ui_level,
    get_ui_theme,
    set_override,
    set_ui_level,
    set_ui_theme,
)


_LEVEL_CARDS: tuple[tuple[str, str, str], ...] = (
    ("1", "Начальный", "Только базовые входы"),
    ("2", "Основной", "Учёба и прогресс"),
    ("3", "Продвинутый", "Планы и граф знаний"),
    ("4", "Профи", "Метрики и перенос"),
    ("5", "Эксперт", "Trace и диагностика"),
    (LEVEL_ALL, "Всё включено", "Полный прежний интерфейс"),
)


def _level_title(level_id: str) -> str:
    for lid, title, _desc in _LEVEL_CARDS:
        if lid == level_id:
            return title
    return level_id


def _render_level_card(level_id: str, title: str, description: str, *, current_level: str, confirm_reset: bool) -> None:
    active = current_level == level_id
    with st.container(border=True):
        if active:
            st.markdown(
                '<p style="margin:0 0 0.35rem 0;font-size:0.82rem;font-weight:600;color:#0f766e;">'
                "● Сейчас активен</p>",
                unsafe_allow_html=True,
            )
        st.markdown(f"**{title}**")
        st.caption(description)
        can_switch = confirm_reset and not active
        if st.button(
            "Выбрано" if active else "Выбрать",
            key=f"ui_level_{level_id}",
            disabled=active or not confirm_reset,
            type="primary" if active else "secondary",
            width="stretch",
        ):
            if can_switch:
                set_ui_level(level_id)
                clear_overrides()
                st.rerun()


def _render_level_cards(level: str, overrides: dict[str, bool]) -> None:
    st.markdown("**Выбор режима интерфейса**")
    st.caption(
        f"Сейчас выбран режим **{_level_title(level)}**. "
        "Переключите пресет, если хотите упростить или расширить меню и панели."
    )
    confirm_reset = True
    if overrides:
        confirm_reset = st.checkbox(
            "Сбросить точечные настройки при смене уровня",
            key="ui_level_confirm_reset",
        )
    for row_start in range(0, len(_LEVEL_CARDS), 3):
        cols = st.columns(3)
        for col, card in zip(cols, _LEVEL_CARDS[row_start : row_start + 3]):
            with col:
                _render_level_card(*card, current_level=level, confirm_reset=confirm_reset)


def _render_overrides(level: str, overrides: dict[str, bool]) -> None:
    groups: dict[str, list] = defaultdict(list)
    for spec in FEATURES:
        groups[spec.group_ru].append(spec)

    with st.expander("Тонкая настройка", expanded=False):
        st.caption("Можно включить или скрыть отдельные элементы поверх выбранного пресета.")
        for group, specs in sorted(groups.items()):
            st.markdown(f"**{group}**")
            for spec in specs:
                current = feature_visible(spec, level=level, overrides=overrides)
                cols = st.columns([0.72, 0.18, 0.1])
                with cols[0]:
                    enabled = st.toggle(
                        spec.title_ru,
                        value=current,
                        key=f"ui_feature_toggle_{spec.id}",
                    )
                with cols[1]:
                    st.caption(f"ур. {spec.tier}")
                if enabled != current:
                    set_override(spec.id, enabled)
                    st.rerun()
        if st.button("Сбросить к пресету", key="ui_overrides_clear", width="stretch"):
            clear_overrides()
            st.rerun()


def _render_theme_card(theme_id: str, *, current_theme: str) -> None:
    meta = THEME_META.get(theme_id, {})
    title = meta.get("title_ru", theme_id)
    desc = meta.get("description_ru", "")
    active = current_theme == theme_id
    tokens = THEME_TOKENS.get(theme_id, {})
    preview_bg = tokens.get("bg-app-3", "#f4ede0")
    preview_accent = tokens.get("accent", "#b95631")
    with st.container(border=True):
        st.markdown(
            f'<div style="height:2.5rem;border-radius:8px;'
            f'background:{preview_bg};'
            f'margin-bottom:0.5rem;'
            f'border-left:4px solid {preview_accent};'
            f'padding:0.2rem 0.5rem;'
            f'font-size:1.2rem;">{title[0]}</div>'
            f"**{title}**",
            unsafe_allow_html=True,
        )
        st.caption(desc)
        if st.button(
            "Выбрано" if active else "Выбрать",
            key=f"ui_theme_{theme_id}",
            disabled=active,
            type="primary" if active else "secondary",
            width="stretch",
        ):
            if not active:
                set_ui_theme(theme_id)
                st.rerun()


def _render_theme_cards() -> None:
    current = get_ui_theme()
    st.markdown("**Выбор цветовой схемы**")
    st.caption(f"Сейчас активна схема **{get_theme_title(current)}**.")
    theme_ids = sorted(VALID_UI_THEMES)
    for row_start in range(0, len(theme_ids), 3):
        cols = st.columns(3)
        for col, tid in zip(cols, theme_ids[row_start : row_start + 3]):
            with col:
                _render_theme_card(tid, current_theme=current)


@st.dialog("Панель управления", width="large")
def render_control_panel_dialog() -> None:
    ui_tab, theme_tab, rag_tab = st.tabs(["Интерфейс", "Оформление", "RAG и ingest"])
    with ui_tab:
        level = get_ui_level()
        overrides = get_overrides()
        _render_level_cards(level, overrides)
        _render_overrides(level, overrides)
        st.caption("Настройки интерфейса хранятся локально в профиле и попадают в backup.")
    with theme_tab:
        _render_theme_cards()
        st.caption("Цветовая схема хранится локально в профиле и попадает в backup.")
    with rag_tab:
        from app.ui.rag_settings_panel import render_rag_settings_section

        render_rag_settings_section()


def open_control_panel_dialog() -> None:
    """Open the control panel without crashing if another Streamlit dialog is active."""
    try:
        render_control_panel_dialog()
    except StreamlitAPIException as exc:
        if "Only one dialog is allowed" not in str(exc):
            raise
        st.warning("Закройте текущее всплывающее окно и откройте настройки ещё раз.")
