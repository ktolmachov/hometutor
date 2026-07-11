"""Подвкладка «Программа обучения» на вкладке «Темы» (P5c split)."""

from __future__ import annotations

import streamlit as st

from app import user_state
from app.knowledge_graph import knowledge_graph as _knowledge_graph
from app.learning_plan_state import check_budget as _check_budget
from app.ui.answer_helpers import format_sources_markdown
from app.ui.course_prepare_view import render_course_prepare_view
from app.ui.helpers import format_request_error
from app.ui.learning_plan_navigation import enriched_learning_plan_markdown, render_learning_plan_table
from app.ui.longform import render_longform_block
from app.ui.print_view import open_print_view
from app.ui.quiz_panel import render_quiz_panel
from app.ui.source_cards import render_source_cards
from app.ui.widgets import render_chip_row, render_metric_card
from app.ui_client import fetch_json


def render_topics_plan_subtab(
    *,
    selected_topic: dict,
    selected_documents: list[str],
    iv: str | None,
) -> None:
    st.caption(
        "Подходит для новой темы, длинной лекции и подготовки к домашнему заданию. Программу можно экспортировать в Markdown после генерации."
    )
    st.markdown("#### Программа обучения")
    plan_goal = st.text_input(
        "Цель обучения",
        value=f"Изучить тему {selected_topic['topic_name']}",
        key=f"plan_goal_{selected_topic['topic_id']}",
        placeholder="Например: подготовиться к домашнему заданию",
    )
    plan_cols = st.columns(2)
    with plan_cols[0]:
        plan_level = st.selectbox(
            "Уровень",
            options=["beginner", "intermediate", "advanced"],
            index=1,
            key=f"plan_level_{selected_topic['topic_id']}",
            help="Уровень влияет на детализацию шагов, предполагаемые prerequisites и глубину объяснений.",
        )
    with plan_cols[1]:
        plan_hours = st.number_input(
            "Бюджет времени (часы)",
            min_value=1.0,
            max_value=40.0,
            value=6.0,
            step=1.0,
            key=f"plan_hours_{selected_topic['topic_id']}",
        )
    known_topics_raw = st.text_input(
        "Что уже знаете",
        key=f"known_topics_{selected_topic['topic_id']}",
        placeholder="Например: basic python, ranking",
        help="Через запятую. Это поможет не повторять уже знакомые темы.",
    )
    if selected_documents:
        st.caption(
            f"В текущей выборке: {len(selected_documents)} документ(ов). Кнопка «Программа по выборке» использует только их."
        )
    _graph_has_concepts = bool(_knowledge_graph.get_concepts())
    plan_user_progress = st.checkbox(
        "Учитывать прогресс (чтение, quiz, интервальные повторения)",
        value=_graph_has_concepts,
        key=f"plan_user_progress_{selected_topic['topic_id']}",
        help="Карта знаний определяет обязательный порядок шагов и зависимости. "
        "Прогресс (чтение, quiz, интервальные повторения) влияет на персонализацию."
        if _graph_has_concepts
        else "Карта знаний пуста: порядок шагов будет свободным (free-form), "
        "зависимости определит LLM без привязки к графу.",
    )
    known_topics = [item.strip() for item in known_topics_raw.split(",") if item.strip()]
    render_course_prepare_view(
        topic=selected_topic,
        goal=plan_goal,
        level=plan_level,
        time_budget_hours=plan_hours,
        known_topics=known_topics,
        user_progress=plan_user_progress,
        key_prefix=f"course_prepare_{selected_topic['topic_id']}",
    )
    plan_action_row = st.columns(2)
    with plan_action_row[0]:
        if st.button("Программа по всей теме", key=f"plan_all_{selected_topic['topic_id']}", width="stretch", type="primary"):
            topic_doc_paths = [
                doc.get("relative_path") or doc.get("file_name")
                for doc in selected_topic.get("documents") or []
                if doc.get("relative_path") or doc.get("file_name")
            ]
            try:
                result = fetch_json(
                    "POST",
                    "/learning-plan",
                    timeout=120,
                    json={
                        "topic_id": selected_topic["topic_id"],
                        "documents": topic_doc_paths,
                        "goal": plan_goal,
                        "level": plan_level,
                        "time_budget_hours": plan_hours,
                        "known_topics": known_topics,
                        "user_progress": plan_user_progress,
                    },
                )
                result["selection_mode"] = "topic"
                st.session_state["last_learning_plan"] = result
            except Exception as e:  # noqa: BLE001 — API call failure shown to user, must not crash the plan subtab
                st.error(f"Ошибка программы обучения: {format_request_error(e)}")
    with plan_action_row[1]:
        if st.button("Программа по выборке", key=f"plan_selected_{selected_topic['topic_id']}", width="stretch", type="secondary"):
            if not selected_documents:
                st.warning("Сначала выберите хотя бы один документ в левой колонке, чтобы построить программу по выборке.")
            else:
                try:
                    result = fetch_json(
                        "POST",
                        "/learning-plan",
                        timeout=120,
                        json={
                            "topic": selected_topic["topic_name"],
                            "documents": selected_documents,
                            "goal": plan_goal,
                            "level": plan_level,
                            "time_budget_hours": plan_hours,
                            "known_topics": known_topics,
                            "user_progress": plan_user_progress,
                        },
                    )
                    result["selection_mode"] = "selected_documents"
                    result["selected_documents"] = selected_documents
                    st.session_state["last_learning_plan"] = result
                except Exception as e:  # noqa: BLE001 — API call failure shown to user, must not crash the plan subtab
                    st.error(f"Ошибка программы обучения: {format_request_error(e)}")

    learning_plan = st.session_state.get("last_learning_plan")
    if learning_plan and learning_plan.get("topic") == selected_topic["topic_name"]:
        mode = "вся тема" if learning_plan.get("selection_mode") == "topic" else "выбранные документы"
        st.caption(f"Режим программы: {mode}")
        summary_cols = st.columns(3)
        with summary_cols[0]:
            render_metric_card("Уровень", str(learning_plan.get("level") or "n/a"), "study mode")
        with summary_cols[1]:
            hours_value = learning_plan.get("time_budget_hours")
            hours_label = f"{hours_value:g} ч" if isinstance(hours_value, (int, float)) else "n/a"
            render_metric_card("Время", hours_label, "budget")
        with summary_cols[2]:
            missing_count = len(learning_plan.get("missing_topics") or [])
            render_metric_card("Пробелы", str(missing_count), "topics to add")

        coverage = learning_plan.get("coverage") or {}
        if coverage.get("total"):
            ratio_pct = round(coverage.get("ratio", 0) * 100)
            cov_color = "#2e7d32" if ratio_pct >= 80 else "#e65100" if ratio_pct >= 40 else "#c62828"
            st.markdown(
                f'<span style="background:{cov_color};color:#fff;border-radius:999px;padding:0.25rem 0.7rem;font-size:0.82rem;font-weight:700;">'
                f'Покрытие: {coverage.get("covered", 0)} из {coverage["total"]} документов ({ratio_pct}%)</span>',
                unsafe_allow_html=True,
            )
            missing_docs = coverage.get("missing", [])
            if missing_docs:
                st.caption(f"В эту программу не вошли: {', '.join(missing_docs[:5])}")
        goal_text = learning_plan.get("goal") or ""
        if goal_text:
            st.markdown(
                f"""
                <div class="callout">
                    <div class="panel-title">Цель</div>
                    <div>{goal_text}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        if learning_plan.get("missing_topics"):
            st.caption(f"Полезно добрать перед следующим шагом: {', '.join(learning_plan['missing_topics'][:6])}")
        plan_order_warning = str(learning_plan.get("plan_order_warning") or "").strip()
        if plan_order_warning:
            st.warning(plan_order_warning)
        dp = learning_plan.get("dynamic_plan")
        if dp and dp.get("enabled"):
            with st.expander("Персонализированный порядок (прогресс + граф + повторения)", expanded=False):
                st.caption(
                    f"Transfer по графу: **{dp.get('mastery_percentage')}%** · "
                    f"Просроченных повторов: **{dp.get('next_review_count')}**"
                )
                for i, step in enumerate(dp.get("plan") or [], 1):
                    st.markdown(
                        f"{i}. **{step.get('topic')}** — `{step.get('type')}` · "
                        f"~{step.get('estimated_hours')}h — {step.get('reason', '')}"
                    )
        plan_md = learning_plan.get("plan", "")
        display_plan_md = enriched_learning_plan_markdown(
            plan_md,
            learning_plan=learning_plan,
            topic_id=str(selected_topic.get("topic_id") or ""),
        )
        rendered_as_table = render_learning_plan_table(
            plan_md,
            learning_plan=learning_plan,
            topic_id=str(selected_topic.get("topic_id") or ""),
            key_prefix=f"plan_nav_{selected_topic['topic_id']}",
        )
        if not rendered_as_table:
            render_longform_block(display_plan_md, markdown=True)
        plan_steps = user_state.learning_plan_steps_from_markdown(plan_md)
        budget_raw = learning_plan.get("time_budget_hours")
        try:
            budget_float = float(budget_raw) if budget_raw else 0.0
        except (TypeError, ValueError):
            budget_float = 0.0
        budget_status = _check_budget(plan_md, budget_float) if budget_float > 0 else None
        if budget_status:
            if budget_status.over_budget:
                budget_cols = st.columns([3, 1])
                with budget_cols[0]:
                    st.warning(
                        f"Программа по таблице занимает ~{budget_status.total_hours:g} ч, "
                        f"что на {budget_status.exceeds_by_hours:g} ч выше "
                        f"заданного бюджета {budget_status.budget_hours:g} ч."
                    )
                with budget_cols[1]:
                    if st.button(
                        "Пересобрать по бюджету",
                        key=f"budget_rebuild_{selected_topic['topic_id']}",
                        type="secondary",
                        use_container_width=True,
                    ):
                        if st.session_state.get("last_learning_plan"):
                            lp = dict(st.session_state["last_learning_plan"])
                            old_budget = lp.get("time_budget_hours")
                            if old_budget:
                                lp["time_budget_hours"] = old_budget
                            st.session_state["pending_rebuild"] = lp.get("selection_mode") or "topic"
                            st.rerun()
            elif budget_status.missing_or_invalid_hours > 0:
                st.caption(
                    f"В {budget_status.missing_or_invalid_hours} шаг(ах) не удалось "
                    "прочитать время из колонки «Время (ч)»."
                )
        n_steps = max(len(plan_steps), 1)
        step_options = list(range(min(max(len(plan_steps), 1), 40)))

        def _fmt_plan_step(i: int) -> str:
            if i < len(plan_steps):
                line = plan_steps[i].split("\n", 1)[0].strip()
                return (line[:100] + "…") if len(line) > 100 else line
            return f"Шаг {i + 1}"

        step_cols = st.columns([3, 1])
        with step_cols[0]:
            cur_step = st.selectbox(
                "Текущий шаг программы",
                options=step_options,
                format_func=_fmt_plan_step,
                key=f"plan_step_pick_{selected_topic['topic_id']}",
            )
        with step_cols[1]:
            st.markdown("<div style='height:1.6rem'></div>", unsafe_allow_html=True)
            if st.button(
                "Запомнить шаг",
                key=f"plan_step_save_{selected_topic['topic_id']}",
                width="stretch",
                type="secondary",
            ):
                si = int(cur_step)
                label = plan_steps[si] if si < len(plan_steps) else plan_md[:400]
                try:
                    user_state.upsert_reading_status(
                        resource_type="learning_plan",
                        resource_id=user_state.learning_plan_resource_id(selected_topic["topic_id"]),
                        step_index=si,
                        step_label=(label or "")[:500],
                        progress=(si + 1) / float(n_steps),
                        display_title=f"Программа по теме «{selected_topic['topic_name']}»",
                        index_version=iv or None,
                    )
                except Exception as exc:  # noqa: BLE001 — progress save failure is reported to the user, not fatal
                    st.error(str(exc))
                else:
                    st.success("Шаг сохранён — карточка «Продолжить» обновится.")
                    st.rerun()
        if coverage.get("ratio") is not None:
            if st.button(
                "Записать покрытие программы в прогресс темы",
                key=f"plan_cov_apply_{selected_topic['topic_id']}",
                width="stretch",
                type="secondary",
            ):
                try:
                    user_state.upsert_reading_status(
                        resource_type="topic",
                        resource_id=user_state.topic_resource_id(selected_topic["topic_id"]),
                        progress=float(coverage["ratio"]),
                        display_title=f"Тема «{selected_topic['topic_name']}»",
                        index_version=iv or None,
                    )
                except Exception as exc:  # noqa: BLE001 — progress update failure is reported to the user, not fatal
                    st.error(str(exc))
                else:
                    st.success("Прогресс темы обновлён из покрытия программы")
                    st.rerun()
        st.markdown("##### Самопроверка (программа)")
        plan_quiz_text = (plan_md or "") + "\n\n" + format_sources_markdown(learning_plan.get("sources") or [])
        render_quiz_panel(
            source_key=f"topics_plan_{selected_topic['topic_id']}",
            title=f"Программа: {selected_topic['topic_name']}",
            material=plan_quiz_text,
        )
        if learning_plan.get("documents"):
            st.markdown("#### Документы в программе")
            render_chip_row(
                [
                    doc.get("relative_path") or doc.get("file_name") or "document"
                    for doc in learning_plan.get("documents") or []
                ]
            )
        md_lines = [
            f"# Программа обучения: {learning_plan.get('topic', selected_topic['topic_name'])}\n\n",
            "## Контекст\n\n",
            f"- Цель: **{goal_text or 'Не указана'}**\n",
            f"- Уровень: **{learning_plan.get('level') or 'n/a'}**\n",
            f"- Бюджет времени: **{hours_label}**\n",
        ]
        if learning_plan.get("missing_topics"):
            md_lines.append(f"- Полезно добрать: **{', '.join(learning_plan['missing_topics'])}**\n")
        if coverage.get("total"):
            md_lines.append(
                f"- Покрытие: **{coverage.get('covered', 0)} из {coverage.get('total', 0)} документов ({ratio_pct}%)**\n"
            )
        md_lines.append("\n## Программа обучения\n\n")
        md_lines.append(display_plan_md)
        if learning_plan.get("documents"):
            md_lines.append("\n\n## Документы\n\n")
            for doc in learning_plan.get("documents") or []:
                path = doc.get("relative_path") or doc.get("file_name") or "document"
                md_lines.append(f"- `{path}`\n")
        if learning_plan.get("sources"):
            md_lines.append("\n\n## Источники\n\n")
            md_lines.append(format_sources_markdown(learning_plan.get("sources") or []))
        plan_action_footer = st.columns(2)
        with plan_action_footer[0]:
            if st.button("Печать/чистый вид", key=f"print_plan_{selected_topic['topic_id']}", width="stretch", type="secondary"):
                open_print_view(
                    title=f"Программа обучения: {learning_plan.get('topic', selected_topic['topic_name'])}",
                    subtitle="Чистый вид для пошагового прохождения темы, лекции или подготовки к домашнему заданию.",
                    body_md=display_plan_md,
                    export_md="".join(md_lines),
                    documents=[
                        doc.get("relative_path") or doc.get("file_name") or "document"
                        for doc in learning_plan.get("documents") or []
                    ],
                    sources=learning_plan.get("sources") or [],
                )
                st.rerun()
        st.download_button(
            label="Скачать программу в Markdown",
            data="".join(md_lines),
            file_name="learning_plan.md",
            mime="text/markdown",
            key=f"download_learning_plan_{selected_topic['topic_id']}",
        )
        if learning_plan.get("sources"):
            st.markdown("---")
            render_source_cards(learning_plan["sources"], prefix="plan_src")
    else:
        st.markdown(
            """
            <div class="callout">
                <div class="panel-title">Соберите программу обучения</div>
                <div class="panel-subtitle">Подходит для новой темы, лекций и подготовки к экзамену или ДЗ</div>
                <div><strong>1.</strong> Укажите цель, уровень и бюджет времени.</div>
                <div><strong>2.</strong> При необходимости сузьте набор документов.</div>
                <div><strong>3.</strong> Постройте программу по теме или по вашей выборке.</div>
                <div><strong>4.</strong> После генерации используйте программу как маршрут, а чат с тьютором — как место для объяснений и проверки понимания.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
