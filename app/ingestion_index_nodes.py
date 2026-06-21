"""Node parsing and embedding persistence for index build (shared by partial/full reindex)."""

from __future__ import annotations

from llama_index.core.ingestion import IngestionCache, IngestionPipeline
from llama_index.core.node_parser import SentenceWindowNodeParser, SentenceSplitter
from llama_index.core.schema import MetadataMode

import app.ingestion as ing
from app.config import get_retrieval_settings, get_settings


def _ingest_batch_sizes() -> tuple[int, int]:
    settings = get_settings()
    embed_batch_size = max(1, int(settings.ingest_embed_pipeline_batch_size))
    store_batch_size = max(1, int(settings.ingest_store_batch_size))
    return embed_batch_size, store_batch_size


def _embed_and_store(nodes, embed_model, vector_store, *, show_progress: bool = True) -> None:
    """Embed nodes and persist to vector_store with disk-backed IngestionCache.

    Interleaved approach: embed in small batches (avoids OOM in
    get_transformation_hash), flush to ChromaDB every store batch
    (bounds peak RAM to one store-batch of embeddings, not the full corpus),
    while keeping ChromaDB HNSW rebuild count reasonable.
    """
    embed_batch_size, store_batch_size = _ingest_batch_sizes()

    before = len(nodes)
    nodes = [n for n in nodes if n.get_content(metadata_mode=MetadataMode.EMBED).strip()]
    dropped = before - len(nodes)
    if dropped:
        ing.logger.info("Skipped %d empty nodes before embedding", dropped)

    cache = (
        IngestionCache.from_persist_path(str(ing.INGEST_CACHE_PATH))
        if ing.INGEST_CACHE_PATH.exists()
        else IngestionCache()
    )
    pipeline = IngestionPipeline(transformations=[embed_model], cache=cache)

    total = len(nodes)
    buffer: list = []
    store_offset = 0

    for batch_start in range(0, total, embed_batch_size):
        batch = nodes[batch_start : batch_start + embed_batch_size]
        ing.logger.info(
            "Embedding batch | start=%d end=%d total=%d",
            batch_start,
            min(batch_start + embed_batch_size, total),
            total,
        )
        buffer.extend(pipeline.run(nodes=batch, show_progress=show_progress))

        while len(buffer) >= store_batch_size:
            store_batch = buffer[:store_batch_size]
            ing.logger.info(
                "Vector store write | start=%d end=%d total=%d",
                store_offset,
                store_offset + len(store_batch),
                total,
            )
            vector_store.add(store_batch)
            store_offset += len(store_batch)
            buffer = buffer[store_batch_size:]

    if buffer:
        ing.logger.info(
            "Vector store write | start=%d end=%d total=%d",
            store_offset,
            store_offset + len(buffer),
            total,
        )
        vector_store.add(buffer)

    ing.INGEST_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache.persist(str(ing.INGEST_CACHE_PATH))


def _strip_relationship_metadata(nodes):
    """Drop copied neighbor metadata from each node's relationships.

    LlamaIndex node parsers populate PREV/NEXT/SOURCE ``RelatedNodeInfo`` entries with a full
    copy of the related node's ``metadata``. This causes each node to store its chunk metadata
    (including ``original_text``) three times (own + prev + next), inflating the serialized
    ``_node_content`` ~3x and bloating ChromaDB. Nothing in the query path reads neighbor
    relationship metadata, so clearing it is loss-free and keeps node_id/node_type/hash
    intact for graph traversal and dedup.
    """
    cleared = 0
    for node in nodes:
        for related in (node.relationships or {}).values():
            related_infos = related if isinstance(related, list) else [related]
            for info in related_infos:
                meta = getattr(info, "metadata", None)
                if meta:
                    info.metadata = {}
                    cleared += 1
    if cleared:
        ing.logger.info("Stripped relationship metadata | cleared_refs=%d", cleared)
    return nodes


def _build_nodes(documents):
    retrieval_settings = get_retrieval_settings()
    ing.logger.info(
        "Building nodes | split_strategy=%s | window_size=%s | chunk_size=%s | chunk_overlap=%s",
        retrieval_settings.split_strategy,
        retrieval_settings.window_size,
        retrieval_settings.chunk_size,
        retrieval_settings.chunk_overlap,
    )

    if retrieval_settings.split_strategy == "sentence_window":
        parser = SentenceWindowNodeParser.from_defaults(
            window_size=retrieval_settings.window_size,
            window_metadata_key="window",
            original_text_metadata_key="original_text",
        )
        return _strip_relationship_metadata(parser.get_nodes_from_documents(documents))

    if retrieval_settings.split_strategy == "sentence_splitter":
        splitter = SentenceSplitter(
            chunk_size=retrieval_settings.chunk_size,
            chunk_overlap=retrieval_settings.chunk_overlap,
        )
        nodes = splitter.get_nodes_from_documents(documents)
        for node in nodes:
            node.metadata["original_text"] = node.text
        return _strip_relationship_metadata(nodes)

    raise ValueError(f"Unsupported SPLIT_STRATEGY: {retrieval_settings.split_strategy}")
