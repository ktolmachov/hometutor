"""Пути к источникам из ответа, переход к теме/synthesis из Q&A."""
from __future__ import annotations

import re

import streamlit as st

from app.ui.session_state import set_last_studied_document
from app.ui.topics_catalog import load_topics_catalog
from app.ui_client import fetch_json, post_knowledge_workflow


def source_paths_from_answer(answer_payload: dict | None) -> list[str]:
    if not answer_payload:
        return []
    seen = set()
    result = []
    for src in answer_payload.get("sources") or []:
        path = src.get("relative_path") or src.get("file_name")
        if not path or path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def linkify_qa_inline_citations(text: str, *, anchor_prefix: str = "qa-cite") -> str:
    """US-11.1: маркеры [n] в markdown-ссылки на якоря карточек источников."""

    def repl(m: re.Match[str]) -> str:
        n = m.group(1)
        return f"[\\[{n}\\]](#{anchor_prefix}-{n})"

    return re.sub(r"\[(\d+)\]", repl, text or "")


def answer_latency_bucket_label_ru(total_answer_ms: object) -> str | None:
    """E9.5/E9.6: тот же порог, что в query_tab — для подсказки при «долго»."""
    if total_answer_ms is None:
        return None
    try:
        m = float(total_answer_ms)
    except (TypeError, ValueError):
        return None
    if m < 2000.0:
        return "быстро"
    if m < 8000.0:
        return "нормально"
    return "долго"


def slow_answer_scope_hint_ru() -> str:
    """E9.6 / US-3.1: одна строка без обещаний про p95."""
    return (
        "Совет: сузьте область поиска — папку, конкретный файл или тему в боковой панели — ответ обычно становится быстрее."
    )


def format_sources_markdown(sources: list[dict] | None) -> str:
    lines: list[str] = []
    for src in sources or []:
        path = src.get("relative_path") or src.get("file_name") or "unknown"
        score = src.get("score")
        page = src.get("page")
        meta = []
        if page is not None:
            meta.append(f"page: {page}")
        if score is not None:
            meta.append(f"score: {score}")
        meta_str = f" ({', '.join(meta)})" if meta else ""
        lines.append(f"- `{path}`{meta_str}\n")
    return "".join(lines)


def find_best_topic_for_documents(document_paths: list[str], topics_catalog: dict | None):
    if not document_paths or not topics_catalog:
        return None
    wanted = set(document_paths)
    best_topic = None
    best_score = 0
    for topic in topics_catalog.get("topics", []):
        topic_docs = {
            doc.get("relative_path") or doc.get("file_name")
            for doc in topic.get("documents", [])
        }
        score = len(wanted & topic_docs)
        if score > best_score:
            best_score = score
            best_topic = topic
    return best_topic if best_score > 0 else None


def open_topic_from_paths(document_paths: list[str]) -> bool:
    topics_catalog = load_topics_catalog(force=False)
    best_topic = find_best_topic_for_documents(document_paths, topics_catalog)
    if best_topic is None:
        post_knowledge_workflow(
            "answer_to_topic_failed",
            payload={"reason": "no_matching_topic"},
        )
        return False
    if document_paths:
        set_last_studied_document(document_paths[0])
    st.session_state["active_topic_id"] = best_topic["topic_id"]
    selection_key = f"topic_docs_{best_topic['topic_id']}"
    topic_documents = [
        doc.get("relative_path") or doc.get("file_name")
        for doc in best_topic.get("documents", [])
    ]
    st.session_state[selection_key] = [path for path in document_paths if path in topic_documents] or topic_documents
    st.session_state["current_view"] = "Темы"
    ws = list(st.session_state[selection_key])
    post_knowledge_workflow(
        "answer_to_topic_open",
        {
            "topic_id": best_topic["topic_id"],
            "topic_name": best_topic.get("topic_name"),
            "working_set_paths": ws,
            "documents_used_count": len(ws),
            "selection_manually_adjusted": sorted(set(ws)) != sorted(set(topic_documents)),
        },
    )
    return True


def run_synthesis_for_paths(document_paths: list[str], topic_name: str | None = None) -> bool:
    if not document_paths:
        return False
    set_last_studied_document(document_paths[0])
    topics_catalog = load_topics_catalog(force=False)
    best_topic = find_best_topic_for_documents(document_paths, topics_catalog)
    topic_documents: list[str] = []
    if best_topic is not None:
        st.session_state["active_topic_id"] = best_topic["topic_id"]
        topic_name = best_topic["topic_name"]
        selection_key = f"topic_docs_{best_topic['topic_id']}"
        topic_documents = [
            doc.get("relative_path") or doc.get("file_name")
            for doc in best_topic.get("documents", [])
        ]
        st.session_state[selection_key] = [path for path in document_paths if path in topic_documents] or topic_documents
    trace = {
        "topic_id": best_topic["topic_id"] if best_topic else None,
        "topic_name": topic_name,
        "working_set_paths": list(document_paths),
        "synthesis_launch_method": "from_answer",
        "documents_used_count": len(document_paths),
        "selection_manually_adjusted": bool(
            topic_documents and sorted(set(document_paths)) != sorted(set(topic_documents))
        ),
    }
    post_knowledge_workflow("answer_synthesis_from_answer_start", trace)
    try:
        result = fetch_json(
            "POST",
            "/synthesize",
            timeout=120,
            json={"topic": topic_name, "documents": document_paths},
        )
    except Exception as _exc:  # noqa: BLE001
        import logging  # noqa: BLE001
        logging.getLogger(__name__).debug("! caught exception: %s", _exc)
        post_knowledge_workflow("answer_synthesis_from_answer_failed", trace)
        return False
    result["selection_mode"] = "selected_documents"
    result["selected_documents"] = document_paths
    st.session_state["last_synthesis"] = result
    st.session_state["current_view"] = "Темы"
    post_knowledge_workflow(
        "answer_synthesis_from_answer_complete",
        {
            **trace,
            "documents_used_count": len(document_paths),
        },
    )
    return True
