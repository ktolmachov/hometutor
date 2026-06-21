"""Topic synthesis: chunk selection and LLM-grounded summary."""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any

from app.knowledge_catalog import compute_source_coverage, get_topics_catalog
from app.knowledge_text import tokenize
from app.llm_resilience import complete_with_resilience
from app.logging_config import setup_logging
from app.prompts import SYNTHESIS_PROMPT
from app.retrieval_cache import get_base_services

logger = setup_logging()


def _fallback_document_for_path(path: str) -> dict[str, Any]:
    normalized_path = str(path or "").strip().replace("\\", "/")
    parsed = PurePosixPath(normalized_path)
    folder_name = str(parsed.parent) if parsed.parent != PurePosixPath(".") else None
    doc_type = parsed.suffix.lower().lstrip(".") or None
    return {
        "doc_id": normalized_path,
        "relative_path": normalized_path,
        "file_name": parsed.name or normalized_path,
        "folder_name": folder_name,
        "summary": None,
        "doc_type": doc_type,
        "difficulty": None,
        "key_concepts": [],
    }


def _score_chunk_for_synthesis(
    chunk_text: str,
    *,
    topic_query: str,
    document_summary: str | None = None,
    key_concepts: list[str] | None = None,
) -> float:
    chunk_tokens = tokenize(chunk_text)
    if not chunk_tokens:
        return 0.0

    query_tokens = tokenize(topic_query)
    summary_tokens = tokenize(document_summary)
    concept_tokens = tokenize(" ".join(key_concepts or []))

    query_overlap = len(chunk_tokens & query_tokens)
    summary_overlap = len(chunk_tokens & summary_tokens)
    concept_overlap = len(chunk_tokens & concept_tokens)

    # Small length prior to avoid preferring trivial one-line chunks when scores tie.
    length_bonus = min(len(chunk_text.strip()) / 500.0, 0.5)
    return query_overlap * 3.0 + summary_overlap * 1.5 + concept_overlap * 1.0 + length_bonus


def _select_documents_for_synthesis(
    *,
    topic: str | None,
    topic_id: str | None,
    documents: list[str] | None,
    services: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    catalog = get_topics_catalog(services=services)
    catalog_topics = catalog["topics"]

    if documents:
        wanted = {str(item).strip().replace("\\", "/") for item in documents if str(item).strip()}
        selected_documents = []
        for catalog_topic in catalog_topics:
            for document in catalog_topic["documents"]:
                relative_path = str(document.get("relative_path") or "").strip().replace("\\", "/")
                if relative_path in wanted:
                    selected_documents.append(document)
        selected_paths = {
            str(document.get("relative_path") or "").strip().replace("\\", "/")
            for document in selected_documents
        }
        # Catalog may be empty or only partially enriched. Keep every requested
        # path in the working set so backend responses still satisfy API models.
        for path in sorted(wanted - selected_paths):
            selected_documents.append(_fallback_document_for_path(path))
        return topic or "Custom document set", selected_documents

    if topic_id:
        for catalog_topic in catalog_topics:
            if catalog_topic["topic_id"] == topic_id:
                return catalog_topic["topic_name"], catalog_topic["documents"]
        raise ValueError("Unknown topic_id")

    if topic:
        normalized = topic.strip().lower()
        for catalog_topic in catalog_topics:
            if catalog_topic["topic_name"].strip().lower() == normalized:
                return catalog_topic["topic_name"], catalog_topic["documents"]
        raise ValueError("Unknown topic")

    raise ValueError("Synthesis requires topic, topic_id, or documents")


def _fetch_chunks_for_documents(
    topic_query: str,
    selected_documents: list[dict[str, Any]],
    document_paths: list[str],
    *,
    services: dict[str, Any] | None = None,
    max_chunks_per_doc: int = 3,
    max_total_chunks: int = 10,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    services = services or get_base_services()
    collection = services["collection"]
    try:
        result = collection.get(include=["documents", "metadatas"])
    except Exception:  # noqa: BLE001 - synthesis can continue with an empty chunk set.
        logger.exception("Failed to load chunks for synthesis")
        return [], {}

    wanted = set(document_paths)
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []

    grouped_chunks: dict[str, list[tuple[float, str]]] = defaultdict(list)
    sources: list[dict[str, Any]] = []
    document_lookup = {item["relative_path"]: item for item in selected_documents}

    for idx, chunk_text in enumerate(documents):
        metadata = metadatas[idx] or {}
        relative_path = metadata.get("relative_path")
        if relative_path not in wanted:
            continue
        document_info = document_lookup.get(relative_path, {})
        source_text = metadata.get("original_text") or chunk_text or ""
        score = _score_chunk_for_synthesis(
            source_text,
            topic_query=topic_query,
            document_summary=document_info.get("summary"),
            key_concepts=document_info.get("key_concepts") or [],
        )
        grouped_chunks[relative_path].append((score, source_text))
        sources.append(
            {
                "relative_path": relative_path,
                "file_name": metadata.get("file_name"),
                "folder_name": metadata.get("folder_name"),
                "page": metadata.get("page_label", "?"),
                "score": round(score, 3),
                "_full_text": source_text,
                "text": source_text[:500],
            }
        )

    selected_grouped_chunks: dict[str, list[str]] = {}
    kept_source_keys: set[tuple[str, str]] = set()
    selected_sources: list[dict[str, Any]] = []

    per_doc_selected: list[tuple[str, float, str]] = []
    for relative_path, candidates in grouped_chunks.items():
        ranked = sorted(candidates, key=lambda item: item[0], reverse=True)[:max_chunks_per_doc]
        selected_grouped_chunks[relative_path] = [text for _, text in ranked]
        per_doc_selected.extend((relative_path, score, text) for score, text in ranked)

    # Keep globally best chunks if the topic spans many docs and there is too much context.
    top_ranked = sorted(per_doc_selected, key=lambda item: item[1], reverse=True)[:max_total_chunks]
    allowed_by_doc: dict[str, set[str]] = defaultdict(set)
    for relative_path, _, text in top_ranked:
        allowed_by_doc[relative_path].add(text)

    for relative_path, texts in list(selected_grouped_chunks.items()):
        filtered = [text for text in texts if text in allowed_by_doc.get(relative_path, set())]
        if filtered:
            selected_grouped_chunks[relative_path] = filtered
        else:
            del selected_grouped_chunks[relative_path]

    for source in sorted(sources, key=lambda item: ((item.get("score") or 0.0), item.get("relative_path") or ""), reverse=True):
        full_text = source.get("_full_text") or ""
        key = (source.get("relative_path") or "", full_text)
        if key in kept_source_keys:
            continue
        relative_path = source.get("relative_path") or ""
        if full_text not in allowed_by_doc.get(relative_path, set()):
            continue
        kept_source_keys.add(key)
        source.pop("_full_text", None)
        selected_sources.append(source)

    return selected_sources, selected_grouped_chunks


def synthesize_topic(
    *,
    topic: str | None = None,
    topic_id: str | None = None,
    documents: list[str] | None = None,
    services: dict[str, Any] | None = None,
) -> dict[str, Any]:
    services = services or get_base_services()
    resolved_topic, selected_documents = _select_documents_for_synthesis(
        topic=topic,
        topic_id=topic_id,
        documents=documents,
        services=services,
    )

    document_paths = [item["relative_path"] for item in selected_documents]
    sources, grouped_chunks = _fetch_chunks_for_documents(
        resolved_topic,
        selected_documents,
        document_paths,
        services=services,
    )
    if not grouped_chunks:
        raise ValueError("No chunks found for selected topic/documents")

    context_sections = []
    sections = []
    for document in selected_documents:
        rel_path = document["relative_path"]
        chunks = grouped_chunks.get(rel_path) or []
        if not chunks:
            continue
        section_text = "\n".join(f"- {chunk}" for chunk in chunks)
        context_sections.append(f"Document: {rel_path}\nSummary: {document.get('summary') or ''}\nChunks:\n{section_text}")
        sections.append(
            {
                "relative_path": rel_path,
                "summary": document.get("summary"),
                "key_concepts": document.get("key_concepts") or [],
                "chunks": chunks,
            }
        )

    llm = services["llm"]
    prompt = SYNTHESIS_PROMPT.format(
        context_str="\n\n".join(context_sections),
        query_str=resolved_topic,
    )
    response = complete_with_resilience(llm, prompt, stage="synthesize_topic")

    coverage = compute_source_coverage(
        source_paths=document_paths,
        topic_id=topic_id,
        services=services,
    )

    return {
        "topic": resolved_topic,
        "summary": response.text.strip(),
        "documents": selected_documents,
        "sections": sections,
        "sources": sources,
        "coverage": coverage,
    }


def fetch_document_chunks_text(
    documents: list[str],
    *,
    topic_query: str = "",
    services: dict[str, Any] | None = None,
    max_chunks_per_doc: int = 3,
    max_total_chunks: int = 12,
) -> str:
    """Return concatenated chunk text for the given document paths (no LLM call).

    Used by quiz generation to restrict content to a course scope's source_paths.
    """
    paths = [str(p).strip() for p in documents if str(p).strip()]
    if not paths:
        return ""
    stub_docs = [{"relative_path": p, "summary": None, "key_concepts": []} for p in paths]
    _, grouped_chunks = _fetch_chunks_for_documents(
        topic_query or " ".join(paths),
        stub_docs,
        paths,
        services=services,
        max_chunks_per_doc=max_chunks_per_doc,
        max_total_chunks=max_total_chunks,
    )
    return "\n\n".join("\n".join(chunks) for chunks in grouped_chunks.values())
