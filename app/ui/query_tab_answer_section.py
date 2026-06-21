"""Блок ответа, источников и отладки под колонками Q&A (P5c split)."""

from __future__ import annotations

import uuid

import streamlit as st

from app import user_state
from app.ui.answer_helpers import (
    answer_latency_bucket_label_ru,
    format_sources_markdown,
    linkify_qa_inline_citations,
    open_topic_from_paths,
    run_synthesis_for_paths,
    slow_answer_scope_hint_ru,
    source_paths_from_answer,
)
from app.ui.continuity_bridge import (
    expert_controls_expander_label_ru,
    qa_five_min_tutor_bridge_caption_ru,
    qa_tab_after_answer_debug_intro_caption_ru,
    qa_tab_focus_view_caption_ru,
    qa_tab_sources_column_intro_caption_ru,
    qa_to_tutor_bridge_caption_ru,
    store_qa_tutor_handoff_context,
)
from app.ui.debug_panel import (
    confidence_reason_labels,
    graph_expansion_trust_caption_ru,
    render_debug_summary,
)
from app.ui.helpers import (
    format_request_error,
    llm_source_badge_text,
    llm_source_privacy_notice,
    post_feedback,
)
from app.ui.kb_fetch import fetch_kb_suggestions
from app.ui.longform import render_longform_block
from app.ui.query_tab_helpers import (
    answer_latency_caption,
    infer_topic_label_from_last_answer,
    summarize_answer_for_handoff,
)
from app.ui.quiz_panel import render_quiz_panel
from app.ui.session_state import PENDING_CURRENT_VIEW_KEY, persist_tutor_goal_snapshot_from_session
from app.ui.source_cards import render_source_cards
from app.ui.widgets import render_chip_row
from app.ui_client import fetch_json


def render_query_answer_section() -> None:
    last = st.session_state.get("last_answer")
    if not last:
        return
    st.markdown("---")
    focus_view = st.session_state.get("focus_view", False)
    if focus_view:
        st.caption(qa_tab_focus_view_caption_ru())
    answer_col, sources_col = st.columns([1.2, 0.95], gap="large") if not focus_view else (st.container(), None)
    with answer_col:
        debug = st.session_state.get("last_debug") or {}
        confidence = last.get("confidence") or {}
        confidence_level = confidence.get("level", "")
        confidence_label = confidence.get("label", "")
        if confidence_label:
            color_map = {"high": "#2e7d32", "medium": "#e65100", "low": "#c62828"}
            badge_color = color_map.get(confidence_level, "#59685f")
            st.markdown(
                f'<span style="background:{badge_color};color:#fff;border-radius:999px;padding:0.3rem 0.8rem;font-size:0.82rem;font-weight:700;">{confidence_label}</span>'
                f' <span style="color:var(--muted);font-size:0.82rem;">{confidence.get("source_count", 0)} источников, avg score: {confidence.get("avg_source_score", "n/a")}, документов: {confidence.get("unique_source_files", 0)}</span>',
                unsafe_allow_html=True,
            )
            st.caption(
                "Уверенность поиска показывает качество найденных источников. "
                "Это не вероятность правильности ответа; сверяйте вывод с фрагментами ниже."
            )
            reasons = confidence_reason_labels(confidence.get("reasons") or [])
            if reasons and confidence_level != "high":
                st.caption("Почему уверенность снижена")
                render_chip_row(reasons)
        source_badge = llm_source_badge_text(debug)
        if source_badge:
            st.caption(source_badge)
        source_notice = llm_source_privacy_notice(debug)
        if source_notice:
            st.info(source_notice)
        st.subheader("Ответ")
        rslot = st.session_state.get("qa_reinforcement")
        rid = debug.get("request_id")
        if (
            isinstance(rslot, dict)
            and rslot.get("request_id") == rid
            and rslot.get("phrase")
        ):
            st.caption(rslot["phrase"])
            st.session_state.pop("qa_reinforcement", None)
        render_longform_block(
            linkify_qa_inline_citations(last.get("answer", ""), anchor_prefix="qa-cite"),
            markdown=True,
        )
        lat_cap = answer_latency_caption(debug)
        if lat_cap:
            st.caption(lat_cap)
        if answer_latency_bucket_label_ru(debug.get("total_answer_ms")) == "долго":
            st.caption(slow_answer_scope_hint_ru())
        answer_topic = infer_topic_label_from_last_answer(last)
        topic_label = (
            f"Учить эту тему 5 минут — {answer_topic[:56]}" if answer_topic else "Учить эту тему 5 минут"
        )
        if len(topic_label) > 72:
            topic_label = topic_label[:69] + "…"
        if st.button(topic_label, key="learn_topic_from_qa", width="stretch", type="primary"):
            if "tutor_session_id" not in st.session_state:
                st.session_state["tutor_session_id"] = str(uuid.uuid4())
            qtext = (last.get("question") or "").strip()
            if qtext:
                query_text = f"Объясни тему «{answer_topic}»: {qtext}" if answer_topic else qtext
                st.session_state["tutor_pending_prompt"] = query_text
                st.session_state["tutor_pending_session_id"] = st.session_state["tutor_session_id"]
            store_qa_tutor_handoff_context(
                st.session_state,
                topic=answer_topic,
                last_question=qtext,
                answer_summary=summarize_answer_for_handoff(last),
                source="quick_answer_cta",
            )
            if answer_topic:
                st.session_state["current_topic"] = answer_topic
            st.session_state["tutor_goal_time_budget_min"] = 5
            if answer_topic:
                at = answer_topic.strip()
                st.session_state["tutor_goal_subtopic"] = at[:120] if at else None
                st.session_state["tutor_goal_desired_outcome"] = f"Разобраться с «{at[:80]}»"
            else:
                st.session_state["tutor_goal_subtopic"] = None
                st.session_state["tutor_goal_desired_outcome"] = "Короткая сессия по последнему ответу"
            st.session_state["tutor_e11_five_min_loop"] = True
            st.session_state["tutor_e11_loop_origin"] = "qa"
            st.session_state["tutor_e11_loop_active"] = True
            persist_tutor_goal_snapshot_from_session()
            st.session_state[PENDING_CURRENT_VIEW_KEY] = "Чат с тьютором"
            st.rerun()
        st.caption(qa_five_min_tutor_bridge_caption_ru())
        st.caption(qa_to_tutor_bridge_caption_ru())
        fb = st.columns([1, 1, 4])
        with fb[0]:
            if st.button("👍 Полезно", key="feedback_helpful_yes", width="stretch"):
                if post_feedback(
                    helpful=True,
                    request_id=last.get("request_id"),
                    question_preview=last.get("question"),
                ):
                    st.session_state["feedback_toast"] = "saved"
                else:
                    st.session_state["feedback_toast"] = "error"
        with fb[1]:
            if st.button("👎 Не помогло", key="feedback_helpful_no", width="stretch"):
                if post_feedback(
                    helpful=False,
                    request_id=last.get("request_id"),
                    question_preview=last.get("question"),
                ):
                    st.session_state["feedback_toast"] = "saved"
                else:
                    st.session_state["feedback_toast"] = "error"
        toast = st.session_state.pop("feedback_toast", None)
        if toast == "saved":
            st.caption("Спасибо, отзыв сохранён локально.")
        elif toast == "error":
            st.caption("Не удалось сохранить отзыв (проверьте API).")
        source_paths = source_paths_from_answer(last)
        smart_actions = st.columns(4)
        with smart_actions[0]:
            if st.button("Открыть тему по источникам", key="jump_to_topic_from_answer", width="stretch", type="secondary"):
                if source_paths and open_topic_from_paths(source_paths):
                    st.rerun()
                else:
                    st.warning(
                        "Не удалось автоматически сопоставить источники ответа с темами. Попробуйте открыть вкладку `Темы` и найти нужную тему вручную."
                    )
        with smart_actions[1]:
            if st.button("Собрать synthesis по этим источникам", key="synth_from_answer_sources", width="stretch", type="secondary"):
                if source_paths and run_synthesis_for_paths(source_paths):
                    st.rerun()
                else:
                    st.warning(
                        "Не удалось собрать конспект по найденным источникам. Попробуйте сузить выборку или перейти во вкладку `Темы`."
                    )
        with smart_actions[2]:
            if st.button("Объясни проще", key="followup_simpler", width="stretch", type="secondary"):
                st.session_state["study_mode"] = True
                st.session_state["question_draft"] = "Объясни проще и на интуитивном уровне."
                st.rerun()
        with smart_actions[3]:
            if st.button("Приведи пример", key="followup_example", width="stretch", type="secondary"):
                st.session_state["study_mode"] = True
                st.session_state["question_draft"] = "Приведи короткий практический пример."
                st.rerun()
        qa_rid = user_state.qa_resource_id(last.get("question") or "")
        study_row = st.columns([1, 1, 2])
        with study_row[0]:
            try:
                bm = user_state.has_bookmark("qa", qa_rid)
            except Exception as _exc:  # noqa: BLE001
                import logging  # noqa: BLE001

                logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                bm = False
            if st.button(
                "Снять закладку" if bm else "Закладка на ответ",
                key="qa_bookmark_toggle",
                width="stretch",
                type="secondary",
            ):
                try:
                    user_state.toggle_bookmark("qa", qa_rid)
                except Exception as _exc:  # noqa: BLE001
                    import logging  # noqa: BLE001

                    logging.getLogger(__name__).debug("! caught exception: %s", _exc)
                    pass
                st.rerun()
        with study_row[1]:
            st.caption("Quiz использует текст вопроса и ответа.")
        st.markdown("##### Самопроверка")
        qa_material = f"Вопрос:\n{last.get('question', '')}\n\nОтвет:\n{last.get('answer', '')}"
        render_quiz_panel(
            source_key="qa_answer",
            title=(last.get("question") or "")[:120],
            material=qa_material,
            min_chars=120,
        )
        suggestions = fetch_kb_suggestions(last.get("question", ""), source_paths)
        if suggestions:
            related = suggestions.get("related_topics", [])
            unexplored = suggestions.get("unexplored_documents", [])
            similar_q = suggestions.get("similar_questions", [])
            if related or unexplored or similar_q:
                st.markdown('<div class="callout" style="margin-top:0.8rem;">', unsafe_allow_html=True)
                st.markdown("#### Продолжите исследование")
                if related:
                    topic_names = [f"{t['topic_name']} ({t['unexplored_count']} ещё)" for t in related[:3]]
                    st.caption("Связанные темы")
                    render_chip_row(topic_names)
                if unexplored:
                    st.caption("Документы, которые вы ещё не исследовали")
                    render_chip_row(unexplored[:5])
                if similar_q:
                    st.caption("Похожие вопросы из истории")
                    for sq in similar_q[:2]:
                        st.markdown(f"- {sq.get('question', '')}", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

        md_parts = [
            "# Ответ из базы знаний\n\n",
            "## Вопрос\n\n",
            last.get("question", ""),
            "\n\n## Краткий ответ\n\n",
            last.get("answer", ""),
        ]
        if confidence_label:
            md_parts.extend(
                [
                    "\n\n## Уверенность поиска\n\n",
                    f"- Уровень: **{confidence_label}**\n",
                    f"- Источников: **{confidence.get('source_count', 0)}**\n",
                    f"- Документов: **{confidence.get('unique_source_files', 0)}**\n",
                    f"- Средний score: **{confidence.get('avg_source_score', 'n/a')}**\n",
                    "- Интерпретация: это качество найденных источников, не вероятность правильности ответа.\n",
                ]
            )
        md_parts.extend(
            [
                "\n\n## Источники\n\n",
                format_sources_markdown(last.get("sources") or []),
            ]
        )
        st.download_button(
            label="Скачать ответ в Markdown",
            data="".join(md_parts),
            file_name="rag_answer.md",
            mime="text/markdown",
            key="download_md",
        )
    if not focus_view and sources_col is not None:
        with sources_col:
            st.subheader("Источники")
            st.caption(qa_tab_sources_column_intro_caption_ru())
            gx_trust = graph_expansion_trust_caption_ru(st.session_state.get("last_debug") or {})
            if gx_trust:
                st.caption(gx_trust)
            render_source_cards(
                last.get("sources") or [],
                prefix="query_src",
                show_document_quiz=True,
                cite_anchor_prefix="qa-cite",
            )
    with st.expander(expert_controls_expander_label_ru(), expanded=False):
        st.caption(qa_tab_after_answer_debug_intro_caption_ru())
        render_debug_summary(st.session_state.get("last_debug") or {})
        with st.expander("Подробный журнал обработки и метрики", expanded=False):
            debug = st.session_state.get("last_debug") or {}
            st.json(debug)
            perf_cols = st.columns(2)
            with perf_cols[0]:
                if st.button("Загрузить общую статистику", key="perf_fetch"):
                    try:
                        st.session_state["flow_stats"] = fetch_json("GET", "/cache/answer-flow-stats", timeout=5)
                    except Exception as e:  # noqa: BLE001 - network/API errors handled gracefully in UI
                        st.error(format_request_error(e))
            with perf_cols[1]:
                if st.button("Сбросить статистику", key="perf_reset"):
                    try:
                        fetch_json("POST", "/cache/answer-flow-reset", timeout=5)
                        st.session_state["flow_stats"] = None
                        st.success("Сброшено")
                    except Exception as e:  # noqa: BLE001 - network/API errors handled gracefully in UI
                        st.error(format_request_error(e))
            if st.session_state.get("flow_stats"):
                st.json(st.session_state["flow_stats"])
