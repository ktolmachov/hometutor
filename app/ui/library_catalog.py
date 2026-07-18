"""«Библиотека области»: catalog body (P0-2a) + schedule entry (P0-2b).

Catalog body paints courses/konspekts from ``app.library_catalog_read``.
``render_library_catalog`` opens the schedule shell (Каталог | Пересадки | Маршрут).
Browse never mutates study scope; ``activate_scope`` runs only on explicit button.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, MutableMapping

import streamlit as st

from app.library_catalog_read import (
    LibraryCourse,
    LibraryKonspekt,
    library_ask_folder_rel,
    list_library_courses,
    list_library_konspekts,
    list_library_sections,
)
from app.ui.session_state import PENDING_CURRENT_VIEW_KEY
from app.ui.study_scope import activate_scope, get_active_scope
from app.ui_client import load_index_stats

LIBRARY_VIEW_NAME = "Библиотека"
_LIBRARY_QA_FOLDER_KEY = "qa_sidebar_folder_rel"


def _scope_snapshot(state: MutableMapping[str, Any] | None = None) -> dict[str, Any] | None:
    scope = get_active_scope(state)
    if not isinstance(scope, dict):
        return None
    return {
        "folder_rel": str(scope.get("folder_rel") or ""),
        "active": bool(scope.get("active")),
        "id": str(scope.get("id") or ""),
    }


def navigate_to_ask(
    folder_rel: str | None,
    *,
    state: MutableMapping[str, Any] | None = None,
) -> None:
    """Prefill Q&A folder filter and open Quick Answer. Does not activate scope.

    Empty ``folder_rel`` means whole area: clear any previous course filter so
    «Спросить по всей области» does not keep a stale ``qa_sidebar_folder_rel``.
    """
    target = state if state is not None else st.session_state
    folder = library_ask_folder_rel(folder_rel)
    # Sidebar selectbox key; empty → whole area (must drop prior course filter).
    if folder:
        target[_LIBRARY_QA_FOLDER_KEY] = folder
    else:
        target.pop(_LIBRARY_QA_FOLDER_KEY, None)
    target[PENDING_CURRENT_VIEW_KEY] = "Быстрый ответ"


def activate_course_from_library(
    course: LibraryCourse,
    *,
    state: MutableMapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Explicit «Сделать активным» only — never called from browse/list."""
    return activate_scope(
        folder_rel=course.folder_rel,
        title=course.title,
        source_paths=list(course.source_paths),
        state=state,
    )


def _render_course_actions(course: LibraryCourse, *, key_prefix: str) -> None:
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button(
            "Сделать активным",
            key=f"{key_prefix}_activate",
            width="stretch",
            help="Активирует курс как study scope (как на Mission Control).",
        ):
            activate_course_from_library(course)
            st.success(f"Активный курс: {course.title}")
            st.rerun()
    with c2:
        if st.button(
            "Спросить",
            key=f"{key_prefix}_ask",
            width="stretch",
            help="Открыть Быстрый ответ с фильтром этой папки (scope не меняется).",
        ):
            navigate_to_ask(course.folder_rel)
            st.rerun()
    with c3:
        if st.button(
            "Спросить по всей области",
            key=f"{key_prefix}_ask_all",
            width="stretch",
            help="Q&A без folder_rel — вся область индекса.",
        ):
            navigate_to_ask("")
            # Clear folder filter if previously set to a course.
            st.session_state.pop(_LIBRARY_QA_FOLDER_KEY, None)
            st.rerun()


def _render_konspekt_block(
    course: LibraryCourse,
    km: LibraryKonspekt,
    *,
    key_prefix: str,
) -> None:
    badge = f" · {km.badge}" if km.badge else ""
    source_bit = f" · source: {km.source}" if km.source else ""
    label = f"📄 {km.title}{badge}"
    with st.expander(label, expanded=False):
        st.caption(f"{km.path_rel}{source_bit}")
        if km.tags:
            st.caption("Теги: " + ", ".join(km.tags))

        sections = list_library_sections(km.path_abs)
        if sections:
            st.markdown("**Разделы**")
            for sec in sections[:40]:
                indent = " " * max(0, int(sec.level) - 1)
                st.markdown(
                    f"{indent}• L{sec.level} {sec.heading_text} "
                    f"<span style='opacity:0.55'>(стр. {sec.line_start}–{sec.line_end})</span>",
                    unsafe_allow_html=True,
                )
            if len(sections) > 40:
                st.caption(f"… и ещё {len(sections) - 40} разделов")
        else:
            st.caption("Разделы не разобраны (файл без заголовков или ещё не готов).")

        b1, b2 = st.columns(2)
        with b1:
            try:
                from app.obsidian_export import vscode_uri

                uri = vscode_uri(Path(km.path_abs))
                if uri:
                    st.link_button("Открыть в VS Code", uri, width="stretch")
            except Exception:  # noqa: BLE001 - optional deep-link
                st.caption(f"Путь: `{km.path_rel}`")
        with b2:
            if st.button(
                "Спросить по курсу",
                key=f"{key_prefix}_ask_k",
                width="stretch",
            ):
                navigate_to_ask(course.folder_rel)
                st.rerun()


def _render_source_paths(course: LibraryCourse) -> None:
    if not course.source_paths:
        return
    with st.expander(f"Документы индекса ({len(course.source_paths)})", expanded=False):
        for path in course.source_paths[:30]:
            st.caption(path)
        overflow = len(course.source_paths) - 30
        if overflow > 0:
            st.caption(f"… и ещё {overflow}")


def render_library_catalog_body(index_stats: dict | None = None) -> None:
    """Catalog segment body: courses → konspekts → sections (no outer panel)."""
    if index_stats is None:
        index_stats = load_index_stats()

    active = get_active_scope()
    if active:
        title = active.get("title") or active.get("folder_rel") or "курс"
        st.info(f"Сейчас активен: **{title}**. Каталог показывает все курсы области.")

    courses = list_library_courses(index_stats if isinstance(index_stats, dict) else None)
    if not courses:
        st.warning(
            "Курсов в области пока нет. Добавьте материалы в data/ и обновите индекс "
            "или проверьте Mission Control."
        )
        return

    st.caption(
        f"Курсов: {len(courses)}. Просмотр не активирует курс; "
        "«Сделать активным» — только явная кнопка."
    )

    for idx, course in enumerate(courses):
        reindex_mark = " · нужна переиндексация" if course.needs_reindex else ""
        docs_n = len(course.source_paths)
        st.markdown(f"### {course.title}")
        st.caption(
            f"`{course.folder_rel}` · документов в индексе: {docs_n}{reindex_mark}"
        )
        key_prefix = f"lib_{idx}_{course.folder_rel.replace('/', '_')}"
        _render_course_actions(course, key_prefix=key_prefix)

        konspekts = list_library_konspekts(course.folder_rel)
        if konspekts:
            st.markdown(f"**Конспекты** ({len(konspekts)})")
            for k_idx, km in enumerate(konspekts):
                _render_konspekt_block(
                    course,
                    km,
                    key_prefix=f"{key_prefix}_k{k_idx}",
                )
        else:
            st.caption(
                "Конспектов с `type: konspekt` в папке курса нет — "
                "ниже документы из индекса, если они есть."
            )
        _render_source_paths(course)
        st.markdown("---")


def render_library_catalog(index_stats: dict | None = None) -> None:
    """Library entry: P0-2b schedule shell (Каталог | Пересадки | Маршрут)."""
    from app.ui.library_schedule import render_library_schedule

    render_library_schedule(index_stats)


__all__ = [
    "LIBRARY_VIEW_NAME",
    "activate_course_from_library",
    "navigate_to_ask",
    "render_library_catalog",
    "render_library_catalog_body",
    "_scope_snapshot",
]
