"""«Живой конспект» — study-поверхность над Section Anchor Index.

Корзина (:data:`WORKBENCH_SECTIONS_KEY`) живёт в ``st.session_state`` как
реактивное зеркало. Persisted/runtime-контракт и автосохранение принадлежат
``app.workbench_service``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, MutableMapping

import streamlit as st

from app import konspekt_artifact
from app.section_index import IndexedSection, row_to_section
from app.ui.living_konspekt_add_panel import render_add_sections_panel
from app.konspekt_artifact import (  # noqa: F401 - реэкспорт старых импортов feature-тестов
    _check_questions_block,
    _lecture_main_ideas,
    _row_konspekt_label,
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
    render_course_coverage_panel,
    render_deep_study_panel,
    render_web_queries_panel,
)
from app.ui.living_konspekt_quiz_panel import render_living_konspekt_quiz_panel
from app.ui.living_konspekt_reader import render_reader
from app.ui.living_konspekt_workbench_panel import (
    _add_document_sections_to_workbench as _panel_add_document_sections_to_workbench,
    _row_stale_status,
    render_bulk_document_panel,
    render_cleanup_panel,
    render_collected_sections,
    render_memory_panel,
    render_term_cards_panel,
)
from app.ui.helpers import format_request_error
from app.ui.widgets import render_panel_header

_ACTIVE_ARTIFACT_ID_KEY = "living_konspekt_active_artifact_id"
_LAST_SAVED_BODY_KEY = "living_konspekt_last_saved_body"
_NEW_TITLE_PICK = "__new__"
_TITLE_PICK_KEY = "living_konspekt_title_pick"
_TITLE_PICK_PREV_KEY = "living_konspekt_title_pick_prev"
_TITLE_PICK_PENDING_KEY = "living_konspekt_title_pick_pending"


def _apply_title_pick(
    picked_id: str,
    id_to_artifact: dict[str, konspekt_artifact.SavedArtifact],
) -> None:
    if picked_id == _NEW_TITLE_PICK:
        st.session_state.pop(_ACTIVE_ARTIFACT_ID_KEY, None)
        return
    artifact = id_to_artifact[picked_id]
    st.session_state["living_konspekt_title"] = artifact.title
    st.session_state[_ACTIVE_ARTIFACT_ID_KEY] = artifact.artifact_id


def _render_konspekt_title_fields() -> str:
    from app.obsidian_export import vault_root

    st.session_state.setdefault("living_konspekt_title", "Рабочий конспект")
    artifacts = [
        artifact
        for artifact in konspekt_artifact.scan_saved_artifacts(vault_root())
        if artifact.artifact_id
    ]
    if not artifacts:
        return st.text_input("Название конспекта", key="living_konspekt_title")

    id_to_artifact = {artifact.artifact_id: artifact for artifact in artifacts}
    if _TITLE_PICK_PENDING_KEY in st.session_state:
        pending_val = st.session_state.pop(_TITLE_PICK_PENDING_KEY)
        st.session_state[_TITLE_PICK_KEY] = pending_val
        st.session_state[_TITLE_PICK_PREV_KEY] = pending_val

    active_id = st.session_state.get(_ACTIVE_ARTIFACT_ID_KEY)
    if active_id in id_to_artifact:
        st.session_state.setdefault(_TITLE_PICK_KEY, active_id)
    else:
        st.session_state.setdefault(_TITLE_PICK_KEY, _NEW_TITLE_PICK)

    def _format_pick(artifact_id: str) -> str:
        if artifact_id == _NEW_TITLE_PICK:
            return "— новое название —"
        artifact = id_to_artifact[artifact_id]
        return f"{artifact.title} · {artifact.section_count} разд."

    picked_id = st.selectbox(
        "Существующий конспект",
        [_NEW_TITLE_PICK, *id_to_artifact.keys()],
        format_func=_format_pick,
        key=_TITLE_PICK_KEY,
    )
    prev_picked = st.session_state.get(_TITLE_PICK_PREV_KEY)
    if prev_picked != picked_id:
        st.session_state[_TITLE_PICK_PREV_KEY] = picked_id
        _apply_title_pick(picked_id, id_to_artifact)
        # «Возврат» к существующему конспекту: пользователь выбрал артефакт в пикере.
        # Pending-флоу после save/rebuild выставляет prev==picked одинаково → сюда не
        # попадает, поэтому это именно ручной выбор, а не эхо пересборки.
        if picked_id != _NEW_TITLE_PICK:
            try:
                from app.ui_events import track_event

                track_event(
                    "artifact_reopened",
                    {"artifact_id": picked_id, "sections": id_to_artifact[picked_id].section_count},
                )
            except Exception:  # noqa: BLE001 - аналитика не должна ломать пикер
                pass

    return st.text_input("Название конспекта", key="living_konspekt_title")


# ── Корзина: state-адаптеры вынесены в living_konspekt_state (size-budget) ──
# Реэкспорт сохраняет существующие импорты тестов/соседних UI-модулей из view.
from app.ui.living_konspekt_state import (  # noqa: F401 - реэкспорт адаптеров
    WORKBENCH_SECTIONS_KEY,
    add_section_to_workbench,
    clear_workbench,
    ensure_project_goal_hydrated,
    ensure_workbench_hydrated,
    get_project_goal,
    get_workbench_rows,
    mark_section_read_in_workbench,
    mark_section_listened_in_workbench,
    set_knowledge_status_in_workbench,
    set_open_question_in_workbench,
    move_section_in_workbench,
    remove_section_from_workbench,
    remove_sections_from_workbench,
    set_project_goal,
    set_workbench_rows,
    update_section_note_in_workbench,
)


# ── UI ────────────────────────────────────────────────────────────────────
# _media_line_for_row (медиа-подпись строки для артефакта) — доменная функция
# из konspekt_artifact. Раньше здесь был monkey-patch, подменявший
# konspekt_artifact._sidecar_stale_reasons UI-версией «на время вызова» — но
# реализации были побайтово идентичны, патч был no-op и при том не потокобезопасен
# (несколько Streamlit-сессий = потоки). Реализация теперь единая в media_sidecar.
_media_line_for_row = konspekt_artifact._media_line_for_row


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
    # SYNTHESIS_PROMPT просит модель писать «## Источники» — но авторитетный провенанс
    # с точными «файл:строки» даёт _study_pack_tail. Убираем LLM-ный хвост во избежание
    # дубля (в сохранённом артефакте их было два подряд).
    summary = _strip_synthesis_tail_sections(str(result["summary"]).strip())
    # Медиа-слой: раньше в LLM-режиме sidecar_cache не заполнялся и «🎬 Видео материалов»
    # пропадал целиком — хотя sidecar свежий и доверенные таймкоды есть. Восстанавливаем.
    videos = konspekt_artifact.build_videos_block_for_rows(rows)
    tail = _study_pack_tail(rows)
    return "\n\n".join(block for block in (summary, videos, tail) if block)


# Заголовки хвостовых блоков, которые SYNTHESIS_PROMPT просит модель генерировать, но
# которые детерминированно и точнее собирает _study_pack_tail. Сравнение без регистра.
_SYNTH_TAIL_HEADINGS = frozenset(
    {"## источники", "## источник", "## ✅ проверь себя", "## проверь себя"}
)


def _strip_synthesis_tail_sections(summary: str) -> str:
    """Отрезать LLM-ные блоки «Источники»/«Проверь себя» — их заменяет _study_pack_tail."""
    if not summary:
        return summary
    lines = summary.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower() in _SYNTH_TAIL_HEADINGS:
            return "\n".join(lines[:i]).rstrip()
    return summary


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


def _clear_deleted_artifact_session_refs(artifact: konspekt_artifact.SavedArtifact) -> None:
    last_saved = str(st.session_state.get("living_konspekt_last_saved") or "")
    if last_saved:
        try:
            same_file = Path(last_saved).resolve() == artifact.path.resolve()
        except OSError:
            same_file = last_saved == str(artifact.path)
        if same_file:
            st.session_state.pop("living_konspekt_last_saved", None)
            st.session_state.pop(_LAST_SAVED_BODY_KEY, None)
    if artifact.artifact_id and st.session_state.get(_ACTIVE_ARTIFACT_ID_KEY) == artifact.artifact_id:
        st.session_state.pop(_ACTIVE_ARTIFACT_ID_KEY, None)
    if artifact.artifact_id and (
        st.session_state.get(_TITLE_PICK_KEY) == artifact.artifact_id
        or st.session_state.get(_TITLE_PICK_PENDING_KEY) == artifact.artifact_id
    ):
        st.session_state[_TITLE_PICK_PENDING_KEY] = _NEW_TITLE_PICK


def _render_saved_artifacts_panel() -> None:
    from app.obsidian_export import obsidian_uri, vault_root, vscode_uri

    st.markdown("### Мои конспекты")
    artifacts = konspekt_artifact.scan_saved_artifacts(vault_root())
    if not artifacts:
        st.caption("Сохранённых живых конспектов пока нет.")
        return

    for idx, artifact in enumerate(artifacts):
        with st.container(border=True):
            cols = st.columns([5, 1.1, 1.1, 1.1, 0.9])
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
                        set_project_goal(manifest.goal if isinstance(manifest.goal, dict) else {})
                        st.session_state[_ACTIVE_ARTIFACT_ID_KEY] = manifest.artifact_id
                        st.session_state["living_konspekt_title"] = manifest.title
                        st.session_state[_TITLE_PICK_PENDING_KEY] = manifest.artifact_id
                        st.session_state["living_konspekt_last_saved"] = str(artifact.path)
                        st.session_state.pop(_LAST_SAVED_BODY_KEY, None)
                        try:
                            from app.ui_events import track_event

                            # «Пересобрать» = rebuild в корзину. «Возврат» (artifact_reopened)
                            # трекается отдельно — выбором существующего конспекта в пикере выше,
                            # а не этой кнопкой (раньше оба события стреляли одновременно → метрики
                            # «rebuild» и «reopen» были тождественны).
                            track_event("artifact_rebuilt", {"artifact_id": manifest.artifact_id, "sections": len(rows)})
                        except Exception:  # noqa: BLE001 - аналитика не должна ломать пересборку
                            pass
                    except (OSError, UnicodeError, ValueError) as exc:
                        st.error(f"Не удалось пересобрать конспект: {format_request_error(exc)}")
                    else:
                        st.toast("Конспект пересобран в корзину.", icon="📚")
                        st.rerun()
            with cols[4]:
                artifact_key = artifact.artifact_id or artifact.path.stem
                if st.button(
                    "🗑 Удалить",
                    key=f"living_artifact_delete_{idx}_{artifact_key}",
                    width="stretch",
                ):
                    try:
                        root = vault_root()
                        konspekt_artifact.delete_saved_artifact(artifact.path, root)
                        _clear_deleted_artifact_session_refs(artifact)
                        try:
                            from app.ui_events import track_event

                            track_event(
                                "artifact_deleted",
                                {"artifact_id": artifact.artifact_id, "name": artifact.name},
                            )
                        except Exception:  # noqa: BLE001 - аналитика не должна ломать удаление
                            pass
                    except (OSError, ValueError, FileNotFoundError) as exc:
                        st.error(f"Не удалось удалить конспект: {format_request_error(exc)}")
                    else:
                        st.toast(f"Конспект «{artifact.title}» удалён.", icon="🗑")
                        st.rerun()


def _render_build_panel(rows: list[dict[str, Any]]) -> None:
    st.markdown("### 📚 Собрать рабочий конспект")
    topic = _render_konspekt_title_fields()
    mode = st.radio(
        "Способ сборки",
        ["Дословная сшивка (без LLM)", "LLM-синтез из разделов"],
        key="living_konspekt_mode",
        horizontal=True,
    )
    action_cols = st.columns([1.35, 1.0, 1.0, 0.9])
    with action_cols[0]:
        save_and_map_clicked = st.button(
            "Сохранить и обновить карту",
            key="living_konspekt_build",
            type="primary",
            width="stretch",
            help="Сохранит конспект и запустит обновление поиска и карты курса.",
        )
    with action_cols[1]:
        save_clicked = st.button("Только сохранить", key="living_konspekt_save_only", width="stretch")
    with action_cols[2]:
        save_new_clicked = st.button("Сохранить как новый", key="living_konspekt_build_new", width="stretch")
    with action_cols[3]:
        print_clicked = st.button("Печать/PDF", key="living_konspekt_print", width="stretch")
    if save_and_map_clicked or save_clicked or save_new_clicked:
        try:
            body = _build_living_konspekt_body(topic, rows, mode)
            target_path = konspekt_artifact.save_artifact(
                topic,
                body,
                rows,
                artifact_id=st.session_state.get(_ACTIVE_ARTIFACT_ID_KEY),
                goal=get_project_goal(),
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
                st.session_state[_TITLE_PICK_PENDING_KEY] = manifest.artifact_id
            try:
                from app.ui_events import track_event

                track_event(
                    "living_konspekt_saved",
                    {"mode": "verbatim" if mode.startswith("Дословная") else "synthesis", "sections": len(rows)},
                )
            except Exception:  # noqa: BLE001 - аналитика не должна ломать сохранение
                pass
            if save_and_map_clicked:
                try:
                    _request_reindex_from_ui()
                except Exception as exc:  # noqa: BLE001 - показать пользователю причину отказа API
                    st.warning(
                        "Конспект сохранён, но обновление карты не запустилось: "
                        f"{format_request_error(exc)}"
                    )
                else:
                    st.success("Конспект сохранён. Обновляю поиск и карту курса…")
            else:
                st.toast("Конспект сохранён. Карту курса можно обновить отдельной кнопкой.", icon="✅")
            st.rerun()
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
            if st.button("🔄 Обновить карту курса", key="living_konspekt_reindex", width="stretch"):
                try:
                    _request_reindex_from_ui()
                except Exception as exc:  # noqa: BLE001 - показать пользователю причину отказа API
                    st.error(f"Не удалось запустить обновление карты: {format_request_error(exc)}")
                else:
                    st.success("Обновление поиска и карты курса запущено.")
                    st.rerun()
        with cta_cols[3]:
            saved_body = str(st.session_state.get(_LAST_SAVED_BODY_KEY) or "")
            if st.button("🖨 Печать/PDF", key="living_konspekt_last_print", width="stretch", disabled=not saved_body):
                _open_print_living_konspekt(topic, saved_body, rows)
                st.rerun()
        st.caption("Следующий шаг: «🃏 Карточки из терминов» ниже — и конспект начнёт повторяться сам.")
    st.divider()
    _render_saved_artifacts_panel()


def _render_project_goal_panel() -> None:
    goal = get_project_goal()
    current = str(goal.get("text") or "")
    st.session_state.setdefault("living_konspekt_goal_text", current)
    st.text_area(
        "Цель конспекта",
        key="living_konspekt_goal_text",
        placeholder="Например: подготовиться к коллоквиуму по теме агентов за 40 минут.",
        height=80,
    )
    if st.button("Сохранить цель", key="living_konspekt_goal_save", width="stretch"):
        updated = set_project_goal({"text": st.session_state.get("living_konspekt_goal_text")})
        if updated.get("text"):
            st.toast("Цель конспекта сохранена.", icon="🎯")
        else:
            st.toast("Цель очищена.", icon="🎯")
        st.rerun()


def _reader_media_renderer(row: dict[str, Any], is_first: bool) -> None:
    # key_prefix отличает чекбоксы "Показать видео" от вкладки «Разделы»: одна и та же
    # строка рендерится в обеих вкладках за один rerun, ключи виджетов не могут совпадать.
    _render_media_panel(row, is_first, key_prefix="reader", mark_listened=mark_section_listened_in_workbench)


def render_living_konspekt_view() -> None:
    from app.ui.reindex_poll import poll_reindex_status

    ensure_workbench_hydrated()
    ensure_project_goal_hydrated()
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
    _render_project_goal_panel()
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
        render_cleanup_panel(
            rows,
            remove_rows=remove_sections_from_workbench,
            clear_rows=clear_workbench,
        )
        render_collected_sections(
            rows,
            move_section=move_section_in_workbench,
            remove_section=remove_section_from_workbench,
            mark_listened=mark_section_listened_in_workbench,
            set_status=set_knowledge_status_in_workbench,
            set_question=set_open_question_in_workbench,
        )
    with tab_reader:
        render_reader(
            rows,
            media_renderer=_reader_media_renderer,
            save_note=update_section_note_in_workbench,
            mark_read=mark_section_read_in_workbench,
            mark_listened=mark_section_listened_in_workbench,
            set_status=set_knowledge_status_in_workbench,
            set_question=set_open_question_in_workbench,
        )
    with tab_memory:
        render_memory_panel(rows)
        render_term_cards_panel(rows)
        render_living_konspekt_quiz_panel(
            rows,
            title=str(st.session_state.get("living_konspekt_title") or "Рабочий конспект"),
            goal=get_project_goal(),
        )
    with tab_export:
        _render_build_panel(rows)
    with tab_next:
        render_web_queries_panel(rows)
        st.divider()
        render_graph_lens_panel(rows)
        st.divider()
        render_course_coverage_panel(rows)
        st.divider()
        render_deep_study_panel(rows)
