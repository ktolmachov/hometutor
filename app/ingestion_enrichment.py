"""LLM enrichment pass for ingested documents (split from ``app.ingestion``)."""

import time

from tqdm import tqdm
from llama_index.core import Document

from app.ingestion_chunk_metadata import (
    _METADATA_EXCLUDE_FROM_SPLIT_STRING,
    _slim_metadata_for_summary,
)
from app.ingestion_support import (
    _ascii_console_fragment,
    _ingestion_status,
    _print_ingest_progress,
    aggregate_page_range_for_doc_group,
)
from app.logging_config import setup_logging

logger = setup_logging()


def _enrich_documents(
    documents: list[Document],
    *,
    ingest_t0: float | None = None,
) -> tuple[list[Document], list[Document], dict[str, object]]:
    """Добавить семантические metadata и summary-документы по document-level (doc_id).

    Один LLM-вызов enrichment + один LLM-вызов summary на каждый уникальный doc_id.
    Все страницы/фрагменты с одним doc_id получают одинаковые обогащённые метаданные.
    """
    # Resolve facades via ``app.ingestion`` so tests can monkeypatch ``ingestion.*``.
    from app import ingestion as ingestion_mod

    settings = ingestion_mod.get_settings()

    # Группируем документы по doc_id, чтобы не дёргать LLM по нескольку раз на один файл.
    groups: dict[str, list[Document]] = {}
    for doc in documents:
        doc_id = (doc.metadata or {}).get("doc_id")
        if not doc_id:
            # На всякий случай fallback — считаем такой документ отдельной группой по id объекта.
            doc_id = f"__no_doc_id__:{id(doc)}"
        groups.setdefault(doc_id, []).append(doc)

    enriched_docs: list[Document] = []
    summary_docs: list[Document] = []
    stats = {
        "documents_seen": len(documents),
        "unique_doc_ids": len(groups),
        "metadata_enrichment_calls": 0,
        "summary_calls": 0,
        "metadata_enrichment_successes": 0,
        "summary_successes": 0,
        "estimated_cost_usd": {
            "metadata_enrichment": 0.0,
            "summary_generation": 0.0,
            "total": 0.0,
        },
        "token_usage": {
            "metadata_enrichment": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "summary_generation": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "total": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
    }

    def _merge_usage(stage: str, usage: dict[str, int] | None) -> None:
        if not usage:
            return
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = int(usage.get(key) or 0)
            stats["token_usage"][stage][key] += value
            stats["token_usage"]["total"][key] += value

    t_prog = ingest_t0 if ingest_t0 is not None else time.perf_counter()
    group_items = list(groups.items())
    total_g = len(group_items)
    _ingestion_status["ingest_unique_total"] = total_g
    _ingestion_status["ingest_unique_processed"] = 0
    pbar = tqdm(group_items, desc="Enriching documents", total=total_g, unit="doc", leave=True)
    for i, (doc_id, group) in enumerate(group_items, start=1):
        pbar.set_postfix_str(f"doc={_ascii_console_fragment(str(doc_id), 40)}")
        # Склеиваем текст группы для enrichment/summary
        full_text_parts = [(doc.text or "").strip() for doc in group if (doc.text or "").strip()]
        full_text = "\n\n".join(full_text_parts)

        enrichment = None
        if settings.enable_metadata_enrichment and full_text:
            stats["metadata_enrichment_calls"] += 1
            enrichment, enrich_cost = ingestion_mod.enrich_document_metadata_with_cost(full_text)
            if enrich_cost:
                _merge_usage("metadata_enrichment", enrich_cost.token_usage)
                stats["estimated_cost_usd"]["metadata_enrichment"] += float(enrich_cost.estimated_cost_usd or 0.0)
            if enrichment is not None:
                stats["metadata_enrichment_successes"] += 1

        summary: str | None = None
        if settings.enable_document_summaries and full_text:
            stats["summary_calls"] += 1
            summary, summary_cost = ingestion_mod.build_document_summary_with_cost(full_text)
            if summary_cost:
                _merge_usage("summary_generation", summary_cost.token_usage)
                stats["estimated_cost_usd"]["summary_generation"] += float(summary_cost.estimated_cost_usd or 0.0)
            if summary:
                stats["summary_successes"] += 1

        # Update ingestion status for Streamlit UI polling
        _ingestion_status["processed_files"] = _ingestion_status.get("processed_files", 0) + len(group)
        _ingestion_status["current_file"] = doc_id
        _ingestion_status["ingest_unique_processed"] = i
        _print_ingest_progress(
            phase="enrichment",
            processed=i,
            total=total_g,
            current=str(doc_id),
            started_monotonic=t_prog,
        )
        pbar.update(1)

        # Применяем обогащённые метаданные ко всем документам группы
        for doc in group:
            if enrichment is not None:
                if enrichment.topic:
                    doc.metadata["topic"] = enrichment.topic
                if enrichment.key_concepts:
                    concepts_str = ", ".join(enrichment.key_concepts)
                    doc.metadata["key_concepts"] = concepts_str
                    doc.metadata["concepts"] = concepts_str
                if enrichment.doc_type:
                    doc.metadata["doc_type"] = enrichment.doc_type
                if enrichment.difficulty:
                    doc.metadata["difficulty"] = enrichment.difficulty
            enriched_docs.append(doc)

        # Создаём один summary-документ на doc_id
        if summary:
            base_metadata = dict(group[0].metadata or {})
            labels = [(d.metadata or {}).get("page_label") for d in group]
            doc_pr = aggregate_page_range_for_doc_group(labels)
            if doc_pr:
                base_metadata["page_range"] = doc_pr
            split_extras = list(_METADATA_EXCLUDE_FROM_SPLIT_STRING)
            summary_doc = Document(
                text=summary,
                metadata=_slim_metadata_for_summary(base_metadata),
                excluded_embed_metadata_keys=split_extras,
                excluded_llm_metadata_keys=split_extras,
            )
            summary_docs.append(summary_doc)

    pbar.close()
    logger.info(
        "Documents enriched | raw_documents=%s | unique_doc_ids=%s | summaries=%s",
        len(documents),
        len(groups),
        len(summary_docs),
    )
    stats["estimated_cost_usd"]["metadata_enrichment"] = round(stats["estimated_cost_usd"]["metadata_enrichment"], 8)
    stats["estimated_cost_usd"]["summary_generation"] = round(stats["estimated_cost_usd"]["summary_generation"], 8)
    stats["estimated_cost_usd"]["total"] = round(
        stats["estimated_cost_usd"]["metadata_enrichment"] + stats["estimated_cost_usd"]["summary_generation"],
        8,
    )
    return enriched_docs, summary_docs, stats
