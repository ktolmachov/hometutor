"""Control panel for UI visibility levels and feature overrides."""
from __future__ import annotations

from collections import defaultdict

import streamlit as st

from app.ui.feature_registry import FEATURES
from app.ui_preferences import (
    LEVEL_ALL,
    clear_overrides,
    feature_visible,
    get_overrides,
    get_ui_level,
    set_override,
    set_ui_level,
)


_LEVEL_CARDS: tuple[tuple[str, str, str], ...] = (
    ("1", "Начальный", "Только базовые входы"),
    ("2", "Основной", "Учёба и прогресс"),
    ("3", "Продвинутый", "Планы и граф знаний"),
    ("4", "Профи", "Метрики и перенос"),
    ("5", "Эксперт", "Trace и диагностика"),
    (LEVEL_ALL, "Всё включено", "Полный прежний интерфейс"),
)


def _render_level_card(level_id: str, title: str, description: str, *, current_level: str, confirm_reset: bool) -> None:
    active = current_level == level_id
    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.caption(description)
        disabled = active or not confirm_reset
        label = "Выбрано" if active else "Выбрать"
        if st.button(label, key=f"ui_level_{level_id}", disabled=disabled, width="stretch"):
            set_ui_level(level_id)
            clear_overrides()
            st.rerun()


def _render_level_cards(level: str, overrides: dict[str, bool]) -> None:
    st.caption("Выберите, сколько интерфейса показывать по умолчанию.")
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


@st.dialog("Панель управления", width="large")
def render_control_panel_dialog() -> None:
    ui_tab, rag_tab = st.tabs(["Интерфейс", "RAG и ingest"])
    with ui_tab:
        level = get_ui_level()
        overrides = get_overrides()
        _render_level_cards(level, overrides)
        _render_overrides(level, overrides)
        st.caption("Настройки интерфейса хранятся локально в профиле и попадают в backup.")
    with rag_tab:
        from app.ui.rag_settings_panel import render_rag_settings_section

        render_rag_settings_section()
