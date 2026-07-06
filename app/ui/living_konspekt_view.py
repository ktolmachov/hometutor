"""«Живой конспект» — study-поверхность над Section Anchor Index.

Корзина (:data:`WORKBENCH_SECTIONS_KEY`) живёт в ``st.session_state`` как
реактивное зеркало. Persisted/runtime-контракт и автосохранение принадлежат
``app.workbench_service``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, MutableMapping

import streamlit as st

from app import konspekt_artifact
from app import workbench_service
from app.section_index import IndexedSection, row_to_section
from app.ui.living_konspekt_add_panel import render_add_sections_panel
from app.konspekt_artifact import (  # noqa: F401 - реэкспорт старых импортов feature-тестов
    _check_questions_block,
    _lecture_main_ideas,
    _row_konspekt_label,
    _sidecar_stale_reasons,
    _sources_footer,
    _stitch_verbatim,
    _study_pack_tail,
    _videos_block,
    media_caption_line,
)

# Медиа-кластер вынесен в living_konspekt_media (size-budget); реэкспорт имён
# сохраняет существующие импорты тестов/соседних модулей из этого файла.
from app.ui.living_konspekt_media import (  # noqa: F401 - реэкспорт
    _expected_asr_params,
    _format_timestamp,
    _media_section_for_row,
    _render_all_lesson_videos_panel,
    _render_media_panel,
    _row_section_id,
    _sidecar_stale_reasons,
    _unique_document_rows,
    render_playlist_panel,
)
from app.ui.living_konspekt_next_steps import (
    _collect_concept_context,
    render_graph_lens_panel,
    render_deep_study_panel,
    render_web_queries_panel,
)
from app.ui.living_konspekt_reader import render_reader
from app.ui.living_konspekt_workbench_panel import (
    _add_document_sections_to_workbench as _panel_add_document_sections_to_workbench,
    _row_stale_status,
    render_bulk_document_panel,
    render_collected_sections,
    render_memory_panel,
    render_term_cards_panel,
)
from app.ui.helpers import format_request_error
from app.ui.widgets import render_panel_header

WORKBENCH_SECTIONS_KEY = workbench_service.WORKBENCH_SECTIONS_KEY
_WORKBENCH_KV_KEY = workbench_service.WORKBENCH_KV_KEY
_WORKBENCH_HYDRATED_KEY = "_workbench_hydrated"
_ACTIVE_ARTIFACT_ID_KEY = "living_konspekt_active_artifact_id"
_LAST_SAVED_BODY_KEY = "living_konspekt_last_saved_body"


# ── Корзина: тонкий Streamlit-адаптер поверх app.workbench_service ───────
def _state(state: MutableMapping[str, Any] | None) -> MutableMapping[str, Any]:
    return state if state is not None else st.session_state


def _ensure_auth_context() -> None:
    from app.ui.auth_gate import ensure_streamlit_auth_context

    ensure_streamlit_auth_context()


def ensure_workbench_hydrated(state: MutableMapping[str, Any] | None = None) -> None:
    """Один раз за сессию поднять runtime rows из ``app_kv`` через сервис."""
    target = _state(state)
    if target.get(_WORKBENCH_HYDRATED_KEY):
        return
    target[_WORKBENCH_HYDRATED_KEY] = True
    if WORKBENCH_SECTIONS_KEY in target:
        target[WORKBENCH_SECTIONS_KEY] = workbench_service.normalize_runtime_rows(
            list(target.get(WORKBENCH_SECTIONS_KEY) or [])
        )
        return
    if state is not None:
        target[WORKBENCH_SECTIONS_KEY] = []
        return
    try:
        _ensure_auth_context()
        target[WORKBENCH_SECTIONS_KEY] = workbench_service.load_rows()
    except Exception:  # noqa: BLE001 - недоступный профиль → пустая корзина, не падение
        return


def set_workbench_rows(
    rows: list[dict[str, Any]],
    state: MutableMapping[str, Any] | None = None,
) -> None:
    """Заменить корзину целиком (restore research-сессии) + авто-персист через сервис."""
    target = _state(state)
    runtime_rows = workbench_service.normalize_runtime_rows([row for row in rows if isinstance(row, dict)])
    target[WORKBENCH_SECTIONS_KEY] = runtime_rows
    target[_WORKBENCH_HYDRATED_KEY] = True
    if state is None:
        try:
            _ensure_auth_context()
            workbench_service.save_rows(runtime_rows)
        except Exception:  # noqa: BLE001 - restore не должен падать из-за авто-персиста
            pass


def get_workbench_rows(state: MutableMapping[str, Any] | None = None) -> list[dict[str, Any]]:
    rows = _state(state).get(WORKBENCH_SECTIONS_KEY)
    return rows if isinstance(rows, list) else []


# TODO(W4-cleanup): внутренние UI-модули фичи ещё импортируют эти адаптеры из view;
# внешний доменный контракт уже живёт в app.workbench_service.
def add_section_to_workbench(
    section: IndexedSection,
    state: MutableMapping[str, Any] | None = None,
) -> bool:
    """Добавить раздел в session_state-зеркало; доменная операция живёт в сервисе."""
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    before = {str(row.get("row_key") or "") for row in rows}
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    new_rows = workbench_service.add_section(rows, section, storage=storage)
    target[WORKBENCH_SECTIONS_KEY] = new_rows
    added = any(str(row.get("row_key") or "") not in before for row in new_rows)
    if state is None and added:
        try:
            # Funnel «чтение → обучение»: раздел добавлен (из графа/карточки/сбора по концепту).
            from app.ui_events import track_event

            track_event("living_konspekt_section_added")
        except Exception:  # noqa: BLE001 - аналитика не должна ломать корзину
            pass
    return added


def move_section_in_workbench(
    row_key: str,
    delta: int,
    state: MutableMapping[str, Any] | None = None,
) -> bool:
    """Сдвинуть раздел по ``row_key``; доменная операция живёт в сервисе."""
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    new_rows = workbench_service.move_section(rows, row_key, delta, storage=storage)
    changed = [row.get("row_key") for row in new_rows] != [row.get("row_key") for row in rows]
    target[WORKBENCH_SECTIONS_KEY] = new_rows
    return changed


def remove_section_from_workbench(
    row_key: str,
    state: MutableMapping[str, Any] | None = None,
) -> None:
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    target[WORKBENCH_SECTIONS_KEY] = workbench_service.remove_section(rows, row_key, storage=storage)


def remove_sections_from_workbench(
    row_keys: set[str],
    state: MutableMapping[str, Any] | None = None,
) -> None:
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    target[WORKBENCH_SECTIONS_KEY] = workbench_service.remove_sections(rows, row_keys, storage=storage)


def clear_workbench(state: MutableMapping[str, Any] | None = None) -> None:
    target = _state(state)
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    target[WORKBENCH_SECTIONS_KEY] = workbench_service.clear_rows(storage=storage)


def update_section_note_in_workbench(
    row_key: str,
    note: str,
    state: MutableMapping[str, Any] | None = None,
) -> None:
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    target[WORKBENCH_SECTIONS_KEY] = workbench_service.update_section_fields(
        rows,
        row_key,
        note=note,
        storage=storage,
    )


def mark_section_read_in_workbench(
    row_key: str,
    state: MutableMapping[str, Any] | None = None,
) -> None:
    target = _state(state)
    rows = workbench_service.normalize_runtime_rows(get_workbench_rows(target))
    storage = None if state is None else workbench_service.InMemoryWorkbenchStorage()
    if state is None:
        _ensure_auth_context()
    read_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    target[WORKBENCH_SECTIONS_KEY] = workbench_service.update_section_fields(
        rows,
        row_key,
        read_at=read_at,
        storage=storage,
    )


# ── UI ────────────────────────────────────────────────────────────────────
def _media_line_for_row(
    row: dict[str, Any],
    sidecar_cache: dict[str, Any],
    stale_cache: dict[str, list[str]] | None = None,
) -> str | None:
    original = konspekt_artifact._sidecar_stale_reasons
    try:
        konspekt_artifact._sidecar_stale_reasons = _sidecar_stale_reasons
        return konspekt_artifact._media_line_for_row(row, sidecar_cache, stale_cache)
    finally:
        konspekt_artifact._sidecar_stale_reasons = original


def _add_document_sections_to_workbench(
    md_abs: str,
    rows: list[dict[str, Any]],
    state: MutableMapping[str, Any] | None = None,
) -> tuple[int, int]:
    return _panel_add_document_sections_to_workbench(md_abs, rows, add_section_to_workbench, state)


def _build_living_konspekt_body(topic: str, rows: list[dict[str, Any]], mode: str) -> str:
    if mode.startswith("Дословная"):
        return _stitch_verbatim(rows)
    from app.knowledge_synthesis import synthesize_sections  # heavy: LLM/Chroma services

    sections = [row_to_section(row) for row in rows]
    result = synthesize_sections(topic=topic, sections=sections)
    # Study Pack tail и для LLM-режима: summary модели без «Проверь себя» и
    # точных «файл:строки» — статичная выжимка, а не живой конспект.
    return "\n\n".join(block for block in (str(result["summary"]).strip(), _study_pack_tail(rows)) if block)


def _open_print_living_konspekt(title: str, body: str, rows: list[dict[str, Any]]) -> None:
    from app.ui.print_view import open_print_view

    documents = list(dict.fromkeys(_row_konspekt_label(row) for row in rows))
    open_print_view(
        title=title,
        subtitle="Живой конспект для печати или PDF.",
        body_md=body,
        export_md=f"# {title}\n\n{body}\n",
        documents=documents,
        sources=[
            {
                "file_name": _row_konspekt_label(row),
                "text": str(row.get("heading_text") or ""),
                "line_start": row.get("line_start"),
                "line_end": row.get("line_end"),
            }
            for row in rows
        ],
    )


def _request_reindex_from_ui() -> None:
    from app.ui_client import fetch_json

    fetch_json("POST", "/reindex", timeout=30, params={"reset": False})
    st.session_state["poll_reindex_status"] = True


def _render_saved_artifacts_panel() -> None:
    from app.obsidian_export import obsidian_uri, vault_root, vscode_uri

    st.markdown("### Мои конспекты")
    artifacts = konspekt_artifact.scan_saved_artifacts(vault_root())
    if not artifacts:
        st.caption("Сохранённых живых конспектов пока нет.")
        return

    for idx, artifact in enumerate(artifacts):
        with st.container(border=True):
            cols = st.columns([5, 1.2, 1.2, 1.2])
            with cols[0]:
                st.markdown(f"**{artifact.title}**")
                manifest_label = f"id: `{artifact.artifact_id}`" if artifact.has_manifest else "без манифеста"
                st.caption(
                    f"{artifact.name} · разделов: {artifact.section_count} · обновлён: {artifact.updated_at} · "
                    f"{manifest_label}"
                )
            with cols[1]:
                st.link_button("📄 Открыть", obsidian_uri(artifact.path), width="stretch")
            with cols[2]:
                st.link_button("🖥 VS Code", vscode_uri(artifact.path), width="stretch")
            with cols[3]:
                artifact_key = artifact.artifact_id or artifact.path.stem
                if st.button(
                    "↩ Пересобрать",
                    key=f"living_artifact_reassemble_{idx}_{artifact_key}",
                    width="stretch",
                    disabled=not artifact.can_reassemble,
                ):
                    try:
                        manifest = konspekt_artifact.parse_manifest(
                            artifact.path.read_text(encoding="utf-8", errors="replace")
                        )
                        if manifest is None:
                            st.error("В файле нет манифеста живого конспекта.")
                            return
                        rows = konspekt_artifact.reassemble_rows(manifest)
                        set_workbench_rows(rows)
                        st.session_state[_ACTIVE_ARTIFACT_ID_KEY] = manifest.artifact_id
                        st.session_state["living_konspekt_title"] = manifest.title
                        st.session_state["living_konspekt_last_saved"] = str(artifact.path)
                        st.session_state.pop(_LAST_SAVED_BODY_KEY, None)
                        try:
                            from app.ui_events import track_event

                            payload = {"artifact_id": manifest.artifact_id, "sections": len(rows)}
                            track_event("artifact_reopened", payload)
                            track_event("artifact_rebuilt", payload)
                        except Exception:  # noqa: BLE001 - аналитика не должна ломать пересборку
                            pass
                    except (OSError, UnicodeError, ValueError) as exc:
                        st.error(f"Не удалось пересобрать конспект: {format_request_error(exc)}")
                    else:
                        st.toast("Конспект пересобран в корзину.", icon="📚")
                        st.rerun()


def _render_build_panel(rows: list[dict[str, Any]]) -> None:
    st.markdown("### 📚 Собрать рабочий конспект")
    # Дефолт через setdefault ДО инстанцирования: value= вместе с key= для уже
    # существующего session_state-ключа — анти-паттерн (Streamlit его игнорирует и warn'ит).
    st.session_state.setdefault("living_konspekt_title", "Рабочий конспект")
    topic = st.text_input(
        "Название конспекта",
        key="living_konspekt_title",
    )
    mode = st.radio(
        "Способ сборки",
        ["Дословная сшивка (без LLM)", "LLM-синтез из разделов"],
        key="living_konspekt_mode",
        horizontal=True,
    )
    action_cols = st.columns([1.2, 1.1, 1])
    with action_cols[0]:
        save_clicked = st.button("Собрать и сохранить", key="living_konspekt_build", type="primary", width="stretch")
    with action_cols[1]:
        save_new_clicked = st.button("Сохранить как новый", key="living_konspekt_build_new", width="stretch")
    with action_cols[2]:
        print_clicked = st.button("Печать/PDF", key="living_konspekt_print", width="stretch")
    if save_clicked or save_new_clicked:
        try:
            body = _build_living_konspekt_body(topic, rows, mode)
            target_path = konspekt_artifact.save_artifact(
                topic,
                body,
                rows,
                artifact_id=st.session_state.get(_ACTIVE_ARTIFACT_ID_KEY),
                save_as_new=save_new_clicked,
            )
            manifest = konspekt_artifact.parse_manifest(target_path.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001 - показать пользователю причину сбора/сохранения
            st.error(f"Не удалось собрать конспект: {format_request_error(exc)}")
        else:
            st.session_state["living_konspekt_last_saved"] = str(target_path)
            st.session_state[_LAST_SAVED_BODY_KEY] = body
            if manifest is not None:
                st.session_state[_ACTIVE_ARTIFACT_ID_KEY] = manifest.artifact_id
            try:
                from app.ui_events import track_event

                track_event(
                    "living_konspekt_saved",
                    {"mode": "verbatim" if mode.startswith("Дословная") else "synthesis", "sections": len(rows)},
                )
            except Exception:  # noqa: BLE001 - аналитика не должна ломать сохранение
                pass
            st.success("✅ Сохранено в vault. Войдёт в поиск и граф после обновления индекса.")
    if print_clicked:
        try:
            body = _build_living_konspekt_body(topic, rows, mode)
            _open_print_living_konspekt(topic, body, rows)
        except Exception as exc:  # noqa: BLE001 - показать пользователю причину подготовки print-view
            st.error(f"Не удалось подготовить печать/PDF: {format_request_error(exc)}")
        else:
            st.rerun()

    # Файл — стартовая площадка, а не финал: постоянный CTA-ряд по последнему сохранённому
    # (переживает rerun'ы — success-строка выше живёт только один прогон).
    last_saved = str(st.session_state.get("living_konspekt_last_saved") or "")
    if last_saved:
        from app.obsidian_export import obsidian_uri, vscode_uri

        saved_path = Path(last_saved)
        st.caption(f"Последний собранный: `{saved_path.name}`")
        cta_cols = st.columns(4)
        with cta_cols[0]:
            st.link_button("📄 Открыть в Obsidian", obsidian_uri(saved_path), width="stretch")
        with cta_cols[1]:
            st.link_button("🖥 Открыть в VS Code", vscode_uri(saved_path), width="stretch")
        with cta_cols[2]:
            if st.button("🔄 Обновить индекс", key="living_konspekt_reindex", width="stretch"):
                try:
                    _request_reindex_from_ui()
                except Exception as exc:  # noqa: BLE001 - показать пользователю причину отказа API
                    st.error(f"Не удалось запустить переиндексацию: {format_request_error(exc)}")
                else:
                    st.success("Переиндексация запущена.")
                    st.rerun()
        with cta_cols[3]:
            saved_body = str(st.session_state.get(_LAST_SAVED_BODY_KEY) or "")
            if st.button("🖨 Печать/PDF", key="living_konspekt_last_print", width="stretch", disabled=not saved_body):
                _open_print_living_konspekt(topic, saved_body, rows)
                st.rerun()
        st.caption("Следующий шаг: «🃏 Карточки из терминов» ниже — и конспект начнёт повторяться сам.")
    st.divider()
    _render_saved_artifacts_panel()


def render_living_konspekt_view() -> None:
    from app.ui.reindex_poll import poll_reindex_status

    ensure_workbench_hydrated()
    poll_reindex_status()
    render_panel_header(
        "📚 Живой конспект",
        "Собирайте разделы лекций из графа/карточек, проверяйте актуальность и готовьте промпт "
        "для глубокого изучения — всё локально, облако только по вашей ссылке.",
    )

    rows = get_workbench_rows()
    st.caption(
        f"В корзине: {len(rows)} раздел(ов) · автосохраняется локально и переживает перезапуск; "
        "именованные сессии в сайдбаре — для снимков-вариантов."
    )
    render_add_sections_panel(expanded=not rows)

    if not rows:
        st.info(
            "Корзина пуста. Найдите разделы прямо здесь, добавьте их из Knowledge Graph "
            "или кнопкой «➕ В рабочий конспект» под карточкой Flashcards."
        )
        return

    tab_sections, tab_reader, tab_memory, tab_export, tab_next = st.tabs(
        ["🧩 Разделы", "📖 Читать", "🧠 Память", "📚 Сохранить", "🌐 Дальше"]
    )
    with tab_sections:
        _render_all_lesson_videos_panel(rows)
        render_playlist_panel(rows)
        render_bulk_document_panel(
            rows,
            add_document_sections=_add_document_sections_to_workbench,
            remove_rows=remove_sections_from_workbench,
            clear_rows=clear_workbench,
        )
        render_collected_sections(
            rows,
            move_section=move_section_in_workbench,
            remove_section=remove_section_from_workbench,
        )
    with tab_reader:
        render_reader(
            rows,
            media_renderer=_render_media_panel,
            save_note=update_section_note_in_workbench,
            mark_read=mark_section_read_in_workbench,
        )
    with tab_memory:
        render_memory_panel(rows)
        render_term_cards_panel(rows)
    with tab_export:
        _render_build_panel(rows)
    with tab_next:
        render_web_queries_panel(rows)
        st.divider()
        render_graph_lens_panel(rows)
        st.divider()
        render_deep_study_panel(rows)
