"""Подвкладка «Конспект» на вкладке «Темы» (P5c split)."""

from __future__ import annotations

import streamlit as st

from app import user_state
from app.ui.anki_export import (
    anki_apkg_from_pairs,
    anki_tsv_from_pairs,
    synthesis_sections_for_anki,
)
from app.ui.answer_helpers import format_sources_markdown
from app.ui.longform import render_longform_block
from app.ui.print_view import open_print_view
from app.ui.quiz_panel import render_quiz_panel
from app.ui.source_cards import render_source_cards
from app.ui.widgets import render_chip_row


def render_topics_synthesis_subtab(*, selected_topic: dict, iv: str | None) -> None:
    st.markdown("#### Конспект")
    synthesis = st.session_state.get("last_synthesis")
    if isinstance(synthesis, dict) and synthesis.get("topic") == selected_topic["topic_name"]:
        mode = "вся тема" if synthesis.get("selection_mode") == "topic" else "выбранные документы"
        st.caption(f"Режим synthesis: {mode}")
        coverage = synthesis.get("coverage") or {}
        if coverage.get("total"):
            ratio_pct = round(coverage.get("ratio", 0) * 100)
            cov_color = "#2e7d32" if ratio_pct >= 80 else "#e65100" if ratio_pct >= 40 else "#c62828"
            st.markdown(
                f'<span style="background:{cov_color};color:#fff;border-radius:999px;padding:0.25rem 0.7rem;font-size:0.82rem;font-weight:700;">'
                f'Покрытие: {coverage.get("covered", 0)} из {coverage["total"]} документов ({ratio_pct}%)</span>',
                unsafe_allow_html=True,
            )
            missing = coverage.get("missing", [])
            if missing:
                st.caption(f"В этот конспект не вошли: {', '.join(missing[:5])}")
        cov_syn = synthesis.get("coverage") or {}
        if cov_syn.get("ratio") is not None:
            if st.button(
                "Записать покрытие конспекта в прогресс темы",
                key=f"synth_cov_apply_{selected_topic['topic_id']}",
                width="stretch",
                type="secondary",
            ):
                try:
                    user_state.upsert_reading_status(
                        resource_type="topic",
                        resource_id=user_state.topic_resource_id(selected_topic["topic_id"]),
                        progress=float(cov_syn["ratio"]),
                        display_title=f"Тема «{selected_topic['topic_name']}»",
                        index_version=iv or None,
                    )
                except Exception as exc:
                    st.error(str(exc))
                else:
                    st.success("Прогресс обновлён из покрытия конспекта")
                    st.rerun()
        if synthesis.get("selected_documents"):
            render_chip_row(synthesis["selected_documents"])
        render_longform_block(synthesis.get("summary", ""), markdown=True)
        anki_pairs = synthesis_sections_for_anki(
            synthesis,
            selected_topic.get("topic_name") or "Synthesis",
        )
        synth_deck_title = f"Synthesis::{selected_topic.get('topic_name') or selected_topic['topic_id']}"
        synth_apkg_bytes, synth_apkg_error = anki_apkg_from_pairs(synth_deck_title, anki_pairs)
        synth_action_row = st.columns(3)
        with synth_action_row[0]:
            if st.button("Печать/чистый вид", key=f"print_synthesis_{selected_topic['topic_id']}", width="stretch", type="secondary"):
                export_md = "".join(
                    [
                        f"# Конспект: {synthesis.get('topic', selected_topic['topic_name'])}\n\n",
                        f"**Режим:** {mode}\n\n",
                        "## Конспект\n\n",
                        synthesis.get("summary", ""),
                        "\n\n## Источники\n\n",
                        format_sources_markdown(synthesis.get("sources") or []),
                    ]
                )
                open_print_view(
                    title=f"Конспект: {synthesis.get('topic', selected_topic['topic_name'])}",
                    subtitle="Чистый вид для чтения, печати или спокойного разбора темы.",
                    body_md=synthesis.get("summary", ""),
                    export_md=export_md,
                    documents=synthesis.get("selected_documents") or [
                        doc.get("relative_path") or doc.get("file_name") or "document"
                        for doc in synthesis.get("documents") or []
                    ],
                    sources=synthesis.get("sources") or [],
                )
                st.rerun()
        with synth_action_row[1]:
            st.download_button(
                "Anki TSV",
                data=anki_tsv_from_pairs(anki_pairs),
                file_name=f"synthesis_{selected_topic['topic_id']}.tsv",
                mime="text/tab-separated-values",
                width="stretch",
                key=f"synth_anki_tsv_{selected_topic['topic_id']}",
                disabled=not anki_pairs,
            )
        with synth_action_row[2]:
            st.download_button(
                "Anki APKG",
                data=synth_apkg_bytes or b"",
                file_name=f"synthesis_{selected_topic['topic_id']}.apkg",
                mime="application/octet-stream",
                width="stretch",
                key=f"synth_anki_apkg_{selected_topic['topic_id']}",
                disabled=not anki_pairs or synth_apkg_bytes is None,
            )
        if synth_apkg_error:
            st.caption(synth_apkg_error)
        st.markdown("##### Самопроверка (конспект)")
        synth_quiz_text = (synthesis.get("summary") or "") + "\n\n" + format_sources_markdown(
            synthesis.get("sources") or []
        )
        render_quiz_panel(
            source_key=f"topics_synth_{selected_topic['topic_id']}",
            title=f"Конспект: {selected_topic['topic_name']}",
            material=synth_quiz_text,
        )
        if synthesis.get("sources"):
            st.markdown("---")
            render_source_cards(synthesis["sources"], prefix="topic_src")
    else:
        st.markdown(
            """
            <div class="callout">
                <div class="panel-title">Начните с темы</div>
                <div class="panel-subtitle">Подходит для длинных тем, лекций и ручной сборки контекста</div>
                <div><strong>1.</strong> Выберите тему слева.</div>
                <div><strong>2.</strong> Посмотрите документы и при необходимости сузьте выборку.</div>
                <div><strong>3.</strong> Соберите конспект по теме или по выбранным документам.</div>
                <div><strong>4.</strong> Если хотите учиться пошагово, переходите в «План обучения» или возвращайтесь в чат с тьютором.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
