"""Боковая панель Streamlit: метрики, навигация, индекс, фильтры Q&A, сессии."""
from __future__ import annotations

import json
import uuid
from typing import Any

import streamlit as st

from app import user_state
from app.config import get_settings
from app.course_cache import load_course_artifact, normalize_source_paths
from app.course_folder_filter import is_user_course_folder_rel
from app.ui_preferences import feature_visible_by_id, get_overrides, get_ui_level, feature_visible
from app.ui.auth_gate import render_account_status_sidebar
from app.ui.constants import _SIDEBAR_FILTER_FOLDER_ALL, _SIDEBAR_FILTER_TOPIC_ALL
from app.ui.continuity_bridge import (
    expert_controls_expander_label_ru,
    expert_controls_sidebar_blurb_ru,
    sidebar_fast_filters_caption_ru,
    sidebar_focus_view_help_ru,
    restore_course_cta_ru,
    sync_transfer_sidebar_expander_label_ru,
    sync_transfer_sidebar_intro_caption_ru,
)
from app.ui.index_labels import index_version_label
from app.ui.study_scope import deactivate_scope as _deactivate_scope
from app.ui.study_scope import get_active_scope as _get_active_scope
from app.ui.study_scope import get_last_deactivated_scope as _get_last_deactivated_scope
from app.ui.study_scope import restore_scope as _restore_scope
from app.ui.topics_catalog import load_topics_catalog
from app.ui.widgets import render_panel_header
from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

_RESTORE_PREVIEW_KEYS: dict[str, tuple[str, ...]] = {
    "profiles": ("learner_profile_snapshots", "learner_profile_migration_log"),
    "decks": ("flashcard_decks",),
    "cards": ("flashcards",),
    "reviews": ("spaced_repetition",),
}


def _view_visible(target_view: str) -> bool:
    from app.ui.feature_registry import feature_for_view

    spec = feature_for_view(target_view)
    if spec is None:
        return True
    return feature_visible(spec, level=get_ui_level(), overrides=get_overrides())


def open_mnemo_polis(*, state: Any | None = None, return_from: str | None = None) -> None:
    """W4a: deep link «В Мнемополис» → Knowledge Graph (delegates to mnemo_nav)."""
    from app.ui.mnemo_nav import open_mnemo_polis as _open

    _open(state=state, return_from=return_from)


def _restore_preview_entity_rows(preview: dict) -> dict[str, int]:
    counts = preview.get("table_row_counts") if isinstance(preview, dict) else {}
    if not isinstance(counts, dict):
        counts = {}
    out: dict[str, int] = {}
    for label, keys in _RESTORE_PREVIEW_KEYS.items():
        out[label] = sum(int(counts.get(table) or 0) for table in keys)
    return out


def _restore_result_summary(result: dict) -> str:
    rows = int((result or {}).get("rows_inserted") or 0)
    ver = int((result or {}).get("sync_version") or 0)
    return f"Снимок применён: импортировано {rows} строк (sync_version={ver})."


def collect_topic_document_selections() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for k in st.session_state.keys():
        if isinstance(k, str) and k.startswith("topic_docs_"):
            tid = k[len("topic_docs_") :]
            val = st.session_state[k]
            if isinstance(val, list):
                out[tid] = [str(x) for x in val]
    return out


def clear_quiz_widget_state() -> None:
    for k in list(st.session_state.keys()):
        if not isinstance(k, str):
            continue
        if k.startswith("quiz_data_") or k.startswith("quiz_q_") or k.startswith("quiz_gen_"):
            try:
                del st.session_state[k]
            except Exception as _exc:  # noqa: BLE001
                import logging  # noqa: BLE001
                logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                pass


def apply_research_payload(payload: dict) -> None:
    """Restore UI snapshot from `user_state.normalize_research_payload`."""
    if not payload:
        return
    st.session_state["current_view"] = payload.get("current_view") or "Быстрый ответ"
    st.session_state["active_topic_id"] = payload.get("active_topic_id")
    st.session_state["last_studied_document"] = payload.get("last_studied_document")
    st.session_state["last_answer"] = payload.get("last_answer")
    st.session_state["last_synthesis"] = payload.get("last_synthesis")
    st.session_state["last_learning_plan"] = payload.get("last_learning_plan")
    st.session_state["history"] = payload.get("history") or []
    st.session_state["question_draft"] = payload.get("question_draft") or ""
    st.session_state["last_debug"] = None
    st.session_state.pop("topics_catalog", None)
    clear_quiz_widget_state()
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("topic_docs_"):
            try:
                del st.session_state[k]
            except Exception as _exc:  # noqa: BLE001
                import logging  # noqa: BLE001
                logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                pass
    for tid, paths in (payload.get("topic_document_selections") or {}).items():
        if isinstance(paths, list):
            st.session_state[f"topic_docs_{tid}"] = [str(x) for x in paths]
    workbench_sections = payload.get("workbench_sections")
    restored_rows = list(workbench_sections) if isinstance(workbench_sections, list) else []
    try:
        # workbench_service: session_state + авто-персист в app_kv (restore перезаписывает профиль).
        from app import workbench_service

        runtime_rows = workbench_service.normalize_runtime_rows(restored_rows)
        st.session_state[workbench_service.WORKBENCH_SECTIONS_KEY] = runtime_rows
        workbench_service.save_rows(runtime_rows)
    except Exception:  # noqa: BLE001 - restore не должен падать из-за авто-персиста
        st.session_state["workbench_sections"] = restored_rows


def render_reading_mode_toggle(*, key: str, help_text: str | None = None) -> None:
    st.toggle(
        "Reading mode",
        key=key,
        help=help_text or "Сужает длину строки и делает длинные ответы удобнее для спокойного чтения.",
    )


def render_focus_view_toggle(*, key: str, help_text: str | None = None) -> None:
    st.toggle(
        "Focus view",
        key=key,
        help=help_text or "Скрывает второстепенные панели рядом с длинным материалом, чтобы сосредоточиться на чтении.",
    )


def render_sidebar_notes_panel() -> None:
    with st.expander("Мои заметки", expanded=False):
        try:
            items = user_state.list_annotations(limit=30)
        except Exception as exc:  # noqa: BLE001 - robust UI load, fallback if table is locked or missing
            st.caption(f"Не удалось загрузить заметки: {exc}")
            return
        if not items:
            st.caption("Закладок и заметок пока нет.")
            return
        for row in items:
            lab = user_state.format_resource_label(row["resource_type"], row["resource_id"])
            prefix = "Закладка" if row["kind"] == "bookmark" else "Заметка"
            st.markdown(f"**{prefix}** · {lab}")
            if row["kind"] == "note" and row.get("body"):
                st.caption((row["body"] or "")[:400])
            if st.button("Удалить", key=f"ann_del_{row['id']}", width='stretch'):
                try:
                    user_state.delete_annotation(int(row["id"]))
                except Exception as _exc:  # noqa: BLE001
                    import logging  # noqa: BLE001
                    logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                    pass
                st.rerun()


def render_sidebar_research_sessions(index_stats: dict | None) -> None:
    iv = index_version_label(index_stats)
    with st.expander("Исследования", expanded=False):
        if st.session_state.pop("_research_stale_banner", None):
            st.warning(
                "Индекс менялся после сохранения этой сессии — перепроверьте источники и при необходимости заново соберите synthesis или программу."
            )
        name = st.text_input(
            "Имя сессии",
            key="research_session_name_input",
            placeholder="Например: RAG — неделя 1",
        )
        if st.button("Сохранить текущее состояние", key="research_session_save", width='stretch'):
            label = (name or "").strip()
            if not label:
                st.warning("Введите имя сессии.")
            else:
                try:
                    from app import workbench_service

                    payload = user_state.normalize_research_payload(
                        current_view=str(st.session_state.get("current_view") or "Быстрый ответ"),
                        active_topic_id=st.session_state.get("active_topic_id"),
                        last_studied_document=st.session_state.get("last_studied_document"),
                        last_answer=st.session_state.get("last_answer"),
                        last_synthesis=st.session_state.get("last_synthesis"),
                        last_learning_plan=st.session_state.get("last_learning_plan"),
                        history=list(st.session_state.get("history") or []),
                        question_draft=str(st.session_state.get("question_draft") or ""),
                        topic_document_selections=collect_topic_document_selections(),
                        workbench_sections=workbench_service.persisted_rows_from_runtime(
                            list(st.session_state.get("workbench_sections") or [])
                        ),
                    )
                    user_state.save_research_session(label, payload, index_version=iv or None)
                except Exception as exc:  # noqa: BLE001 - user session save failure is UI-reportable
                    st.error(f"Не удалось сохранить: {exc}")
                else:
                    st.success("Сессия сохранена.")
                    st.rerun()
        try:
            rows = user_state.list_research_sessions(limit=25, current_index_version=iv or None)
        except Exception as exc:  # noqa: BLE001 - robust UI list, fallback if database fails
            st.caption(f"Список сессий недоступен: {exc}")
            return
        if not rows:
            st.caption("Сохранённые исследования появятся здесь.")
            return
        st.caption("Сохранённые сессии")
        for row in rows:
            sid = int(row["id"])
            stale = row.get("is_stale")
            ts = (row.get("updated_at") or "")[:19].replace("T", " ")
            title = row.get("name") or f"#{sid}"
            line = f"**{title}** · {ts} UTC"
            if stale:
                line += " · устарело относительно индекса"
            st.markdown(line)
            oc1, oc2 = st.columns(2)
            with oc1:
                if st.button("Открыть", key=f"research_open_{sid}", width='stretch'):
                    sess = user_state.get_research_session(sid)
                    if not sess or not sess.get("payload"):
                        st.error("Сессия не найдена.")
                    else:
                        siv = sess.get("index_version")
                        if iv and siv and siv != iv:
                            st.session_state["_research_stale_banner"] = True
                        apply_research_payload(sess["payload"])
                        st.rerun()
            with oc2:
                if st.button("Удалить", key=f"research_del_{sid}", width='stretch'):
                    try:
                        user_state.delete_research_session(sid)
                    except Exception as exc:  # noqa: BLE001 - session delete failure is UI-reportable
                        st.error(str(exc))
                    else:
                        st.rerun()


def _render_sidebar_backup_restore_panel() -> None:
    """US-10.1 / US-10.2: единый блок backup + restore (ключи виджетов стабильны для session_state)."""
    from app.sync_service import (
        bundle_json_bytes,
        import_bundle_from_dict,
        qr_payload_for_bundle,
        qr_png_bytes,
    )

    if str(st.query_params.get("e2e_restore_preview") or "").lower() in {"1", "true", "yes"}:
        raw_restore = {
            "sync_version": user_state.SYNC_BUNDLE_VERSION,
            "exported_at": "2026-04-16T12:00:00Z",
            "tables": {},
        }
        st.session_state["restore_bundle_raw"] = raw_restore
        st.session_state["restore_bundle_preview"] = user_state.preview_full_sync_bundle(raw_restore)

    st.markdown("**Синхронизация и backup (US-10.1)**")
    st.download_button(
        "Скачать полный backup (rag_sync.json)",
        data=bundle_json_bytes(),
        file_name="rag_sync.json",
        mime="application/json",
        key="sidebar_sync_dl",
        help="Снимок user_state + quiz stats; восстановление через мастер ниже или import_full_sync_bundle.",
    )
    try:
        payload, fits = qr_payload_for_bundle()
        st.caption("QR: полный импорт со скана" if fits else "QR: только отпечаток — переносите JSON-файл")
        st.image(qr_png_bytes(payload))
    except Exception as e:  # noqa: BLE001 - robust QR backup display, continue UI render on failure
        st.warning(f"QR недоступен: {e}")

    st.markdown("**Восстановление из backup (US-10.2)**")
    st.caption(
        f"Ожидается `sync_version` = **{user_state.SYNC_BUNDLE_VERSION}**. "
        "Сначала предпросмотр, затем подтверждение — полная перезапись локального прогресса."
    )
    up = st.file_uploader("Файл backup (JSON)", type=["json"], key="sidebar_sync_upload")
    c_prev, c_clr = st.columns(2)
    with c_prev:
        preview_clicked = st.button("Предпросмотр", key="sidebar_restore_preview", width='stretch')
    with c_clr:
        if st.button("Сбросить предпросмотр", key="sidebar_restore_clear", width='stretch'):
            st.session_state.pop("restore_bundle_raw", None)
            st.session_state.pop("restore_bundle_preview", None)
            st.rerun()
    if preview_clicked:
        if up is None:
            st.warning("Выберите JSON-файл.")
        else:
            try:
                raw_restore = json.loads(up.getvalue().decode("utf-8"))
                preview = user_state.preview_full_sync_bundle(raw_restore)
                st.session_state["restore_bundle_raw"] = raw_restore
                st.session_state["restore_bundle_preview"] = preview
            except json.JSONDecodeError:
                st.error("Файл не является корректным JSON.")
            except ValueError as ex:
                st.error(str(ex))
    prev = st.session_state.get("restore_bundle_preview")
    if isinstance(prev, dict):
        st.success("Предпросмотр готов — проверьте счётчики и подтвердите импорт.")
        exp_at = prev.get("exported_at")
        if exp_at:
            st.caption(f"Экспортировано: {str(exp_at)[:19].replace('T', ' ')} UTC")
        st.metric("Всего строк (таблицы)", int(prev.get("total_rows") or 0))
        st.caption("Строк по таблице (top-level ключи bundle.tables)")
        counts = prev.get("table_row_counts") or {}
        if isinstance(counts, dict):
            busy = [(k, v) for k, v in counts.items() if int(v or 0) > 0]
            busy.sort(key=lambda kv: -kv[1])
            for name, n in busy[:12]:
                st.caption(f"- `{name}`: **{n}**")
        entity_counts = _restore_preview_entity_rows(prev)
        st.caption(
            "Ключевые сущности: "
            f"profiles={entity_counts['profiles']}, "
            f"decks={entity_counts['decks']}, "
            f"cards={entity_counts['cards']}, "
            f"reviews={entity_counts['reviews']}"
        )
        st.markdown('<div data-testid="e2e-restore-confirm"></div>', unsafe_allow_html=True)
        confirm = st.checkbox(
            "Я понимаю, что импорт перезапишет локальный прогресс на этой машине",
            key="sidebar_restore_confirm",
        )
        if st.button("Импортировать снимок", key="sidebar_sync_apply", disabled=not confirm):
            raw_apply = st.session_state.get("restore_bundle_raw")
            if not isinstance(raw_apply, dict):
                st.error("Нет данных для импорта — снова нажмите «Предпросмотр».")
            else:
                result = import_bundle_from_dict(raw_apply)
                st.session_state.pop("restore_bundle_raw", None)
                st.session_state.pop("restore_bundle_preview", None)
                st.success(_restore_result_summary(result))


def _render_mission_control_sidebar_sections(index_stats: dict | None) -> None:
    with st.expander("База знаний", expanded=False):
        render_panel_header("База знаний", "Короткая сводка индекса")
        if index_stats and index_stats.get("status") == "ok":
            st.metric("Документы", index_stats.get("documents_count", 0))
            st.metric("Ноды", index_stats.get("nodes_count", 0))
            if index_stats.get("last_indexed_at"):
                st.caption(f"Последняя индексация: {index_stats['last_indexed_at'][:19].replace('T', ' ')} UTC")
        else:
            st.caption("Индекс пока недоступен.")
    with st.expander("Инструменты", expanded=False):
        from app.ui.cockpit_rotator import render_rotator_panel
        from app.ui.mission_control import MORE_TOOLS, _navigate_to

        render_rotator_panel()
        for label, target_view, icon in MORE_TOOLS:
            if not _view_visible(target_view):
                continue
            if st.button(f"{icon} {label}", key=f"sidebar_tool_{target_view}", width="stretch"):
                _navigate_to(target_view)


def _load_active_course_plan_into_session(scope: dict[str, Any]) -> bool:
    documents = normalize_source_paths(list(scope.get("source_paths") or []))
    if not documents:
        return False
    artifact = load_course_artifact(documents)
    plan = artifact.get("learning_plan") if isinstance(artifact, dict) else None
    if not isinstance(plan, dict):
        return False
    st.session_state["last_course_prepare"] = artifact
    st.session_state["last_learning_plan"] = plan
    st.session_state[PENDING_CURRENT_VIEW_KEY] = "Темы"
    return True


def render_sidebar(index_stats: dict | None):
    with st.sidebar:
        if get_settings().auth_enabled:
            render_account_status_sidebar()
            st.markdown("---")
        st.subheader("📊 Live метрики")
        evlog = st.session_state.get("ui_event_log") or []
        if evlog:
            for ev in evlog[-5:]:
                st.caption(f"{ev.get('time', '')} — {ev.get('event', '')}")
        else:
            st.caption("События появятся после действий в сессии.")
        st.markdown("---")
        if st.button("Мой прогресс", width='stretch', key="sidebar_nav_mastery"):
            st.switch_page("pages/3_Мой_прогресс.py")
        if st.button("Продолжить обучение", width='stretch', key="sidebar_smart_resume"):
            from app.learning_plan_service import plan_service

            nxt = plan_service.get_smart_resume()
            st.session_state["current_topic"] = nxt
            st.toast(f"Следующий шаг: {nxt}")
        if feature_visible_by_id("page:analytics") and st.button("Аналитика", width='stretch', key="sidebar_nav_analytics"):
            st.switch_page("pages/4_Аналитика.py")
        # W4a: ceremonial deep link to Memory Run / 3D hall (not Mission Control home).
        if _view_visible("Knowledge Graph") and st.button(
            "🌆 В Мнемополис",
            width="stretch",
            key="sidebar_nav_mnemo_polis",
            help="Открыть Knowledge Graph → 3D-зал (город памяти). Главный экран — Mission Control.",
        ):
            from app.ui.mnemo_nav import open_mnemo_polis as _open_mnemo

            _open_mnemo()
            st.rerun()
        _cw = st.session_state.pop("coach_weak_spot_topic", None)
        if _cw:
            st.info(
                f"AI Coach: слабое место — **{_cw}**. Укажите тему в Tutor или scoped quiz по этому концепту."
            )
        if str(st.session_state.get("current_view") or "").strip() == "Чат с тьютором":
            if "tutor_session_id" not in st.session_state:
                st.session_state["tutor_session_id"] = str(uuid.uuid4())
            try:
                from app.ui.learner_profile_panel import render_personalized_learner_panel

                _sid_tutor = str(st.session_state.get("tutor_session_id") or "").strip() or None
                render_personalized_learner_panel(session_id=_sid_tutor, variant="sidebar")
            except Exception as _exc:  # noqa: BLE001
                import logging  # noqa: BLE001
                logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                pass
            st.markdown("---")
        try:
            from app.gamification_service import get_snapshot

            _g = get_snapshot()
        except Exception as _exc:  # noqa: BLE001
            import logging  # noqa: BLE001
            logging.getLogger(__name__).debug("! caught exception: %s", _exc)
            _g = {}
        if _g:
            _cur_xp = int(_g.get("xp_in_level") or 0)
            _span = int(_g.get("xp_for_level_span") or 1000)
            st.caption(
                f"🔥 Стрик **{_g.get('daily_streak', 0)}** дн. · "
                f"**{_g.get('level_title', '?')}** (ур. {_g.get('level', '?')}) · "
                f"XP **{_g.get('total_xp', 0)}** ({_cur_xp}/{_span} в уровне) · "
                f"квиз-стрик {_g.get('quiz_streak', 0)}"
            )
        _active_scope = _get_active_scope()
        if _active_scope:
            _scope_title = str(_active_scope.get("title") or _active_scope.get("folder_rel") or "Курс")
            st.info(f"🎯 Активный курс: **{_scope_title}**")
            if st.button("Открыть программу курса", key="sidebar_open_course_plan", width="stretch", type="primary"):
                if _load_active_course_plan_into_session(_active_scope):
                    st.rerun()
                else:
                    st.warning("Для активного курса пока нет сохранённой программы. Откройте «Темы» и нажмите «Подготовить курс».")
            if st.button("× Деактивировать курс", key="sidebar_deactivate_scope", width="stretch", type="secondary"):
                _deactivate_scope()
                st.rerun()
            st.markdown("---")
        else:
            _last_scope = _get_last_deactivated_scope()
            if _last_scope:
                _scope_title = str(_last_scope.get("title") or _last_scope.get("folder_rel") or "Курс")
                st.caption(f"↩ Недавно деактивирован: **{_scope_title}**")
                if st.button(
                    restore_course_cta_ru(_scope_title),
                    key="sidebar_restore_scope",
                    width="stretch",
                    type="secondary",
                ):
                    _restore_scope()
                    st.rerun()
                st.markdown("---")
        if feature_visible_by_id("sidebar:sync_backup"):
            with st.expander(sync_transfer_sidebar_expander_label_ru(), expanded=False):
                st.caption(sync_transfer_sidebar_intro_caption_ru())
                _render_sidebar_backup_restore_panel()
        _render_mission_control_sidebar_sections(index_stats)
        st.markdown("---")
        render_panel_header("Индекс", "Быстрый статус базы знаний")
        if index_stats and index_stats.get("status") == "ok":
            st.metric("Документы", index_stats.get("documents_count", 0))
            st.metric("Ноды", index_stats.get("nodes_count", 0))
            if index_stats.get("last_indexed_at"):
                st.caption(f"Последняя индексация: {index_stats['last_indexed_at'][:19].replace('T', ' ')} UTC")
            _iv = index_stats.get("index_version")
            _gid = index_stats.get("generation_id")
            _ract = index_stats.get("registry_activated_at")
            if (_iv is not None or _gid or _ract) and feature_visible_by_id("panel:index_freshness"):
                with st.expander("Актуальность индекса (freshness)", expanded=False):
                    if _iv is not None:
                        st.markdown(f"**Версия реестра:** `v{int(_iv)}`")
                    if _gid:
                        st.markdown(f"**Поколение:** `{_gid}`")
                    if _ract:
                        st.caption(f"Активация в реестре: {str(_ract)[:19].replace('T', ' ')} UTC")
                    st.caption(
                        "Сохранённые сессии исследований помечают версию индекса; при её смене перепроверьте synthesis и программы."
                    )
        else:
            st.info("Индекс пока недоступен. Проверьте, что база уже проиндексирована, или запустите переиндексацию.")
            if st.button("Добавить материалы", key="sidebar_add_materials", width="stretch", type="primary"):
                from app.ui.breadcrumb import HOME_VIEW
                from app.ui.session_state import PENDING_CURRENT_VIEW_KEY

                st.session_state[PENDING_CURRENT_VIEW_KEY] = HOME_VIEW
                st.rerun()
        folder = ""
        folder_rel = ""
        file_name = ""
        relative_path = ""
        topic_quick = _SIDEBAR_FILTER_TOPIC_ALL
        folder_quick = _SIDEBAR_FILTER_FOLDER_ALL
        if feature_visible_by_id("sidebar:expert_filters"):
            with st.expander(expert_controls_expander_label_ru(), expanded=False):
                st.caption(expert_controls_sidebar_blurb_ru())
                if feature_visible_by_id("panel:voice"):
                    with st.expander("Голос", expanded=False):
                        from app.voice_service import VoiceService, voice_dependencies_available

                        deps = voice_dependencies_available()
                        st.caption(
                            f"SpeechRecognition: {'да' if deps['speech_recognition'] else 'нет'} · "
                            f"pyttsx3 (tts): {'да' if deps['pyttsx3'] else 'нет'} · "
                            f"PyAudio: {'да' if deps['pyaudio'] else 'нет'} · "
                            f"faster_whisper (asr): {'да' if deps.get('faster_whisper') else 'нет'}"
                        )
                        av = st.audio_input("Запись вопроса (предпочтительно WAV)", key="sidebar_voice_audio")
                        if av is not None and st.button("Распознать запись", key="sidebar_voice_transcribe"):
                            vo = VoiceService()
                            st.session_state["voice_transcript"] = vo.transcribe_audio_bytes(av.getvalue())
                        if st.button("Слушать микрофон (локально)", key="sidebar_voice_mic"):
                            vo = VoiceService()
                            st.session_state["voice_transcript"] = vo.listen_microphone_once()
                        vt = st.session_state.get("voice_transcript")
                        if vt:
                            st.info(vt)
                        if vt and st.button("Озвучить последний текст", key="sidebar_voice_speak"):
                            VoiceService().speak(str(vt))
                        # B2 (TTS file): demo of text->audio file for "on the go" or text sections (no live speaker required)
                        if vt and st.button("Сгенерировать TTS файл (B2)", key="sidebar_tts_file"):
                            from pathlib import Path
                            p = VoiceService().tts_text_to_audio_file(str(vt), suggested_name="sidebar_tts_demo.wav")
                            if p and p.exists():
                                st.audio(str(p))
                                st.caption(f"TTS файл: {p.name}")
                            else:
                                st.caption("TTS файл не создан (pyttsx3 недоступен или ошибка). Установите [tts] или [voice].")
                    st.markdown("---")
                with st.expander("Область поиска для Q&A", expanded=False):
                    folder = st.text_input("Последняя папка")
                    folder_rel = st.text_input("Относительный путь папки")
                    file_name = st.text_input("Имя файла")
                    relative_path = st.text_input("Относительный путь файла")
                topics_catalog = load_topics_catalog()
                topic_choices = [_SIDEBAR_FILTER_TOPIC_ALL]
                if topics_catalog and topics_catalog.get("topics"):
                    for t in topics_catalog["topics"]:
                        name = (t.get("topic_name") or "").strip()
                        if name:
                            topic_choices.append(name)
                folder_quick_choices = [_SIDEBAR_FILTER_FOLDER_ALL]
                for fr in (index_stats or {}).get("folder_rel_options") or []:
                    s = str(fr).strip()
                    if is_user_course_folder_rel(s):
                        folder_quick_choices.append(s)
                st.caption(sidebar_fast_filters_caption_ru())
                topic_quick = st.selectbox("Тема", topic_choices, key="qa_sidebar_topic")
                folder_quick = st.selectbox("Папка (folder_rel)", folder_quick_choices, key="qa_sidebar_folder_rel")
                with st.expander("Файлы в индексе", expanded=False):
                    for item in (index_stats or {}).get("files", []):
                        st.text(item)
        render_sidebar_notes_panel()
        if feature_visible_by_id("sidebar:research_sessions"):
            render_sidebar_research_sessions(index_stats)
        st.markdown("---")
        render_panel_header("Сессия", "Что уже исследовали в этом окне")
        render_reading_mode_toggle(
            key="reading_mode",
            help_text="Удобный режим для длинных ответов, конспектов и программ обучения: уже строка, спокойнее ритм текста и меньше визуального шума.",
        )
        render_focus_view_toggle(
            key="focus_view",
            help_text=sidebar_focus_view_help_ru(),
        )
        if st.button("⚙️ Настроить интерфейс", key="sidebar_control_panel", width="stretch"):
            from app.ui.control_panel import open_control_panel_dialog

            open_control_panel_dialog()
        if st.session_state["history"]:
            for entry in st.session_state["history"][:8]:
                preview = (entry.get("question") or "")[:58]
                st.caption(preview + ("..." if len((entry.get("question") or "")) > 58 else ""))
        else:
            st.caption("После первого ответа здесь появится короткая история ваших вопросов.")
    return folder, folder_rel, file_name, relative_path, topic_quick, folder_quick
