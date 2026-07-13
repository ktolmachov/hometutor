"""Вкладка «Темы»: каталог тем, synthesis, программа обучения."""
from __future__ import annotations

import streamlit as st

from app import user_state
from app.ui.index_labels import index_version_label
from app.ui.study_scope import get_active_scope
from app.ui.topics_catalog import load_topics_catalog
from app.ui.topics_tab_filters import (
    dedupe_topics_by_id,
    filter_topics_by_active_scope,
    filter_topics_by_search,
)
from app.ui.topics_tab_left_column import render_topics_left_column
from app.ui.topics_tab_plan_subtab import render_topics_plan_subtab
from app.ui.topics_tab_right_column import (
    render_obsidian_course_batch,
    render_topic_scope_quiz_panel,
    render_topics_right_column,
    topic_scope_quiz_is_active,
)
from app.ui.topics_tab_synthesis_subtab import render_topics_synthesis_subtab
from app.ui.tutor_mastery_forecast_panel import render_tutor_orchestration_snapshot_expander
from app.ui.widgets import render_metric_card, render_panel_header
from app.ui_client import load_index_stats


def _render_course_obsidian_button(topics_catalog: dict | None) -> None:
    """Кнопка «Весь курс → Obsidian» с проверкой покрытия конспектами."""
    all_paths: list[str] = []
    if topics_catalog:
        seen: set[str] = set()
        for topic in topics_catalog.get("topics") or []:
            for doc in topic.get("documents") or []:
                p = doc.get("relative_path") or doc.get("file_name") or ""
                if p and p not in seen:
                    seen.add(p)
                    all_paths.append(p)

    if all_paths:
        try:
            from app.konspekt_discovery import coverage_summary
            cov = coverage_summary(all_paths)
        except Exception:  # noqa: BLE001 — coverage check failure must degrade to None, not crash the tab
            cov = None
    else:
        cov = None

    if cov is not None and cov.pct >= 1.0:
        # A1: passport по плану «N/M с конспектом · рубрика в K · средняя X/5»
        rubric_info = ""
        try:
            from app.konspekt_discovery import find_konspekt_for_source_in_data, get_konspekt_quality_rubric
            rubric_avgs = []
            for p in all_paths:
                km = find_konspekt_for_source_in_data(p)
                if km:
                    r = get_konspekt_quality_rubric(km.path)
                    if r and r.get("average") is not None:
                        rubric_avgs.append(r["average"])
            if rubric_avgs:
                k = len(rubric_avgs)
                overall = round(sum(rubric_avgs) / k, 1)
                rubric_info = f" · рубрика в {k} · средняя {overall}"  # /5 convention in source tables (see rubric expander)
            # C1: sample grade for passport
            try:
                from app.section_index import _cached_parse_sections, get_konspekt_grade
                for p in all_paths:
                    km = find_konspekt_for_source_in_data(p)
                    if km:
                        secs = _cached_parse_sections(km.path)
                        g = get_konspekt_grade(secs)
                        if g != "базовый":
                            rubric_info += f" · {g}"
                            break
            except Exception:
                pass
        except Exception:  # noqa: BLE001 - optional rubric lookup must not break the Topics tab
            pass
        label = f"{cov.covered}/{cov.total} с конспектом{rubric_info}"
        st.markdown(
            f'<div style="font-size:12px;color:#4ade80;padding:6px 0">✅ {label}</div>',
            unsafe_allow_html=True,
        )
    else:
        help_text = "Подготовить конспекты для всех документов всех тем курса"
        if cov is not None and cov.covered > 0:
            help_text = f"{cov.covered} из {cov.total} документов уже имеют конспект"
        st.button(
            "📥 Весь курс → Obsidian",
            key="obs_course_btn",
            width="stretch",
            help=help_text,
        )


def _use_full_width_topic_workspace(
    *,
    active_scope: dict | None,
    filtered_topics: list,
    quiz_active: bool,
) -> bool:
    """Avoid wasting a navigation column when active course scope has one topic."""
    return bool(active_scope and len(filtered_topics) == 1 and not quiz_active)


def render_topics_tab(index_stats: dict | None = None) -> None:
    if index_stats is None:
        index_stats = load_index_stats()
    iv = index_version_label(index_stats)
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.caption(
        "Этот экран лучше всего подходит для длинных лекций и новых тем: здесь можно собрать конспект или построить программу обучения по всей теме либо по выбранной выборке документов."
    )
    render_panel_header(
        "Темы и synthesis",
        "Исследуйте карту тем, выберите документы и собирайте конспекты как из рабочей базы знаний",
    )
    st.markdown(
        """
        <div class="step-strip">
            <span class="step-item"><strong>1.</strong> Найдите нужную тему</span>
            <span class="step-item"><strong>2.</strong> Сузьте набор документов</span>
            <span class="step-item"><strong>3.</strong> Соберите synthesis</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_tutor_orchestration_snapshot_expander(key_prefix="topics", show_focus_concept=True)
    toolbar = st.columns([1.05, 1.5, 0.7, 0.9], gap="large")
    with toolbar[0]:
        if st.button("Обновить каталог тем", key="topics_refresh", width="stretch", type="secondary"):
            load_topics_catalog(force=True)
    with toolbar[1]:
        search_query = st.text_input(
            "Поиск по темам и документам",
            placeholder="Например: retrieval, security, hybrid, prompt injection",
            key="topics_search",
        ).strip().lower()
    with toolbar[2]:
        catalog = load_topics_catalog(force=False)
        render_metric_card("Тем", str((catalog or {}).get("total_topics", 0)), "catalog")
    with toolbar[3]:
        _render_course_obsidian_button(topics_catalog=st.session_state.get("topics_catalog"))
    topics_catalog = st.session_state.get("topics_catalog")
    if not topics_catalog or not topics_catalog.get("topics"):
        st.info("Каталог тем пока недоступен. Обычно это значит, что индекс ещё пуст или переиндексация не завершилась.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    active_scope = get_active_scope()
    scoped_topics = filter_topics_by_active_scope(topics_catalog["topics"], active_scope)
    if active_scope and not scoped_topics:
        title = active_scope.get("title") or active_scope.get("folder_rel") or "активный курс"
        st.warning(f"Для «{title}» в каталоге тем пока нет документов. Обновите индекс или деактивируйте курс.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    filtered_topics = filter_topics_by_search(scoped_topics, search_query)
    filtered_topics = dedupe_topics_by_id(filtered_topics)
    if not filtered_topics:
        st.warning("По этому фильтру ничего не найдено. Попробуйте убрать часть слов или выбрать тему без фильтра.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    if st.session_state.get("obs_course_btn"):
        render_obsidian_course_batch(filtered_topics, key="obs_course_run")

    topic_lookup = {topic["topic_id"]: topic for topic in filtered_topics}
    if st.session_state["active_topic_id"] not in topic_lookup:
        st.session_state["active_topic_id"] = filtered_topics[0]["topic_id"]
    selected_topic = topic_lookup[st.session_state["active_topic_id"]]
    try:
        topic_states = user_state.get_topic_states([t["topic_id"] for t in filtered_topics if t.get("topic_id")])
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001

        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        topic_states = {}
    quiz_active = topic_scope_quiz_is_active(selected_topic)
    if _use_full_width_topic_workspace(
        active_scope=active_scope,
        filtered_topics=filtered_topics,
        quiz_active=quiz_active,
    ):
        selected_documents = render_topics_right_column(
            selected_topic=selected_topic,
            topic_states=topic_states,
            iv=iv,
            index_stats=index_stats,
        )
    else:
        column_weights = [0.55, 2.45] if quiz_active else [0.7, 1.85]
        left, right = st.columns(column_weights, gap="medium" if quiz_active else "large")
        with left:
            render_topics_left_column(
                filtered_topics=filtered_topics,
                selected_topic=selected_topic,
                topic_states=topic_states,
            )
        with right:
            selected_documents = render_topics_right_column(
                selected_topic=selected_topic,
                topic_states=topic_states,
                iv=iv,
                index_stats=index_stats,
            )
    render_topic_scope_quiz_panel(selected_topic)
    st.markdown("---")
    result_tabs = st.tabs(["Конспект", "Программа обучения"])
    with result_tabs[0]:
        render_topics_synthesis_subtab(selected_topic=selected_topic, iv=iv)
    with result_tabs[1]:
        render_topics_plan_subtab(
            selected_topic=selected_topic,
            selected_documents=selected_documents,
            iv=iv,
        )
    st.markdown("</div>", unsafe_allow_html=True)
