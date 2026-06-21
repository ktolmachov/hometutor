"""Фильтрация и дедупликация тем для вкладки «Темы» (P5c split)."""

from __future__ import annotations

from copy import deepcopy
from pathlib import PurePosixPath


def _normalize_rel_path(value: object) -> str:
    return str(value or "").strip().replace("\\", "/")


def _path_in_folder(path: str, folder_rel: str) -> bool:
    normalized_path = _normalize_rel_path(path)
    normalized_folder = _normalize_rel_path(folder_rel).strip("/")
    if not normalized_path or not normalized_folder:
        return False
    return normalized_path == normalized_folder or normalized_path.startswith(f"{normalized_folder}/")


def _doc_type_from_path(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower().lstrip(".")
    return suffix or "document"


def _fallback_course_topic(active_scope: dict, source_paths: set[str]) -> dict | None:
    if not source_paths:
        return None
    folder_rel = _normalize_rel_path(active_scope.get("folder_rel")).strip("/")
    title = str(active_scope.get("title") or folder_rel or "Активный курс").strip()
    topic_id = str(active_scope.get("id") or folder_rel or "active_course").strip()
    documents = [
        {
            "doc_id": path,
            "relative_path": path,
            "file_name": PurePosixPath(path).name,
            "folder_name": folder_rel,
            "summary": "Summary появится после обогащения каталога; документ уже доступен в активном курсе.",
            "doc_type": _doc_type_from_path(path),
            "difficulty": None,
            "key_concepts": [],
        }
        for path in sorted(source_paths)
    ]
    return {
        "topic_id": f"course_{topic_id}",
        "topic_name": title,
        "document_count": len(documents),
        "key_concepts": [],
        "documents": documents,
    }


def filter_topics_by_active_scope(topics: list, active_scope: dict | None) -> list:
    """Return topic copies limited to the active course source paths/folder."""
    if not active_scope:
        return list(topics)

    source_paths = {
        _normalize_rel_path(path)
        for path in active_scope.get("source_paths") or []
        if _normalize_rel_path(path)
    }
    folder_rel = _normalize_rel_path(active_scope.get("folder_rel")).strip("/")
    scoped_topics: list = []

    for topic in topics:
        documents = topic.get("documents") or []
        scoped_documents = []
        for document in documents:
            rel_path = _normalize_rel_path(document.get("relative_path") or document.get("file_name"))
            if not rel_path:
                continue
            if source_paths:
                if rel_path not in source_paths:
                    continue
            elif not _path_in_folder(rel_path, folder_rel):
                continue
            scoped_documents.append(document)

        if not scoped_documents:
            continue

        scoped_topic = deepcopy(topic)
        scoped_topic["documents"] = scoped_documents
        scoped_topic["document_count"] = len(scoped_documents)
        scoped_topics.append(scoped_topic)

    if not scoped_topics:
        fallback_topic = _fallback_course_topic(active_scope, source_paths)
        if fallback_topic is not None:
            scoped_topics.append(fallback_topic)

    return scoped_topics


def filter_topics_by_search(topics: list, search_query: str) -> list:
    q = (search_query or "").strip().lower()
    if not q:
        return list(topics)
    filtered: list = []
    for topic in topics:
        haystack = " ".join(
            [
                topic.get("topic_name", ""),
                " ".join(topic.get("key_concepts") or []),
                " ".join((doc.get("relative_path") or "") for doc in topic.get("documents", [])),
            ]
        ).lower()
        if q not in haystack:
            continue
        filtered.append(topic)
    return filtered


def dedupe_topics_by_id(filtered_topics: list) -> list:
    """Clustering/catalog may repeat the same topic_id; Streamlit keys must be unique."""
    seen_topic_ids: set[str] = set()
    deduped: list = []
    for topic in filtered_topics:
        tid = topic.get("topic_id")
        if tid is None:
            deduped.append(topic)
            continue
        if tid in seen_topic_ids:
            continue
        seen_topic_ids.add(tid)
        deduped.append(topic)
    return deduped
