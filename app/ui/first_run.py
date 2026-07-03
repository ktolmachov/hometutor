"""First-run empty index rescue UI."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.config import DATA_DIR
from app.demo_sandbox import (
    ALLOWED_UPLOAD_EXTS,
    count_supported_materials,
    install_demo_materials,
    remove_demo_materials,
    save_uploaded_files,
)
from app.ui_client import fetch_json
from app.user_state import get_kv, set_kv


def should_show_empty_index_hero(index_stats: dict | None) -> bool:
    if not isinstance(index_stats, dict):
        return False
    if str(index_stats.get("status") or "") != "ok":
        return True
    try:
        return int(index_stats.get("documents_count") or 0) == 0
    except (TypeError, ValueError):
        return True


def _track_door(door: str) -> None:
    try:
        from app.ui_events import track_event

        track_event("first_run_door_selected", {"door": door})
    except Exception:  # noqa: BLE001
        pass


def _start_reindex(*, reset: bool = False) -> None:
    fetch_json("POST", "/reindex", params={"reset": reset}, timeout=30)
    st.session_state["poll_reindex_status"] = True


def render_empty_index_hero(index_stats: dict | None) -> bool:
    if not should_show_empty_index_hero(index_stats):
        return False

    st.markdown("## Добавьте материалы — и получите первый ответ за минуту")
    cols = st.columns(3, gap="large")

    with cols[0]:
        st.markdown("#### Загрузить файлы")
        st.caption("Поддерживаются Markdown, TXT, PDF, DOCX и HTML.")
        upload_key = f"first_run_upload_{int(st.session_state.get('first_run_upload_counter') or 0)}"
        uploaded = st.file_uploader(
            "Файлы материалов",
            accept_multiple_files=True,
            type=sorted(ext.lstrip(".") for ext in ALLOWED_UPLOAD_EXTS),
            key=upload_key,
            label_visibility="collapsed",
        )
        if st.button("Загрузить и индексировать", key="first_run_upload_btn", type="primary", disabled=not uploaded):
            files = [(item.name, item.getvalue()) for item in uploaded or []]
            saved = save_uploaded_files(files)
            if not saved:
                st.warning("Не нашёл файлов с поддерживаемыми расширениями.")
            else:
                _track_door("upload")
                _start_reindex(reset=False)
                st.session_state["first_run_upload_counter"] = int(st.session_state.get("first_run_upload_counter") or 0) + 1
                st.rerun()

    with cols[1]:
        st.markdown("#### Попробовать демо")
        st.caption("Небольшой учебный набор, чтобы увидеть ответы с источниками без подготовки.")
        if st.button("Установить демо-материалы", key="first_run_demo_btn", type="primary"):
            install_demo_materials()
            set_kv("demo_sandbox_active", "1")
            _track_door("demo")
            _start_reindex(reset=False)
            st.rerun()

    with cols[2]:
        st.markdown("#### У меня уже есть папка")
        try:
            data_path = DATA_DIR.resolve()
        except OSError:
            data_path = Path(DATA_DIR)
        st.caption(f"Положите материалы сюда: `{data_path}`")
        if st.button("Переиндексировать", key="first_run_folder_reindex_btn", type="secondary"):
            _track_door("folder")
            _start_reindex(reset=False)
            st.rerun()

    return True


def render_demo_sandbox_banner(index_stats: dict | None) -> None:
    if get_kv("demo_sandbox_active") != "1":
        return
    if not isinstance(index_stats, dict) or int(index_stats.get("documents_count") or 0) <= 0:
        return
    st.info(
        "Вы в демо-песочнице — это учебные материалы для знакомства. "
        "Замените их на свои конспекты, когда будете готовы."
    )
    if st.button("Удалить демо-материалы", key="remove_demo_sandbox", type="secondary"):
        remove_demo_materials()
        set_kv("demo_sandbox_active", "0")
        _start_reindex(reset=count_supported_materials() == 0)
        st.rerun()
