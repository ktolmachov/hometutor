"""Правая колонка вкладки «Темы»: действия, документы, подвкладки (P5c split)."""

from __future__ import annotations

import streamlit as st

from app import user_state
from app.ui.helpers import format_request_error
from app.ui.quiz_learning_mode_widgets import (
    render_scoped_quiz_learning_mode_select,
    scoped_quiz_learning_mode_value,
)
from app.ui.continuity_bridge import restore_course_cta_ru
from app.ui.study_scope import (
    activate_scope,
    deactivate_scope,
    folder_rel_from_paths,
    get_active_scope,
    get_last_deactivated_scope,
    restore_scope,
)
from app.ui_client import fetch_json, post_knowledge_workflow


def _folder_source_paths_from_index(folder_rel: str, index_stats: dict | None) -> list[str]:
    """Return all indexed paths for folder_rel from index_stats (no disk scan)."""
    if not index_stats or not folder_rel:
        return []
    normalized = str(folder_rel or "").strip().replace("\\", "/")
    prefix_slash = f"{normalized}/"
    prefix_backslash = f"{normalized}\\"
    return [
        str(p).strip()
        for p in index_stats.get("files") or []
        if str(p).strip() and (
            str(p).strip() == normalized
            or str(p).strip().startswith(prefix_slash)
            or str(p).strip().startswith(prefix_backslash)
        )
    ]


def _render_activate_course_row(
    topic: dict, document_options: list[str], index_stats: dict | None = None
) -> None:
    """Кнопка «Активировать как курс» под action_row (Package AB / US-16.0)."""
    folder_rel = folder_rel_from_paths(document_options)
    if not folder_rel:
        return
    # Use full folder paths from index to avoid scoping to a single topic's docs
    folder_source_paths = _folder_source_paths_from_index(folder_rel, index_stats) or document_options
    active = get_active_scope()
    is_active = bool(active and active.get("folder_rel") == folder_rel)
    last_scope = get_last_deactivated_scope()
    is_restorable = bool(
        not is_active
        and last_scope
        and last_scope.get("folder_rel") == folder_rel
    )
    act_cols = st.columns([2, 1])
    with act_cols[0]:
        if is_active:
            st.caption(f"✅ Активный курс: **{folder_rel}** — все запросы фильтруются по этой папке")
        elif is_restorable:
            course_title = str(last_scope.get("title") or topic.get("topic_name") or folder_rel)
            st.caption(f"↩ Недавно деактивирован: **{folder_rel}**")
            if st.button(
                restore_course_cta_ru(course_title),
                key=f"restore_course_{topic.get('topic_id', 'none')}",
                width="stretch",
                type="secondary",
            ):
                restore_scope()
                st.rerun()
        else:
            course_title = f"Курс: {topic.get('topic_name', folder_rel)}"
            if st.button(
                f"📚 Активировать как курс: {folder_rel}",
                key=f"activate_course_{topic.get('topic_id', 'none')}",
                width="stretch",
                type="secondary",
            ):
                activate_scope(
                    folder_rel=folder_rel,
                    title=course_title,
                    source_paths=folder_source_paths,
                )
                st.rerun()
    with act_cols[1]:
        if is_active:
            if st.button("× Деактивировать", key=f"deactivate_course_{topic.get('topic_id', 'none')}", width="stretch", type="secondary"):
                deactivate_scope()
                st.rerun()


def render_topics_right_column(
    *,
    selected_topic: dict,
    topic_states: dict,
    iv: str | None,
    index_stats: dict | None = None,
) -> list[str]:
    st.subheader(selected_topic["topic_name"])
    st.caption("Сначала посмотрите состав темы целиком, а затем сужайте документы только если нужен более точный конспект или план.")
    tid = selected_topic["topic_id"]
    trid = user_state.topic_resource_id(tid)
    bm = bool(topic_states.get(tid, {}).get("bookmarked"))
    track_cols = st.columns([1, 1, 2])
    with track_cols[0]:
        if st.button(
            "Снять закладку" if bm else "Закладка на тему",
            key=f"topic_bm_{tid}",
            width="stretch",
            type="secondary",
        ):
            try:
                user_state.toggle_bookmark("topic", trid)
            except Exception as _exc:  # noqa: BLE001
                import logging  # noqa: BLE001

                logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                pass
            st.rerun()
    with track_cols[1]:
        cur_p = topic_states.get(tid, {}).get("progress")
        st.caption(f"Прогресс: {round(float(cur_p) * 100)}%" if cur_p is not None else "Прогресс не задан")
    with track_cols[2]:
        slider_val = st.slider(
            "Прогресс по теме",
            0.0,
            1.0,
            value=float(cur_p) if cur_p is not None else 0.0,
            step=0.05,
            key=f"topic_track_slider_{tid}",
            help="Сохраняется локально для трекинга изучения.",
        )
        if st.button("Записать прогресс", key=f"topic_track_save_{tid}", width="stretch"):
            try:
                user_state.upsert_reading_status(
                    resource_type="topic",
                    resource_id=trid,
                    progress=slider_val,
                    display_title=f"Тема «{selected_topic['topic_name']}»",
                    index_version=iv or None,
                )
            except Exception as exc:  # noqa: BLE001 - user progress save failure is UI-reportable
                st.error(str(exc))
            else:
                st.success("Прогресс сохранён")
                st.rerun()
    documents = selected_topic.get("documents", [])
    document_options = [doc.get("relative_path") or doc.get("file_name") or "document" for doc in documents]
    doc_filter = st.text_input(
        "Фильтр документов внутри темы",
        placeholder="Введите часть имени файла или пути",
        key=f"doc_filter_{selected_topic['topic_id']}",
    ).strip().lower()
    visible_document_options = [item for item in document_options if not doc_filter or doc_filter in item.lower()]
    selection_key = f"topic_docs_{selected_topic['topic_id']}"
    active_document_options = visible_document_options if visible_document_options else document_options
    if selection_key in st.session_state:
        st.session_state[selection_key] = [doc for doc in st.session_state[selection_key] if doc in active_document_options]
        multiselect_kwargs = {}
    else:
        multiselect_kwargs = {"default": list(active_document_options)}
    selected_documents = st.multiselect(
        "Документы для выборочного synthesis",
        options=active_document_options,
        key=selection_key,
        help="По умолчанию выбраны все документы темы. Уберите лишние, если хотите сделать более точный synthesis.",
        **multiselect_kwargs,
    )
    action_row = st.columns(4)
    with action_row[0]:
        if st.button("Собрать по всей теме", key=f"synth_all_{selected_topic['topic_id']}", width="stretch", type="primary"):
            trace_all = {
                "topic_id": selected_topic["topic_id"],
                "topic_name": selected_topic["topic_name"],
                "working_set_paths": list(document_options),
                "synthesis_launch_method": "by_topic",
                "documents_used_count": len(document_options),
                "selection_manually_adjusted": False,
            }
            post_knowledge_workflow("topics_synthesis_start", trace_all)
            try:
                # topic_id alone fails with Unknown topic_id if UI catalog and API diverge;
                # documents + topic pin retrieval to the visible working set (same as by_selection).
                result = fetch_json(
                    "POST",
                    "/synthesize",
                    timeout=120,
                    json={
                        "topic": selected_topic["topic_name"],
                        "topic_id": selected_topic["topic_id"],
                        "documents": list(document_options),
                    },
                )
                result["selection_mode"] = "topic"
                st.session_state["last_synthesis"] = result
                used = len(result.get("documents") or document_options)
                post_knowledge_workflow(
                    "topics_synthesis_complete",
                    {**trace_all, "documents_used_count": used},
                )
            except Exception as e:  # noqa: BLE001 - synthesis failure is caught and reported to the user
                post_knowledge_workflow("topics_synthesis_failed", trace_all)
                st.error(f"Ошибка synthesis: {format_request_error(e)}")
    with action_row[1]:
        if st.button("Собрать по выборке", key=f"synth_selected_{selected_topic['topic_id']}", width="stretch", type="secondary"):
            if not selected_documents:
                st.warning("Сначала выберите хотя бы один документ в левой колонке, чтобы собрать конспект по выборке.")
            else:
                manual_sel = sorted(set(selected_documents)) != sorted(set(document_options))
                trace_sel = {
                    "topic_id": selected_topic["topic_id"],
                    "topic_name": selected_topic["topic_name"],
                    "working_set_paths": list(selected_documents),
                    "synthesis_launch_method": "by_selection",
                    "documents_used_count": len(selected_documents),
                    "selection_manually_adjusted": manual_sel,
                }
                post_knowledge_workflow("topics_synthesis_start", trace_sel)
                try:
                    result = fetch_json(
                        "POST",
                        "/synthesize",
                        timeout=120,
                        json={
                            "topic": selected_topic["topic_name"],
                            "topic_id": selected_topic["topic_id"],
                            "documents": selected_documents,
                        },
                    )
                    result["selection_mode"] = "selected_documents"
                    result["selected_documents"] = selected_documents
                    st.session_state["last_synthesis"] = result
                    used = len(result.get("documents") or selected_documents)
                    post_knowledge_workflow(
                        "topics_synthesis_complete",
                        {**trace_sel, "documents_used_count": used},
                    )
                except Exception as e:  # noqa: BLE001 - synthesis selection failure is reported to the user
                    post_knowledge_workflow("topics_synthesis_failed", trace_sel)
                    st.error(f"Ошибка synthesis: {format_request_error(e)}")
    with action_row[2]:
        if st.button("Выбрать все", key=f"select_all_{selected_topic['topic_id']}", width="stretch", type="secondary"):
            st.session_state[selection_key] = list(document_options)
            st.rerun()
    with action_row[3]:
        if st.button("Очистить", key=f"clear_all_{selected_topic['topic_id']}", width="stretch", type="secondary"):
            st.session_state[selection_key] = []
            st.rerun()
    _render_activate_course_row(selected_topic, document_options, index_stats)
    tid_cur = selected_topic["topic_id"]
    tqlm_key = f"topic_scope_quiz_lm_{tid_cur}"
    render_scoped_quiz_learning_mode_select(session_key=tqlm_key)
    topic_lm = scoped_quiz_learning_mode_value(tqlm_key)
    if st.button(
        "Тест по всей теме",
        key=f"topic_quiz_all_{tid_cur}",
        width="stretch",
        type="primary",
    ):
        try:
            data = fetch_json(
                "POST",
                "/quiz/generate",
                timeout=120,
                json={
                    "scope": "topic",
                    "identifier": tid_cur,
                    "num_questions": 6,
                    "difficulty": "adaptive",
                    "learning_mode": topic_lm,
                    "documents": list(document_options),
                },
            )
            st.session_state[f"topic_scope_quiz_{tid_cur}"] = data.get("quiz") or {}
            st.session_state.pop(f"topic_scope_quiz_err_{tid_cur}", None)
        except Exception as e:  # noqa: BLE001 - quiz generation failure is caught and reported
            st.session_state[f"topic_scope_quiz_err_{tid_cur}"] = format_request_error(e)
        st.rerun()
    with st.expander("Документы в теме", expanded=False):
        st.markdown("#### Документы в теме")
        st.caption(
            "📥 «Подготовить для Obsidian» конвертирует документ в красиво "
            "отформатированный Markdown-конспект (txt — через локальную LLM) и "
            "кладёт его в `data/vault/`. После этого в графе знаний работает кнопка 🔮 Obsidian."
        )
        _render_obsidian_batch_button(documents, key=f"obs_batch_{tid_cur}")
        st.divider()
        for idx, doc in enumerate(documents):
            title = doc.get("relative_path") or doc.get("file_name") or "document"
            if doc_filter and doc_filter not in title.lower():
                continue
            vault_badge = _vault_status_badge(title)
            st.markdown(
                f"""
                <div class="doc-card">
                    <div class="doc-path">{title} {vault_badge}</div>
                    <div class="doc-meta">{doc.get('doc_type') or 'document'} | {doc.get('difficulty') or 'n/a'}</div>
                    <div>{(doc.get('summary') or 'Нет summary для документа.')[:260]}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            _render_konspekt_badge(title, key_prefix=f"km_{tid_cur}_{idx}")
            col_exp, col_read = st.columns([2, 1])
            with col_exp:
                _render_obsidian_export_button(title, key=f"obs_export_{tid_cur}_{idx}")
            with col_read:
                _render_obsidian_read_button(title, key=f"obs_read_{tid_cur}_{idx}")
            _render_obsidian_reader_panel(title, key=f"obs_read_{tid_cur}_{idx}")
    return list(selected_documents)


def topic_scope_quiz_session_key(topic_id: str) -> str:
    return f"topic_scope_quiz_{topic_id}"


def topic_scope_quiz_is_active(selected_topic: dict) -> bool:
    tid = str(selected_topic.get("topic_id") or "").strip()
    if not tid:
        return False
    tdata = st.session_state.get(topic_scope_quiz_session_key(tid))
    return isinstance(tdata, dict) and bool(tdata.get("questions"))


def render_topic_scope_quiz_panel(selected_topic: dict) -> None:
    """Полноширинная панель сгенерированного теста по теме."""
    tid_cur = selected_topic["topic_id"]
    terr = st.session_state.pop(f"topic_scope_quiz_err_{tid_cur}", None)
    if terr:
        st.error(terr)
    tdata = st.session_state.get(topic_scope_quiz_session_key(tid_cur))
    if not isinstance(tdata, dict) or not tdata.get("questions"):
        return
    from app.ui.scoped_quiz import render_scoped_self_check_quiz

    with st.expander("Сгенерированный тест по теме", expanded=True):
        st.caption(f"Вопросов: {len(tdata['questions'])} · {selected_topic.get('topic_name', '')}")
        render_scoped_self_check_quiz(
            tdata["questions"],
            source_key=topic_scope_quiz_session_key(tid_cur),
            quiz_meta=tdata,
        )


def _render_konspekt_badge(rel_path: str, *, key_prefix: str) -> None:
    """Показать badge «конспект готов» и кнопку скачать, если конспект найден."""
    try:
        from app.konspekt_discovery import find_konspekt_for_source_in_data
        km = find_konspekt_for_source_in_data(rel_path)
    except Exception:  # noqa: BLE001 — konspekt discovery failure must not crash document list rendering
        return
    if km is None:
        return
    date_str = f" · {km.generated}" if km.generated else ""
    badge = f"✅ конспект готов{date_str}"
    try:
        # A1: rubric badge next to konspekt (konspekt_quality_plan)
        from app.konspekt_discovery import get_konspekt_quality_rubric
        r = get_konspekt_quality_rubric(km.path)
        if r and r.get("average") is not None:
            badge += f" · рубрика {r['average']}/5"
    except Exception:  # noqa: BLE001
        pass
    try:
        # C1: grade badge (derived from roles, same places as A1)
        from app.section_index import _cached_parse_sections, get_konspekt_grade
        secs = _cached_parse_sections(km.path)
        grade = get_konspekt_grade(secs)
        if grade != "базовый":
            badge += f" · {grade}"
    except Exception:  # noqa: BLE001
        pass
    st.markdown(
        f'<div style="font-size:12px;color:#4ade80;margin:2px 0 4px">{badge}</div>',
        unsafe_allow_html=True,
    )
    try:
        content = km.path.read_bytes()
        st.download_button(
            label="⬇ Скачать конспект",
            data=content,
            file_name=km.path.name,
            mime="text/markdown",
            key=f"{key_prefix}_dl",
        )
    except OSError:
        pass


def _render_obsidian_export_button(rel_path: str, *, key: str) -> None:
    """Кнопка ленивой конвертации документа в Obsidian-ready Markdown."""
    if not st.button("📥 Подготовить для Obsidian", key=key, help=rel_path):
        return
    try:
        from app.obsidian_export import to_obsidian_markdown, vault_target, resolve_source

        src = resolve_source(rel_path)
        if src is not None and vault_target(src).exists():
            st.info("Уже подготовлено — пересоздаю с нуля.")

        progress = st.progress(0.0, text="Готовлю…")
        stage_labels = {"map": "Читаю фрагменты", "merge": "Свожу тезисы", "compose": "Собираю конспект"}

        def _on_progress(stage: str, cur: int, total: int) -> None:
            frac = cur / total if total else 0.0
            base = {"map": 0.0, "merge": 0.5, "compose": 0.9}.get(stage, 0.0)
            span = {"map": 0.5, "merge": 0.4, "compose": 0.1}.get(stage, 1.0)
            progress.progress(min(base + span * frac, 1.0), text=f"{stage_labels.get(stage, stage)} ({cur}/{total})")

        result = to_obsidian_markdown(rel_path, force=True, progress=_on_progress)
        progress.progress(1.0, text="Готово")
        verb = {"converted": "сконвертирован", "copied": "скопирован", "cached": "взят из кэша", "skipped-empty": "пуст"}
        st.success(f"✅ Документ {verb.get(result.action, result.action)}: `{result.vault_rel}`")
        st.caption(f"Файл: `{result.target_abs}`")
    except Exception as exc:  # noqa: BLE001 - показать пользователю причину
        progress.progress(0.0, text="Ошибка")
        st.error(f"❌ Не удалось подготовить документ: {format_request_error(exc)}")
        st.caption("Нажмите кнопку ещё раз — map/merge фазы будут пропущены после реализации partial resume.")


def _vault_status_badge(rel_path: str) -> str:
    """Вернуть HTML-бейдж статуса конспекта в vault: ✅ готов / 📝 нет. + A1 rubric."""
    try:
        from app.obsidian_export import obsidian_uri, resolve_source, vault_target
        from app.konspekt_discovery import find_konspekt_for_source_in_data, get_konspekt_quality_rubric
        src = resolve_source(rel_path)
        if src is not None and vault_target(src).exists():
            uri = obsidian_uri(vault_target(src))
            badge = f'<a href="{uri}" title="Открыть конспект в Obsidian" style="color:#4ade80;font-size:13px;text-decoration:none">✅</a>'
            # A1: rubric рядом с ✅ (plan)
            try:
                km = find_konspekt_for_source_in_data(rel_path)
                if km:
                    r = get_konspekt_quality_rubric(km.path)
                    if r and r.get("average") is not None:
                        badge += f' <span style="font-size:11px;color:#64748b">рубрика {r["average"]}/5</span>'
            except Exception:
                pass
            return badge
        if src is not None and src.suffix.lower() == ".txt":
            return '<span title="txt без конспекта — нажмите Подготовить" style="color:#94a3b8;font-size:11px">📝 txt</span>'
    except Exception:  # noqa: BLE001 — vault badge lookup failure must return empty string, not crash the doc card
        pass
    return ""


def _render_obsidian_read_button(rel_path: str, *, key: str) -> None:
    """Кнопка «👁 Читать» — toggles готовый конспект; panel renders full-width."""
    try:
        from app.obsidian_export import resolve_source, vault_target
        src = resolve_source(rel_path)
        md_path = vault_target(src) if src is not None else None
        has_md = md_path is not None and md_path.exists()
    except Exception:  # noqa: BLE001 — vault path resolution failure degrades to disabled read button, not crash
        has_md = False
        md_path = None

    toggle_key = f"{key}_open"
    if not has_md:
        st.button("👁 Читать", key=key, disabled=True, help="Сначала подготовьте документ для Obsidian")
        return

    is_open = st.session_state.get(toggle_key, False)
    label = "✕ Закрыть" if is_open else "👁 Читать"
    if st.button(label, key=key):
        st.session_state[toggle_key] = not is_open
        st.rerun()


def _render_obsidian_reader_panel(rel_path: str, *, key: str) -> None:
    """Full-width reader panel for an opened Obsidian-ready Markdown note."""
    toggle_key = f"{key}_open"
    if not st.session_state.get(toggle_key):
        return
    try:
        from app.obsidian_export import resolve_source, vault_target
        src = resolve_source(rel_path)
        md_path = vault_target(src) if src is not None else None
    except Exception:  # noqa: BLE001 — vault lookup failure is shown as unavailable reader, not a crash
        md_path = None

    if st.session_state.get(toggle_key) and md_path is not None:
        try:
            text = md_path.read_text(encoding="utf-8")
            # Убираем YAML-frontmatter из отображения
            if text.startswith("---"):
                end = text.find("\n---", 4)
                if end != -1:
                    text = text[end + 4:].lstrip("\n")
            with st.container(border=True):
                st.markdown(text, unsafe_allow_html=False)
        except Exception as exc:  # noqa: BLE001 — konspekt read failure shown to user, must not crash the whole panel
            st.error(f"Не удалось прочитать конспект: {exc}")
    else:
        st.warning("Конспект недоступен. Подготовьте документ для Obsidian ещё раз.")

def _render_obsidian_batch_button(documents: list[dict], *, key: str) -> None:
    """Батч-кнопка «Подготовить ВСЕ документы темы для Obsidian»."""
    if not documents:
        return
    paths = [doc.get("relative_path") or doc.get("file_name") or "" for doc in documents]
    paths = [p for p in paths if p]
    if not paths:
        return

    col1, col2 = st.columns([3, 1])
    with col1:
        label = f"📥 Подготовить все {len(paths)} документа(ов) темы для Obsidian"
        run_batch = st.button(label, key=key, help="Конвертирует каждый документ по очереди (txt → конспект LLM).")
    with col2:
        force_batch = st.checkbox("Пересоздать", key=f"{key}_force", help="Перегнать даже уже готовые.")

    if not run_batch:
        return

    try:
        from app.obsidian_export import to_obsidian_markdown, resolve_source, vault_target
    except ImportError as exc:
        st.error(f"Не удалось загрузить модуль экспорта: {exc}")
        return

    status_area = st.empty()
    overall = st.progress(0.0, text="Инициализация…")

    results: list[dict] = []
    for doc_idx, rel_path in enumerate(paths):
        doc_label = rel_path.split("/")[-1]
        overall.progress(doc_idx / len(paths), text=f"[{doc_idx + 1}/{len(paths)}] {doc_label}")
        status_area.info(f"🔄 Обрабатываю: `{doc_label}`")

        try:
            src = resolve_source(rel_path)
            cached = (src is not None and vault_target(src).exists()) and not force_batch

            if cached:
                results.append({"path": rel_path, "action": "cached", "ok": True})
                continue

            doc_progress = st.progress(0.0, text=f"{doc_label}: старт…")
            stage_labels = {"map": "Читаю", "merge": "Свожу", "compose": "Собираю"}

            def _on_progress(stage: str, cur: int, total: int, _bar=doc_progress, _lbl=doc_label) -> None:
                frac = cur / total if total else 0.0
                base = {"map": 0.0, "merge": 0.5, "compose": 0.9}.get(stage, 0.0)
                span = {"map": 0.5, "merge": 0.4, "compose": 0.1}.get(stage, 1.0)
                _bar.progress(min(base + span * frac, 1.0), text=f"{_lbl}: {stage_labels.get(stage, stage)} ({cur}/{total})")

            result = to_obsidian_markdown(rel_path, force=force_batch, progress=_on_progress)
            doc_progress.progress(1.0, text=f"{doc_label}: ✅")
            results.append({"path": rel_path, "action": result.action, "vault_rel": result.vault_rel, "ok": True})
        except Exception as exc:  # noqa: BLE001
            doc_progress.progress(0.0, text=f"{doc_label}: ❌ {type(exc).__name__}")
            results.append({"path": rel_path, "action": "error", "error": str(exc), "ok": False})

    overall.progress(1.0, text="Готово")
    status_area.empty()

    ok = [r for r in results if r["ok"] and r["action"] != "cached"]
    cached = [r for r in results if r["ok"] and r["action"] == "cached"]
    errors = [r for r in results if not r["ok"]]

    verb = {"converted": "сконвертирован", "copied": "скопирован"}
    summary_lines = [f"### Итог батч-конвертации для Obsidian"]
    if ok:
        summary_lines.append(f"✅ Обработано: **{len(ok)}**")
        for r in ok:
            summary_lines.append(f"  - {r.get('vault_rel') or r['path']} ({verb.get(r['action'], r['action'])})")
    if cached:
        summary_lines.append(f"⏩ Без изменений (из кэша): **{len(cached)}**")
    if errors:
        summary_lines.append(f"❌ Ошибок: **{len(errors)}**")
        for r in errors:
            summary_lines.append(f"  - `{r['path']}`: {r.get('error', '?')}")
    st.markdown("\n".join(summary_lines))


def render_obsidian_course_batch(
    topics: list[dict], *, key: str, skip_with_konspekt: bool = True
) -> None:
    """Батч-конвертация всех документов всех тем курса (вызывается из topics_tab)."""
    all_paths: list[str] = []
    seen: set[str] = set()
    for topic in topics:
        for doc in topic.get("documents") or []:
            p = doc.get("relative_path") or doc.get("file_name") or ""
            if p and p not in seen:
                seen.add(p)
                all_paths.append(p)

    if not all_paths:
        st.info("Нет документов в каталоге тем.")
        return

    if skip_with_konspekt:
        try:
            from app.konspekt_discovery import find_konspekt_for_source_in_data
            covered = [p for p in all_paths if find_konspekt_for_source_in_data(p) is not None]
            pending = [p for p in all_paths if p not in set(covered)]
        except Exception:  # noqa: BLE001 — coverage scan failure degrades to processing all docs, not crash
            covered, pending = [], all_paths
    else:
        covered, pending = [], all_paths

    if covered:
        st.info(
            f"✅ **{len(covered)}** из **{len(all_paths)}** документов уже имеют конспект — "
            f"будет обработано **{len(pending)}**."
        )
    if not pending:
        return

    all_docs = [{"relative_path": p} for p in pending]
    _render_obsidian_batch_button(all_docs, key=key)
