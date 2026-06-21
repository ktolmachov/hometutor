"""Extracted data-view tabs: search, history, metrics, explain."""

import pandas as pd
import streamlit as st

from app.ui.helpers import (
    format_request_error as _format_request_error,
    preview_code_language as _preview_code_language,
    show_file_error as _show_file_error,
    supports_text_preview as _supports_text_preview,
)
from app.ui.kb_fetch import fetch_kb_search as _fetch_kb_search
from app.ui.longform import render_longform_block as _render_longform_block
from app.ui.quiz_panel import render_quiz_panel as _render_quiz_panel
from app.ui.source_cards import render_source_cards as _render_source_cards
from app.ui.widgets import render_panel_header as _render_panel_header
from app.ui_client import fetch_json as _fetch_json


def _render_search_tab():
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    _render_panel_header("Поиск по базе знаний", "Единый поиск по документам, темам и концептам — без генерации ответа")
    query = st.text_input(
        "Поиск",
        placeholder="Например: retrieval, security, hybrid, prompt injection",
        key="kb_search_query",
    )
    if query and query.strip():
        results = _fetch_kb_search(query.strip())
        if results:
            result_cols = st.columns(3, gap="large")
            topics = results.get("topics", [])
            documents = results.get("documents", [])
            concepts = results.get("concepts", [])

            with result_cols[0]:
                st.markdown(f"#### Темы ({len(topics)})")
                for t in topics[:8]:
                    st.markdown(
                        f"""
                        <div class="topic-card">
                            <div class="source-path">{t['topic_name']}</div>
                            <div class="source-meta">{t['document_count']} документов</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            with result_cols[1]:
                st.markdown(f"#### Документы ({len(documents)})")
                for d in documents[:10]:
                    path = d.get("relative_path") or d.get("file_name") or ""
                    summary_preview = (d.get("summary") or "")[:120]
                    st.markdown(
                        f"""
                        <div class="doc-card">
                            <div class="doc-path">{path}</div>
                            <div class="doc-meta">тема: {d.get('topic_name', 'n/a')}</div>
                            <div>{summary_preview}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            with result_cols[2]:
                st.markdown(f"#### Концепты ({len(concepts)})")
                for c in concepts[:8]:
                    st.markdown(
                        f"""
                        <div class="topic-card">
                            <div class="source-path">{c['name']}</div>
                            <div class="source-meta">в темах: {', '.join(c.get('topics', [])[:2])}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            if not topics and not documents and not concepts:
                st.info("По этому запросу ничего не найдено. Попробуйте более короткую формулировку или один ключевой термин.")
        else:
            st.info("Не удалось выполнить поиск. Проверьте, что API запущен и индекс доступен.")
    else:
        st.markdown(
            """
            <div class="callout">
                <div class="panel-title">Навигация по знаниям</div>
                <div class="panel-subtitle">Ищите по документам, темам и ключевым концептам</div>
                <div>Введите ключевое слово или фразу, чтобы найти связанные документы, темы и концепты в вашей базе знаний. Это не Q&A — здесь вы находите <em>где</em> искать, а не получаете ответ.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _load_history(*, q: str, limit: int, since: str, until: str, topic: str):
    params: dict = {"limit": limit}
    if q.strip():
        params["q"] = q.strip()
    if since.strip():
        params["since"] = since.strip()
    if until.strip():
        params["until"] = until.strip()
    if topic.strip():
        params["topic"] = topic.strip()
    return _fetch_json("GET", "/history", timeout=15, params=params)


def _render_history_tab():
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    _render_panel_header(
        "История вопросов",
        "Сохранённые ответы API (logs/history.jsonl): поиск по тексту, периоду и пути к источникам.",
    )
    filt_cols = st.columns([2, 1, 1, 1, 1])
    with filt_cols[0]:
        hq = st.text_input("Поиск по вопросу или ответу", key="history_q", placeholder="ключевые слова")
    with filt_cols[1]:
        since_s = st.text_input("С даты (YYYY-MM-DD)", key="history_since", placeholder="опционально")
    with filt_cols[2]:
        until_s = st.text_input("По дату (YYYY-MM-DD)", key="history_until", placeholder="опционально")
    with filt_cols[3]:
        topic_s = st.text_input("Путь / папка / тема", key="history_topic", placeholder="фильтр по источникам")
    with filt_cols[4]:
        limit_n = st.number_input("Лимит", min_value=1, max_value=200, value=30, step=1, key="history_limit")

    if st.button("Обновить список", key="history_refresh", type="primary"):
        try:
            st.session_state["history_remote"] = _load_history(
                q=hq,
                limit=int(limit_n),
                since=since_s,
                until=until_s,
                topic=topic_s,
            )
            st.session_state.pop("history_remote_error", None)
        except Exception as e:
            st.session_state["history_remote"] = None
            st.session_state["history_remote_error"] = _format_request_error(e)

    err = st.session_state.get("history_remote_error")
    if err:
        st.error(err)
        st.session_state["history_remote_error"] = None

    data = st.session_state.get("history_remote")
    if data is None:
        st.info("Нажмите «Обновить список», чтобы загрузить историю с сервера.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    items = data.get("items") or []
    total = data.get("total", len(items))
    st.caption(f"Показано до {len(items)} записей, отфильтровано всего: {total}")
    if not items:
        st.warning("Записей не найдено. Измените фильтры или задайте вопрос на вкладке «Быстрый ответ» — ответы сохраняются в историю.")
    for hidx, entry in enumerate(items):
        ts = entry.get("timestamp", "")[:19].replace("T", " ")
        qtext = entry.get("question") or ""
        title = f"{ts} UTC — {qtext[:80]}{'…' if len(qtext) > 80 else ''}"
        with st.expander(title, expanded=False):
            st.markdown(f"**Вопрос:** {qtext}")
            ans = entry.get("answer") or ""
            st.markdown("**Ответ:**")
            st.markdown(ans if ans else "_(пусто)_")
            iv = entry.get("index_version")
            if iv:
                st.caption(f"index_version: `{iv}`")
            conf = entry.get("confidence") or {}
            if conf.get("level"):
                st.caption(f"Уверенность: **{conf.get('level')}**")
            rid = entry.get("request_id")
            if rid:
                st.caption(f"request_id: `{rid}`")
            srcs = entry.get("sources") or []
            if srcs:
                st.markdown("**Источники**")
                _render_source_cards(srcs, prefix=f"hist_{hidx}")
            hist_material = f"Вопрос:\n{qtext}\n\nОтвет:\n{ans}"
            st.markdown("##### Самопроверка по записи")
            _render_quiz_panel(
                source_key=f"hist_quiz_{hidx}",
                title=qtext[:120],
                material=hist_material,
                min_chars=120,
            )
    st.markdown("</div>", unsafe_allow_html=True)


def _render_metrics_tab():
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    _render_panel_header(
        "Метрики",
        "Тренды latency, стоимости и качества по дням и неделям (данные из `metrics_store.jsonl`, кэш агрегатов в SQLite).",
    )
    limit = st.number_input(
        "Последние N событий `request` для разбиения по времени",
        min_value=100,
        max_value=100000,
        value=20000,
        step=500,
        key="metrics_limit_events",
    )
    if st.button("Загрузить / обновить", key="metrics_refresh", type="primary"):
        try:
            st.session_state["metrics_dashboard"] = _fetch_json(
                "GET",
                "/metrics/dashboard",
                timeout=60,
                params={"limit_events": int(limit)},
            )
            st.session_state.pop("metrics_dashboard_error", None)
        except Exception as e:
            st.session_state["metrics_dashboard"] = None
            st.session_state["metrics_dashboard_error"] = _format_request_error(e)

    err = st.session_state.get("metrics_dashboard_error")
    if err:
        st.error(err)
        st.session_state["metrics_dashboard_error"] = None

    data = st.session_state.get("metrics_dashboard")
    if data is None:
        st.info("Нажмите «Загрузить / обновить», чтобы вызвать `GET /metrics/dashboard`.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    summary = data.get("summary") or {}
    if summary.get("source") == "empty_store":
        st.warning("Нет `metrics_store` на сервере или файл пуст. Задайте вопросы через API/UI — появятся события запросов.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.caption(
        f"Запросов в окне: **{summary.get('events_window_requests', 0)}** · "
        f"лимит событий: **{summary.get('limit_events', '—')}** · кэш: **{summary.get('source', '—')}**"
    )
    daily = data.get("daily") or []
    weekly = data.get("weekly") or []

    if daily:
        st.subheader("По дням (UTC)")
        rows = []
        for b in daily:
            lid = b.get("latency_ms") or {}
            cost = b.get("estimated_cost_usd") or {}
            qual = b.get("quality") or {}
            rows.append(
                {
                    "day": b.get("bucket_id"),
                    "p95_answer_ms": lid.get("p95_total_answer_ms"),
                    "p95_pipeline_ms": lid.get("p95_pipeline_ms"),
                    "cost_usd_total": cost.get("total"),
                    "quality_pass_rate": qual.get("pass_rate"),
                    "requests": b.get("request_count"),
                }
            )
        df = pd.DataFrame(rows)
        if not df.empty and df["day"].notna().any():
            chart_df = df.set_index("day")
            st.markdown("**Latency p95 (мс)**")
            st.line_chart(chart_df[["p95_answer_ms", "p95_pipeline_ms"]], height=220)
            st.markdown("**Стоимость запросов (USD, сумма за день)**")
            st.line_chart(chart_df[["cost_usd_total"]], height=200)
            qcol = chart_df["quality_pass_rate"].dropna()
            if not qcol.empty:
                st.markdown("**Доля прошедших deterministic quality** (где проверки были)")
                st.line_chart(chart_df[["quality_pass_rate"]].dropna(), height=200)
            judge_keys = set()
            for b in daily:
                ja = b.get("judge_avg_scores")
                if isinstance(ja, dict):
                    judge_keys.update(ja.keys())
            if judge_keys:
                st.markdown("**Средние оценки async judge** (если включён)")
                jrows = []
                for b in daily:
                    ja = b.get("judge_avg_scores") if isinstance(b.get("judge_avg_scores"), dict) else {}
                    row = {"day": b.get("bucket_id")}
                    for k in sorted(judge_keys):
                        row[k] = ja.get(k)
                    jrows.append(row)
                jdf = pd.DataFrame(jrows).set_index("day")
                st.line_chart(jdf, height=220)
            with st.expander("Таблица по дням"):
                st.dataframe(df, width='stretch')
    else:
        st.info("Пока нет дневных агрегатов — проверьте, что у событий есть корректный `timestamp`.")

    if weekly:
        st.subheader("По неделям (ISO)")
        wrows = []
        for b in weekly:
            lid = b.get("latency_ms") or {}
            cost = b.get("estimated_cost_usd") or {}
            wrows.append(
                {
                    "week": b.get("bucket_id"),
                    "p95_answer_ms": lid.get("p95_total_answer_ms"),
                    "cost_usd_total": cost.get("total"),
                    "requests": b.get("request_count"),
                }
            )
        wdf = pd.DataFrame(wrows)
        if not wdf.empty and wdf["week"].notna().any():
            idx = wdf.set_index("week")
            st.markdown("**Недели: latency p95 (мс)**")
            st.line_chart(idx[["p95_answer_ms"]], height=200)
            st.markdown("**Недели: стоимость (USD)**")
            st.line_chart(idx[["cost_usd_total"]], height=200)

    with st.expander("Knowledge workflow (конверсии и trace)"):
        st.caption(
            "События из UI: ответ с источниками → открытие темы / synthesis, сценарии во вкладке «Темы». "
            "Хранятся в `metrics_store.jsonl` (`event_type= knowledge_workflow`)."
        )
        if st.button("Загрузить /metrics/knowledge-workflow", key="kw_metrics_refresh", type="secondary"):
            try:
                st.session_state["kw_workflow_metrics"] = _fetch_json(
                    "GET",
                    "/metrics/knowledge-workflow",
                    timeout=30,
                    params={"limit_events": int(limit)},
                )
                st.session_state.pop("kw_workflow_metrics_error", None)
            except Exception as e:
                st.session_state["kw_workflow_metrics"] = None
                st.session_state["kw_workflow_metrics_error"] = _format_request_error(e)
        err_kw = st.session_state.get("kw_workflow_metrics_error")
        if err_kw:
            st.error(err_kw)
            st.session_state["kw_workflow_metrics_error"] = None
        km = st.session_state.get("kw_workflow_metrics")
        if km:
            st.json(km)
        else:
            st.caption("Нажмите «Загрузить», чтобы увидеть агрегаты по последним событиям.")
    st.markdown("</div>", unsafe_allow_html=True)


def _render_explain_tab():
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    _render_panel_header("Объяснить файл", "Когда уже знаете нужный путь и хотите быстро получить human-readable объяснение одного документа")
    explain_relative_path = st.text_input(
        "Относительный путь внутри data/",
        placeholder="Например: docs/topic/note.md",
        key="explain_relative_path",
    )
    if st.button("Объяснить файл", key="explain_btn"):
        if not explain_relative_path.strip():
            st.warning("Укажите относительный путь файла внутри `data/`, например `lectures/topic.md`.")
        else:
            try:
                data = _fetch_json("GET", "/explain/file", timeout=120, params={"relative_path": explain_relative_path})
                st.subheader("Объяснение")
                _render_longform_block(data.get("explanation", ""), markdown=True)
                if _supports_text_preview(explain_relative_path):
                    st.subheader("Фрагмент файла")
                    frag_lang = _preview_code_language(explain_relative_path.strip()) or "text"
                    st.code(data.get("content_preview", ""), language=frag_lang)
            except Exception as e:
                _show_file_error("Ошибка объяснения файла", e)
    st.markdown("</div>", unsafe_allow_html=True)
