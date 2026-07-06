"""«Живой конспект» — study-поверхность над Section Anchor Index.

Корзина (:data:`WORKBENCH_SECTIONS_KEY`) живёт в ``st.session_state`` как
реактивное зеркало. Persisted/runtime-контракт и автосохранение принадлежат
``app.workbench_service``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, MutableMapping

import streamlit as st

from app import konspekt_artifact
from app import workbench_service
from app.section_index import IndexedSection, parse_sections, row_to_section
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
)
from app.ui.living_konspekt_next_steps import (
    _collect_concept_context,
    render_deep_study_panel,
    render_web_queries_panel,
)
from app.ui.living_konspekt_reader import render_reader
from app.ui.helpers import format_request_error
from app.ui.widgets import render_panel_header

WORKBENCH_SECTIONS_KEY = workbench_service.WORKBENCH_SECTIONS_KEY
_WORKBENCH_KV_KEY = workbench_service.WORKBENCH_KV_KEY
_WORKBENCH_HYDRATED_KEY = "_workbench_hydrated"
_ACTIVE_ARTIFACT_ID_KEY = "living_konspekt_active_artifact_id"
_LAST_SAVED_BODY_KEY = "living_konspekt_last_saved_body"
_SLUG_RE = re.compile(r"[^\w\-]+", re.UNICODE)


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


def _duplicate_heading_keys(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """``(konspekt_md_abs, heading_text)`` с >1 разделом в корзине.

    Obsidian-якорь открывает **первый** одноимённый heading в файле — при дублях он может
    привести не туда, куда собрали раздел (см. план, «Тонкий риск — одинаковые заголовки»).
    """
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row.get("konspekt_md_abs") or ""), str(row.get("heading_text") or ""))
        counts[key] = counts.get(key, 0) + 1
    return {key for key, count in counts.items() if count > 1}


def _row_konspekt_label(row: dict[str, Any]) -> str:
    md_abs = str(row.get("konspekt_md_abs") or "")
    if md_abs:
        return Path(md_abs).name
    return str(row.get("konspekt_md_label") or row.get("source_label") or "непереносимый источник")


def _heading_ambiguous(md_abs: str, heading_text: str) -> bool:
    """Дубль заголовка в самом ДОКУМЕНТЕ (не только среди собранных rows).

    Дубль опасен, даже когда в корзине лежит лишь одна из копий — якорь всё равно
    откроет первый одноимённый heading файла.
    """
    if not md_abs or not heading_text:
        return False
    try:
        from app.section_index import heading_repeats_in_document

        return heading_repeats_in_document(Path(md_abs), heading_text)
    except Exception:  # noqa: BLE001 - подпись о дублях не должна ломать рендер корзины
        return False


def _row_stale_status(row: dict[str, Any]) -> str | None:
    """Дрейф строки корзины относительно исходного конспекта (корзина хранит снимок).

    ``None`` — источник совпадает; иначе короткая причина для caption. Снимок при этом
    остаётся читаемым/собираемым — это предупреждение, не блокировка.
    """
    if str(row.get("portability_status") or "") == workbench_service.NON_PORTABLE:
        reason = str(row.get("resolve_error") or "источник вне data/").replace("_", " ")
        return f"непереносимый снимок: {reason}"
    md_abs = str(row.get("konspekt_md_abs") or "")
    if not md_abs:
        return None
    path = Path(md_abs)
    if not path.is_file():
        return "исходный файл не найден — используется сохранённый снимок"
    try:
        from app.section_index import _cached_parse_sections

        sections = _cached_parse_sections(path)
    except Exception:  # noqa: BLE001 - проверка дрейфа опциональна, корзина работает без неё
        return None
    for section in sections:
        if section.slug == row.get("slug") and section.line_start == row.get("line_start"):
            if section.text == str(row.get("text") or ""):
                return None
            return "раздел изменился в источнике — в корзине старый снимок"
    row_id = _row_section_id(row)
    if row_id is not None:
        try:
            from app.media_alignment import compute_section_id

            if any(compute_section_id(s) == row_id for s in sections):
                return "раздел переехал в источнике (строки сместились)"
        except Exception:  # noqa: BLE001 - compute_section_id опционален — дрейф не проверяем, корзина работает
            return None
    return "раздел не найден в источнике — возможно, конспект перегенерирован"


def _bulk_heading_normalized(heading: str) -> str:
    return _SLUG_RE.sub(" ", heading.strip().lower()).strip()


def _is_bulk_document_section(section) -> bool:
    if section.level != 2:
        return False
    if not section.text.strip():
        return False
    return _bulk_heading_normalized(section.heading_text) not in {"оглавление", "содержание", "toc"}


def _add_document_sections_to_workbench(
    md_abs: str,
    rows: list[dict[str, Any]],
    state: MutableMapping[str, Any] | None = None,
) -> tuple[int, int]:
    representative = next((row for row in rows if str(row.get("konspekt_md_abs") or "") == md_abs), None)
    if representative is None:
        return 0, 0

    md_path = Path(md_abs)
    source_abs = Path(str(representative.get("source_abs") or md_abs))
    added = duplicates = 0
    for parsed in parse_sections(md_path):
        if not _is_bulk_document_section(parsed):
            continue
        section = IndexedSection(
            heading_text=parsed.heading_text,
            slug=parsed.slug,
            level=parsed.level,
            line_start=parsed.line_start,
            line_end=parsed.line_end,
            text=parsed.text,
            own_text=parsed.own_text,
            source_abs=source_abs,
            konspekt_md_abs=md_path,
            concept=representative.get("concept"),
        )
        if add_section_to_workbench(section, state=state):
            added += 1
        else:
            duplicates += 1
    return added, duplicates


def _render_bulk_document_panel(rows: list[dict[str, Any]]) -> None:
    documents = _unique_document_rows(rows)
    if not documents:
        return

    st.markdown("### 📥 Быстро добавить разделы")
    options = [str(row.get("konspekt_md_abs") or "") for row in documents]
    labels = {path: Path(path).name for path in options}
    selected = st.selectbox(
        "Документ",
        options,
        format_func=lambda path: labels.get(path, path),
        key="living_konspekt_bulk_doc",
    )
    if st.button("➕ Добавить крупные разделы документа", key="living_konspekt_bulk_add", width="stretch"):
        try:
            added, duplicates = _add_document_sections_to_workbench(selected, rows)
        except OSError as exc:
            st.error(f"Не удалось прочитать документ: {format_request_error(exc)}")
            return
        st.toast(
            f"В корзину: +{added}" + (f" · уже было: {duplicates}" if duplicates else ""),
            icon="📚",
        )
        st.rerun()


def _render_collected_sections(rows: list[dict[str, Any]]) -> None:
    from app.obsidian_export import obsidian_uri, vscode_uri

    st.markdown("### Собранные разделы")
    duplicate_keys = _duplicate_heading_keys(rows)
    row_list = list(rows)
    for idx, row in enumerate(row_list):
        md_abs = str(row.get("konspekt_md_abs") or "")
        row_key = str(row.get("row_key") or f"legacy_{idx}")
        line_start = row.get("line_start")
        heading_text = str(row.get("heading_text") or "")
        with st.container(border=True):
            cols = st.columns([5, 1, 1, 1])
            with cols[0]:
                st.markdown(f"**{heading_text or '—'}**")
                st.caption(f"{_row_konspekt_label(row)} · строки {line_start}-{row.get('line_end')}")
                if (md_abs, heading_text) in duplicate_keys or _heading_ambiguous(md_abs, heading_text):
                    st.caption("⚠️ Заголовок повторяется в документе — VS Code точнее для повторяющихся заголовков.")
                stale_status = _row_stale_status(row)
                if stale_status:
                    st.caption(f"🕰 {stale_status}")
                st.write(str(row.get("text") or "")[:400])
                _render_media_panel(row)
            with cols[1]:
                if md_abs:
                    st.link_button(
                        "📄 Открыть",
                        obsidian_uri(Path(md_abs), heading_text=heading_text),
                        width="stretch",
                    )
                    st.link_button(
                        "🖥 VS Code",
                        vscode_uri(Path(md_abs), line=int(line_start) if line_start else None),
                        width="stretch",
                    )
            with cols[2]:
                move_cols = st.columns(2)
                with move_cols[0]:
                    if st.button(
                        "↑",
                        key=f"wb_move_up_{row_key}",
                        disabled=idx == 0,
                        help="Поднять раздел выше",
                        width="stretch",
                    ):
                        move_section_in_workbench(row_key, -1)
                        st.rerun()
                with move_cols[1]:
                    if st.button(
                        "↓",
                        key=f"wb_move_down_{row_key}",
                        disabled=idx >= len(row_list) - 1,
                        help="Опустить раздел ниже",
                        width="stretch",
                    ):
                        move_section_in_workbench(row_key, 1)
                        st.rerun()
            with cols[3]:
                if st.button("🗑 Убрать", key=f"wb_remove_{row_key}", width="stretch"):
                    remove_section_from_workbench(row_key)
                    st.rerun()


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


def _due_by_document(rows: list[dict[str, Any]]) -> list[tuple[str, str, int]]:
    """``[(имя конспекта, source-тег, due), ...]`` по уникальным документам корзины.

    Карточки несут системный тег ``source:<rel>`` (термины из «Живого конспекта»,
    course-генерация) — SM-2 due по этому тегу и есть «состояние памяти» конспекта.
    Недоступная БД → пустой список (панель просто не рисуется).
    """
    from app.term_cards import source_tag_value

    md_paths: list[str] = []
    for row in rows:
        md = str(row.get("konspekt_md_abs") or "")
        if md and md not in md_paths:
            md_paths.append(md)

    out: list[tuple[str, str, int]] = []
    for md in md_paths:
        tag = f"source:{source_tag_value(Path(md))}"
        try:
            from app import user_state

            due = int(user_state.count_due_flashcards(tags=tag))
        except Exception:  # noqa: BLE001 - память опциональна, корзина работает и без БД
            continue
        out.append((Path(md).name, tag, due))
    return out


def _render_memory_panel(rows: list[dict[str, Any]]) -> None:
    """«🧠 Память конспекта» — замыкание петли: конспект → карточки → угасание → возврат.

    Показывает due-карточки, привязанные к конспектам корзины; «Повторить» открывает
    review-очередь Flashcards, скоупнутую тегом ``source:`` именно на этот конспект
    (тег-скоуп — штатный, через ключ ``flashcards_review_session_tags_text``).
    Нет due — панель молчит: ноль шума, пока память не начала угасать.
    """
    entries = [(doc_name, tag, due) for doc_name, tag, due in _due_by_document(rows) if due > 0]
    if not entries:
        return
    st.markdown("### 🧠 Память конспекта")
    st.caption("Карточки из этих конспектов ждут повторения — забытое подсвечивается здесь само.")
    for doc_name, tag, due in entries:
        mem_cols = st.columns([4, 2])
        with mem_cols[0]:
            st.markdown(f"**{doc_name}** — {due} карточк(и) к повторению")
        with mem_cols[1]:
            if st.button("🔁 Повторить", key=f"wb_review_{tag}", width="stretch"):
                from app.ui.flashcards_sections import FC_MAIN_SECTION_REVIEW, pending_section_key
                from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

                # Ключ text_input тег-скоупа в review: установка ДО инстанцирования
                # виджета (следующий прогон) легальна; scope-signature сам сбросит сессию.
                st.session_state["flashcards_review_session_deck_id"] = None
                st.session_state["flashcards_review_deck_sync_pending"] = None
                st.session_state["flashcards_review_session_tags_text"] = tag
                st.session_state["flashcards_review_session_tag_ids"] = [tag]
                st.session_state["flashcards_review_queue"] = []
                st.session_state["flashcards_review_index"] = 0
                st.session_state["flashcards_card_flipped"] = False
                st.session_state["flashcards_review_stats"] = {"again": 0, "hard": 0, "good": 0, "easy": 0}
                st.session_state["flashcards_review_session_status"] = "idle"
                st.session_state["flashcards_review_session_error"] = None
                st.session_state.pop("flashcards_review_session_scope_signature", None)
                st.session_state[pending_section_key()] = FC_MAIN_SECTION_REVIEW
                st.session_state[PENDING_CURRENT_VIEW_KEY] = "Flashcards"
                try:
                    from app.ui_events import track_event

                    track_event("living_konspekt_review_loop_opened", {"due": due})
                except Exception:  # noqa: BLE001 - аналитика не должна ломать переход к повторению
                    pass
                st.rerun()


def _render_term_cards_panel(rows: list[dict[str, Any]]) -> None:
    """Карточки из сохранённых разделов «Важные термины» без нового LLM-вызова.

    Переиспользует preview редактор Flashcards (те же ``fc_preview_*`` session_state
    ключи, что заполняет ``render_generate``): редактирование/удаление/сохранение —
    уже готовый UI, не дублируем.
    """
    from app.term_cards import term_cards_from_documents

    st.markdown("### 🃏 Карточки из терминов лекции (без LLM)")
    md_paths = list(dict.fromkeys(str(row.get("konspekt_md_abs") or "") for row in rows if row.get("konspekt_md_abs")))
    cards, source_docs = term_cards_from_documents(md_paths)
    if not cards:
        st.caption(
            "В конспектах собранных разделов нет раздела «🧠 Важные термины и концепции» — "
            "карточки собрать не из чего."
        )
        return
    deck_title = f"Термины — {', '.join(source_docs)}"[:120]
    st.caption(
        f"Найдено {len(cards)} терминов с определениями в {len(source_docs)} конспект(ах): "
        + ", ".join(source_docs)
        + ". Карточки собираются без нового LLM-вызова: front/back берутся из уже сохранённого конспекта."
    )
    if len(cards) < 5:
        st.caption(
            f"Для сохранения колоды нужно минимум 5 карточек, сейчас найдено {len(cards)}. "
            "Добавьте в корзину разделы из других конспектов с терминами."
        )
        return
    if st.button("🃏 Создать карточки из терминов", key="wb_term_cards_btn", type="primary"):
        from app.ui.flashcards_sections import FC_MAIN_SECTION_CREATE, pending_section_key
        from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

        _clear_flashcards_preview_widget_state()
        st.session_state["fc_preview_cards"] = cards
        st.session_state["fc_preview_title"] = deck_title
        st.session_state["fc_deck_name"] = deck_title
        st.session_state["fc_preview_source_type"] = "living_konspekt_terms"
        st.session_state["fc_preview_source_identifier"] = ", ".join(source_docs)
        st.session_state[pending_section_key()] = FC_MAIN_SECTION_CREATE
        # PENDING_CURRENT_VIEW_KEY, не прямая запись: current_view — ключ уже
        # инстанцированного st.selectbox в main.py на этом прогоне.
        st.session_state[PENDING_CURRENT_VIEW_KEY] = "Flashcards"
        try:
            from app.ui_events import track_event

            track_event("living_konspekt_term_cards_created", {"cards": len(cards)})
        except Exception:  # noqa: BLE001 - аналитика не должна ломать создание карточек
            pass
        st.rerun()


def _clear_flashcards_preview_widget_state() -> None:
    """Drop stale preview editor widget values before opening Flashcards create."""
    stale_prefixes = ("prev_f_", "prev_b_", "prev_t_")
    for key in list(st.session_state.keys()):
        if key == "fc_deck_name" or (isinstance(key, str) and key.startswith(stale_prefixes)):
            st.session_state.pop(key, None)


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
        _render_bulk_document_panel(rows)
        _render_collected_sections(rows)
    with tab_reader:
        render_reader(rows, media_renderer=_render_media_panel)
    with tab_memory:
        _render_memory_panel(rows)
        _render_term_cards_panel(rows)
    with tab_export:
        _render_build_panel(rows)
    with tab_next:
        render_web_queries_panel(rows)
        st.divider()
        render_deep_study_panel(rows)
