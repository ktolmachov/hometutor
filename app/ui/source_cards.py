"""Карточки источников retrieval + превью файла, опционально scoped quiz по документу/теме."""
from __future__ import annotations

import streamlit as st

from app.living_konspekt_source_resolver import SourceSectionCandidate, resolve_source_section
from app.living_konspekt_video_citations import video_citation_for_candidate
from app.ui.answer_helpers import find_best_topic_for_documents
from app.ui.quiz_learning_mode_widgets import (
    render_scoped_quiz_learning_mode_select,
    scoped_quiz_learning_mode_value,
)
from app.ui.helpers import format_request_error, preview_code_language, supports_text_preview
from app.ui.scoped_quiz import render_scoped_self_check_quiz
from app.ui.session_state import set_last_studied_document
from app.ui.topics_catalog import load_topics_catalog
from app.ui_client import fetch_json


def _route_label_ru(route: object) -> str:
    """E9.5: человекочитаемый маршрут retrieval для карточки источника."""
    r = (str(route).strip() if route is not None else "") or "не указан"
    return {
        "vector_only": "векторный поиск",
        "hybrid": "гибрид (вектор + BM25)",
        "bm25_only": "ключевые слова (BM25)",
        "faq_cache": "кэш похожих вопросов (FAQ)",
    }.get(r, r)


def _score_trust_caption(score: object) -> str:
    """US-3.2: кратко объясняет, что значит score фрагмента для доверия к источнику."""
    if score is None:
        return "оценка релевантности не передана"
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "оценка поиска по этому фрагменту"
    if s >= 0.75:
        return "высокая близость к формулировке вопроса"
    if s >= 0.45:
        return "умеренная близость — сверьте цитату в файле"
    return "низкий score — фрагмент слабее остальных; при сомнении откройте источник"


def render_source_cards(
    sources: list[dict],
    *,
    prefix: str,
    show_document_quiz: bool = False,
    cite_anchor_prefix: str | None = None,
) -> None:
    _src_lm_key = f"{prefix}_scoped_quiz_lm"
    if show_document_quiz and prefix == "query_src":
        render_scoped_quiz_learning_mode_select(session_key=_src_lm_key)
    for idx, src in enumerate(sources):
        if cite_anchor_prefix:
            try:
                n = int(src.get("cite_index") or (idx + 1))
            except (TypeError, ValueError):
                n = idx + 1
            st.markdown(
                f'<span id="{cite_anchor_prefix}-{n}" style="scroll-margin-top:5rem;"></span>',
                unsafe_allow_html=True,
            )
        path = src.get("relative_path") or src.get("file_name") or "unknown"
        page = src.get("page")
        score = src.get("score")
        snippet = (src.get("text") or "").strip()
        rel = src.get("relative_path")
        can_preview = bool(rel and supports_text_preview(rel))
        open_key = f"{prefix}_src_preview_open_{idx}"
        body_key = f"{prefix}_src_preview_body_{idx}"
        err_key = f"{prefix}_src_preview_err_{idx}"

        route = src.get("route")
        rank_reason = (src.get("rank_reason") or "").strip() or _score_trust_caption(score)
        route_lab = _route_label_ru(route)
        line_start = src.get("line_start")
        line_end = src.get("line_end")
        lines_meta = ""
        if line_start is not None or line_end is not None:
            try:
                ls = int(line_start) if line_start is not None else None
                le = int(line_end) if line_end is not None else None
            except (TypeError, ValueError):
                ls = None
                le = None
            if ls and le and le >= ls:
                lines_meta = f" | lines: {ls}-{le}"
            elif ls:
                lines_meta = f" | line: {ls}"
        st.markdown(
            f"""
            <div class="source-card">
                <div class="source-path">{path}</div>
                <div class="source-meta">page: {page} | маршрут: {route_lab} | score: {score} — {rank_reason}{lines_meta}</div>
                <div>{snippet[:260] if snippet else "Для этого источника пока нет текстового preview. При необходимости откройте сам файл."}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if show_document_quiz and rel and prefix == "query_src":
            _render_living_konspekt_source_action(src, idx, prefix)
            dqk = f"{prefix}_scoped_quiz_{idx}"
            _api_lm = scoped_quiz_learning_mode_value(_src_lm_key)
            col_doc, col_top = st.columns([1, 1])
            with col_doc:
                if st.button("Тест по этому документу", key=f"{dqk}_btn", width='stretch'):
                    try:
                        set_last_studied_document(rel)
                        data = fetch_json(
                            "POST",
                            "/quiz/generate",
                            timeout=120,
                            json={
                                "scope": "document",
                                "identifier": rel,
                                "num_questions": 6,
                                "difficulty": "adaptive",
                                "learning_mode": _api_lm,
                            },
                        )
                        st.session_state[dqk] = data.get("quiz") or {}
                        st.session_state.pop(f"{dqk}_err", None)
                    except Exception as e:
                        st.session_state[f"{dqk}_err"] = format_request_error(e)
                    st.rerun()
            topics_catalog = load_topics_catalog(force=False)
            best = find_best_topic_for_documents([rel], topics_catalog)
            with col_top:
                if best and best.get("topic_id"):
                    tlab = (best.get("topic_name") or "тема")[:40]
                    if st.button(
                        f"Тест по теме «{tlab}»",
                        key=f"{dqk}_topic_btn",
                        width='stretch',
                    ):
                        try:
                            data = fetch_json(
                                "POST",
                                "/quiz/generate",
                                timeout=120,
                                json={
                                    "scope": "topic",
                                    "identifier": best["topic_id"],
                                    "num_questions": 6,
                                    "difficulty": "adaptive",
                                    "learning_mode": _api_lm,
                                },
                            )
                            st.session_state[f"{dqk}_topic"] = data.get("quiz") or {}
                            st.session_state.pop(f"{dqk}_topic_err", None)
                        except Exception as e:
                            st.session_state[f"{dqk}_topic_err"] = format_request_error(e)
                        st.rerun()
                else:
                    st.caption("Тема каталога не сопоставлена — откройте «Темы» вручную.")
            err_d = st.session_state.pop(f"{dqk}_err", None)
            if err_d:
                st.warning(err_d)
            err_t = st.session_state.pop(f"{dqk}_topic_err", None)
            if err_t:
                st.warning(err_t)
            pdata = st.session_state.get(dqk)
            if isinstance(pdata, dict) and pdata.get("questions"):
                render_scoped_self_check_quiz(
                    pdata["questions"],
                    source_key=dqk,
                    quiz_meta=pdata,
                )
            pdata_t = st.session_state.get(f"{dqk}_topic")
            if isinstance(pdata_t, dict) and pdata_t.get("questions"):
                st.markdown("**Тест по связанной теме**")
                render_scoped_self_check_quiz(
                    pdata_t["questions"],
                    source_key=f"{dqk}_topic",
                    quiz_meta=pdata_t,
                )

        if not can_preview:
            continue

        is_open = bool(st.session_state.get(open_key))
        btn_label = "Скрыть содержимое файла" if is_open else "Показать содержимое файла"
        if st.button(btn_label, key=f"{prefix}_src_preview_btn_{idx}"):
            if is_open:
                st.session_state[open_key] = False
                st.session_state.pop(body_key, None)
                st.session_state.pop(err_key, None)
            else:
                try:
                    content = fetch_json("GET", "/content/file", params={"relative_path": rel}, timeout=30)
                    st.session_state[body_key] = content.get("content", "")
                    st.session_state.pop(err_key, None)
                    st.session_state[open_key] = True
                    set_last_studied_document(rel)
                except Exception as e:
                    st.session_state[err_key] = format_request_error(e)
                    st.session_state[open_key] = True

        if st.session_state.get(open_key):
            if err_key in st.session_state:
                st.error(f"Не удалось загрузить файл: {st.session_state[err_key]}")
            elif body_key in st.session_state:
                lang = preview_code_language(rel) or "text"
                st.code(st.session_state[body_key], language=lang)


def _render_living_konspekt_source_action(src: dict, idx: int, prefix: str) -> None:
    resolution = resolve_source_section(src)
    action_key = f"{prefix}_lk_add_{idx}"
    if resolution.status == "unavailable":
        st.caption(resolution.message)
        return

    if resolution.status == "single" and resolution.single is not None:
        candidate = resolution.single
        if st.button("➕ В Живой конспект", key=action_key, width="stretch"):
            _add_candidate_to_living_konspekt(candidate)
            st.rerun()
        st.caption(_candidate_caption(candidate))
        _render_source_video_citation(candidate, key=f"{action_key}_video")
        return

    if not resolution.candidates:
        st.caption(resolution.message)
        return

    with st.expander("➕ В Живой конспект", expanded=False):
        st.caption(resolution.message)
        options = list(resolution.candidates)
        selected = st.selectbox(
            "Раздел",
            options,
            format_func=_candidate_label,
            key=f"{action_key}_choice",
        )
        _render_source_video_citation(selected, key=f"{action_key}_video_choice")
        if st.button("Добавить выбранный раздел", key=f"{action_key}_confirm", width="stretch"):
            _add_candidate_to_living_konspekt(selected)
            st.rerun()


def _add_candidate_to_living_konspekt(candidate: SourceSectionCandidate) -> None:
    from app.ui.living_konspekt_view import add_section_to_workbench

    added = add_section_to_workbench(candidate.section)
    if added:
        st.toast("Раздел добавлен в Живой конспект.", icon="📚")
    else:
        st.toast("Этот раздел уже есть в Живом конспекте.", icon="📚")


def _candidate_label(candidate: SourceSectionCandidate) -> str:
    section = candidate.section
    return f"{section.heading_text} · строки {section.line_start}-{section.line_end}"


def _candidate_caption(candidate: SourceSectionCandidate) -> str:
    return f"{_candidate_label(candidate)} · {candidate.reason} · score {candidate.score:.1f}"


def _render_source_video_citation(candidate: SourceSectionCandidate, *, key: str) -> None:
    resolution = video_citation_for_candidate(candidate)
    if resolution.status != "available" or resolution.citation is None:
        st.caption(f"🎬 Доверенной видео-цитаты нет: {resolution.message}")
        return

    citation = resolution.citation
    _track_video_citation_shown_once(candidate, key)
    label = f"🎬 Смотреть с {citation.timestamp_label}: {citation.video_title}"
    if citation.url:
        st.link_button(label, citation.url, width="stretch")
    else:
        st.caption(f"{label} · локальное видео откройте в Живом конспекте")
    st.caption(f"{citation.heading} · {citation.source_label}")


def _track_video_citation_shown_once(candidate: SourceSectionCandidate, key: str) -> None:
    event_key = f"{key}_shown"
    if st.session_state.get(event_key):
        return
    st.session_state[event_key] = True
    try:
        from app.ui_events import track_event

        track_event(
            "ask_lecturer_video_citation_shown",
            {
                "heading": candidate.section.heading_text,
                "source": str(candidate.section.source_abs.name),
            },
        )
    except Exception:  # noqa: BLE001 - UI analytics must not block source-card rendering
        pass
