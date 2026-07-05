"""UI: управление основными и расширенными настройками RAG и ingest."""
from __future__ import annotations

from typing import Any

import streamlit as st

from app.rag_runtime_preferences import (
    RAG_SETTING_SPECS,
    RagSettingSpec,
    clear_overrides,
    effective_value,
    get_overrides,
    grouped_specs,
    set_override,
)


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "да" if value else "нет"
    if value is None or value == "":
        return "—"
    return str(value)


def _render_bool_field(spec: RagSettingSpec, *, current: Any, overridden: bool) -> None:
    enabled = st.toggle(
        spec.title_ru,
        value=bool(current),
        key=f"rag_setting_bool_{spec.key}",
        help=spec.help_ru or None,
    )
    if overridden:
        st.caption(f"`{spec.env_key}` · переопределено")
    else:
        st.caption(f"`{spec.env_key}` · из config.env")
    if enabled != bool(current):
        set_override(spec.key, enabled)
        st.rerun()


def _render_select_field(spec: RagSettingSpec, *, current: Any, overridden: bool) -> None:
    options = list(spec.options or ())
    if not options:
        return
    current_str = str(current or options[0]).lower()
    if current_str not in options:
        current_str = options[0]
    idx = options.index(current_str)
    selected = st.selectbox(
        spec.title_ru,
        options=options,
        index=idx,
        key=f"rag_setting_select_{spec.key}",
        help=spec.help_ru or None,
    )
    suffix = " · переопределено" if overridden else " · из config.env"
    st.caption(f"`{spec.env_key}`{suffix}")
    if selected != current_str:
        set_override(spec.key, selected)
        st.rerun()


def _render_int_field(spec: RagSettingSpec, *, current: Any, overridden: bool) -> None:
    value = st.number_input(
        spec.title_ru,
        value=int(current),
        min_value=int(spec.min_val) if spec.min_val is not None else None,
        max_value=int(spec.max_val) if spec.max_val is not None else None,
        step=1,
        key=f"rag_setting_int_{spec.key}",
        help=spec.help_ru or None,
    )
    suffix = " · переопределено" if overridden else " · из config.env"
    st.caption(f"`{spec.env_key}`{suffix}")
    if int(value) != int(current):
        set_override(spec.key, int(value))
        st.rerun()


def _render_float_field(spec: RagSettingSpec, *, current: Any, overridden: bool) -> None:
    value = st.number_input(
        spec.title_ru,
        value=float(current),
        min_value=float(spec.min_val) if spec.min_val is not None else None,
        max_value=float(spec.max_val) if spec.max_val is not None else None,
        step=0.01,
        format="%.4f",
        key=f"rag_setting_float_{spec.key}",
        help=spec.help_ru or None,
    )
    suffix = " · переопределено" if overridden else " · из config.env"
    st.caption(f"`{spec.env_key}`{suffix}")
    if float(value) != float(current):
        set_override(spec.key, float(value))
        st.rerun()


def _render_str_field(spec: RagSettingSpec, *, current: Any, overridden: bool) -> None:
    text = st.text_input(
        spec.title_ru,
        value=str(current or ""),
        key=f"rag_setting_str_{spec.key}",
        help=spec.help_ru or None,
    )
    suffix = " · переопределено" if overridden else " · из config.env"
    st.caption(f"`{spec.env_key}`{suffix}")
    normalized = text.strip()
    current_norm = str(current or "").strip()
    if normalized != current_norm:
        set_override(spec.key, normalized)
        st.rerun()


def _render_setting_field(spec: RagSettingSpec, overrides: dict[str, Any]) -> None:
    current = effective_value(spec, overrides)
    overridden = spec.key in overrides
    if spec.requires_reindex:
        st.caption("⚠ После изменения нужна переиндексация")
    if spec.kind == "bool":
        _render_bool_field(spec, current=current, overridden=overridden)
    elif spec.kind == "select":
        _render_select_field(spec, current=current, overridden=overridden)
    elif spec.kind == "int":
        _render_int_field(spec, current=current, overridden=overridden)
    elif spec.kind == "float":
        _render_float_field(spec, current=current, overridden=overridden)
    else:
        _render_str_field(spec, current=current, overridden=overridden)


def _render_spec_group(title: str, specs: list[RagSettingSpec], overrides: dict[str, Any]) -> None:
    with st.expander(title, expanded=False):
        for spec in specs:
            _render_setting_field(spec, overrides)
            st.divider()


def render_rag_settings_section() -> None:
    """Блок «RAG и ingest» внутри панели управления."""
    overrides = get_overrides()
    st.markdown("**RAG и ingest**")
    st.caption(
        "Эффективные значения: `config.env` / `.env` + ваши локальные overrides. "
        "Настройки chunking/embeddings и ingest вступают после **переиндексации**; "
        "retrieval — с следующего запроса. Overrides хранятся в профиле (`app_kv`) и попадают в backup."
    )
    if overrides:
        st.info(f"Активных переопределений: **{len(overrides)}**")
    else:
        st.caption("Переопределений нет — используются значения из окружения.")

    tab_main, tab_advanced = st.tabs(["Основные", "Расширенные"])

    with tab_main:
        groups = grouped_specs(advanced=False)
        for group_title, specs in groups.items():
            _render_spec_group(group_title, specs, overrides)

    with tab_advanced:
        groups = grouped_specs(advanced=True)
        for group_title, specs in groups.items():
            _render_spec_group(group_title, specs, overrides)

    if st.button("Сбросить RAG/ingest к config.env", key="rag_settings_clear", width="stretch"):
        clear_overrides()
        st.rerun()


def render_rag_settings_summary_caption() -> None:
    """Короткая сводка для подписи под панелью."""
    rs = next((s for s in RAG_SETTING_SPECS if s.key == "rag_profile"), None)
    rm = next((s for s in RAG_SETTING_SPECS if s.key == "retrieval_mode"), None)
    if not rs or not rm:
        return
    overrides = get_overrides()
    profile = effective_value(rs, overrides)
    mode = effective_value(rm, overrides)
    st.caption(f"Сейчас: профиль **{profile}**, режим **{mode}**.")
