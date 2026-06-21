"""Hero-блок главной страницы (метрики индекса и KB overview)."""
from __future__ import annotations

from typing import Any

import streamlit as st

from app.ui.widgets import render_metric_card
from app.ui_client import load_kb_overview


def suggest_example_questions(
    *,
    documents_count: int,
    top_concepts: list[dict[str, Any]],
    topic_sizes: list[dict[str, Any]],
) -> list[str]:
    """US-3.3: до 3 стартовых вопросов из концептов/тем KB overview (без LLM)."""
    if documents_count <= 0:
        return []
    out: list[str] = []
    seen_lower: set[str] = set()

    def _push(q: str) -> None:
        q = q.strip()
        if not q or len(out) >= 3:
            return
        low = q.lower()
        if low in seen_lower:
            return
        seen_lower.add(low)
        out.append(q)

    for c in top_concepts or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if name:
            _push(
                f"Кратко объясни концепт «{name}» и где он встречается в моих материалах."
            )

    for ts in topic_sizes or []:
        if not isinstance(ts, dict):
            continue
        tn = str(ts.get("topic_name") or "").strip()
        if tn:
            _push(f"Какие главные идеи в теме «{tn}»?")

    templates = (
        "С чего лучше начать изучение моей базы знаний?",
        "Какие темы в индексе сильнее всего связаны между собой?",
        "Дай короткий обзор ключевых понятий по моим документам.",
    )
    for t in templates:
        _push(t)
        if len(out) >= 3:
            break
    return out[:3]


def render_hero(
    index_stats: dict | None,
    kb_overview: dict | None = None,
    source_readiness: dict[str, Any] | None = None,
) -> None:
    docs = index_stats.get("documents_count", 0) if index_stats else 0
    nodes = index_stats.get("nodes_count", 0) if index_stats else 0
    if kb_overview is None:
        kb_overview = load_kb_overview()
    total_topics = (kb_overview.get("total_topics") or 0) if kb_overview else 0
    top_concepts = (kb_overview.get("top_concepts") or []) if kb_overview else []

    concept_chips = ""
    if top_concepts:
        concept_chips = '<div style="margin-top:0.6rem;display:flex;flex-wrap:wrap;gap:0.35rem;">'
        for c in top_concepts[:8]:
            concept_chips += f'<span style="background:rgba(255,211,158,0.25);color:#ffd39e;border-radius:999px;padding:0.22rem 0.6rem;font-size:0.78rem;font-weight:700;">{c["name"]}</span>'
        concept_chips += "</div>"

    st.markdown(
        f"""
        <div class="hero">
            <div class="kicker">Home RAG Tutor</div>
            <h1>Личная база знаний</h1>
            <p>
                Ответы по вашим файлам и режим обучения с тьютором.
                В индексе: <strong>{docs}</strong> документов, <strong>{nodes}</strong> нод
                и <strong>{total_topics}</strong> тем.
            </p>
            {concept_chips}
        </div>
        """,
        unsafe_allow_html=True,
    )

    cols = st.columns(4, gap="large")
    metric_items = [
        ("Документов", str(docs), "в индексе"),
        ("Тем", str(total_topics), "кластеров"),
        ("Нод", str(nodes), "чанков"),
        ("Концептов", str(len(top_concepts)), "ключевых"),
    ]
    for col, (label, value, sub) in zip(cols, metric_items):
        with col:
            render_metric_card(label, value, sub)

    if source_readiness and isinstance(source_readiness, dict):
        if source_readiness.get("error"):
            st.caption(f"Диагностика корпуса: {source_readiness['error']}")
        else:
            criteria = source_readiness.get("criteria") or {}
            counts = source_readiness.get("counts") or {}
            labels_ru = {
                "text_ready": "Готов к текстовому индексу",
                "needs_ocr": "Нужен OCR / извлечение",
                "problematic": "Проблемные файлы",
            }
            lines = [
                f"- **{labels_ru.get(k, k)}**: {int(counts.get(k) or 0)} — {criteria.get(k, '')}"
                for k in ("text_ready", "needs_ocr", "problematic")
            ]
            primary = str(source_readiness.get("primary_next_action") or "").strip()
            note = str(source_readiness.get("us_2_3_note") or "").strip()
            body = "\n".join(lines)
            if primary:
                body += f"\n\n**Рекомендуемый следующий шаг:** {primary}"
            if note:
                body += f"\n\n_{note}_"
            with st.expander("Готовность файлов в data/ (до первого вопроса)", expanded=False):
                st.markdown(body)

    examples = suggest_example_questions(
        documents_count=docs,
        top_concepts=list(top_concepts) if top_concepts else [],
        topic_sizes=list(kb_overview.get("topic_sizes") or [])
        if kb_overview
        else [],
    )
    if examples:
        st.caption("Примеры вопросов по вашей базе — откроют вкладку «Быстрый ответ» с текстом запроса:")
        ex_cols = st.columns(min(3, len(examples)))
        for i, q in enumerate(examples):
            with ex_cols[i]:
                short = q if len(q) <= 48 else q[:45] + "…"
                if st.button(
                    f"Вопрос {i + 1}: {short}",
                    key=f"hero_example_q_{i}",
                    help=q,
                    width='stretch',
                    type="secondary",
                ):
                    st.session_state["question_draft"] = q
                    st.session_state["current_view"] = "Быстрый ответ"
                    st.rerun()

    if kb_overview and kb_overview.get("topic_sizes"):
        with st.expander("Карта покрытия тем", expanded=False):
            for ts in kb_overview["topic_sizes"]:
                st.caption(f"**{ts['topic_name']}** — {ts['document_count']} документов")
