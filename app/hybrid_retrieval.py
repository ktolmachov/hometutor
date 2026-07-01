"""
Hybrid retrieval helpers built on top of Chroma-backed nodes.
"""

import pathlib
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from llama_index.core.vector_stores import MetadataFilters
from llama_index.retrievers.bm25 import BM25Retriever

from app.logging_config import setup_logging

logger = setup_logging()

_bm25_lock = threading.Lock()
_cached_bm25_retrievers: dict[int, BM25Retriever] = {}
_RRF_K = 60
_BM25_PERSIST_SUBDIR = "bm25_index"
# Collections larger than this skip the full in-memory BM25 index to prevent OOM.
# Keep conservatively low: bm25s builds term-frequency matrices that are several
# times the raw text size. Raise only if the host has ample free RAM.
_BM25_MAX_NODES = 5_000
_BM25_PAGE_SIZE = 100  # smaller pages to avoid Rust/pyo3 OOM on fat metadata
# Node count is a poor proxy for memory: a few nodes with multi-MB metadata can OOM the
# Rust/pyo3 layer (this is exactly what crashed the tutor at 2000 nodes / 6.5 GB). After the
# first page we project total bytes and bail out before materializing a corpus this large.
_BM25_MAX_TOTAL_BYTES = 500_000_000  # ~500 MB projected fetch ceiling


def _bm25_persist_dir() -> pathlib.Path:
    """Return the BM25 index persist directory, creating it if needed."""
    from app.config import CHROMA_DIR
    return CHROMA_DIR / _BM25_PERSIST_SUBDIR


def _bm25_corpus_size(retriever: BM25Retriever) -> int:
    scores = getattr(getattr(retriever, "bm25", None), "scores", None) or {}
    num_docs = scores.get("num_docs")
    if num_docs is not None:
        return max(0, int(num_docs))
    corpus = getattr(retriever, "corpus", None) or []
    return len(corpus)


def _effective_bm25_top_k(similarity_top_k: int, corpus_size: int) -> int:
    if corpus_size < 1:
        return max(1, int(similarity_top_k))
    return max(1, min(int(similarity_top_k), corpus_size))


def _load_bm25_from_disk(similarity_top_k: int) -> BM25Retriever | None:
    """Try loading a pre-built BM25Retriever from disk. Returns None on any failure."""
    persist_dir = _bm25_persist_dir()
    if not persist_dir.exists():
        return None
    try:
        retriever = BM25Retriever.from_persist_dir(str(persist_dir))
        corpus_size = _bm25_corpus_size(retriever)
        effective_k = _effective_bm25_top_k(similarity_top_k, corpus_size)
        retriever.similarity_top_k = effective_k
        logger.info(
            "BM25Retriever loaded from disk | top_k=%s | corpus=%s | effective_top_k=%s | dir=%s",
            similarity_top_k,
            corpus_size,
            effective_k,
            persist_dir,
        )
        return retriever
    except Exception as exc:
        logger.warning("BM25 disk cache load failed, will rebuild: %s", exc)
        shutil.rmtree(persist_dir, ignore_errors=True)
        return None


def _save_bm25_to_disk(retriever: BM25Retriever) -> None:
    """Persist BM25Retriever to disk for fast reload on next restart."""
    persist_dir = _bm25_persist_dir()
    try:
        persist_dir.mkdir(parents=True, exist_ok=True)
        retriever.persist(str(persist_dir))
        logger.info("BM25Retriever persisted to disk | dir=%s", persist_dir)
    except Exception as exc:
        logger.warning("BM25 persist to disk failed (non-fatal): %s", exc)
        shutil.rmtree(persist_dir, ignore_errors=True)


class ParallelHybridRetriever:
    """Run BM25 and vector retrieval in parallel and fuse with reciprocal rank fusion."""

    def __init__(self, bm25_retriever, vector_retriever, similarity_top_k: int):
        self._bm25_retriever = bm25_retriever
        self._vector_retriever = vector_retriever
        self._similarity_top_k = similarity_top_k

    def retrieve(self, query_bundle: QueryBundle):
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="hybrid-retrieve") as executor:
            bm25_future = executor.submit(self._bm25_retriever.retrieve, query_bundle)
            vector_future = executor.submit(self._vector_retriever.retrieve, query_bundle)
            bm25_nodes = bm25_future.result()
            vector_nodes = vector_future.result()

        fused_nodes = _fuse_with_reciprocal_rank(
            [bm25_nodes, vector_nodes],
            similarity_top_k=self._similarity_top_k,
        )
        logger.info(
            "Parallel hybrid retrieval completed | bm25_nodes=%s | vector_nodes=%s | fused_nodes=%s",
            len(bm25_nodes),
            len(vector_nodes),
            len(fused_nodes),
        )
        return fused_nodes


def _nodes_from_chroma(collection) -> list[TextNode]:
    """Load documents from a Chroma collection page-by-page and convert to TextNode.

    Raises RuntimeError if the collection exceeds _BM25_MAX_NODES to prevent OOM
    when the corpus is too large for an in-memory BM25 index.
    """
    total = collection.count()
    if total > _BM25_MAX_NODES:
        raise RuntimeError(
            f"Collection has {total} nodes (limit {_BM25_MAX_NODES}). "
            "BM25 disabled for this collection — switch retrieval_mode to vector_only "
            "or raise BM25_MAX_NODES if RAM permits."
        )

    nodes: list[TextNode] = []
    offset = 0
    while True:
        try:
            result = collection.get(
                include=["documents", "metadatas"],
                limit=_BM25_PAGE_SIZE,
                offset=offset,
            )
        except BaseException as exc:
            # Must catch BaseException, not Exception: pyo3_runtime.PanicException
            # (raised when the Rust thread panics on OOM) inherits from BaseException
            # directly and is invisible to `except Exception`.
            if isinstance(exc, (SystemExit, KeyboardInterrupt, GeneratorExit)):
                raise
            raise RuntimeError(
                f"Failed loading Chroma nodes for BM25 at offset {offset} "
                f"({type(exc).__name__}, page_size={_BM25_PAGE_SIZE}). "
                "Reduce BM25_PAGE_SIZE or switch retrieval_mode to vector_only."
            ) from exc
        ids = result.get("ids") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []

        # Byte-aware guard: project full-corpus fetch size from the first page and abort to
        # vector-only (via the RuntimeError -> build_hybrid_retriever fallback) before we
        # materialize enough Python strings to OOM the pyo3 layer. Count-based limits miss this.
        if offset == 0 and ids:
            page_bytes = sum(len(d or "") for d in documents) + sum(
                len(str(m or "")) for m in metadatas
            )
            avg_bytes = page_bytes / len(ids)
            projected = int(avg_bytes * total)
            if projected > _BM25_MAX_TOTAL_BYTES:
                raise RuntimeError(
                    f"BM25 fetch projected at ~{projected // 1_000_000} MB for {total} nodes "
                    f"(avg {int(avg_bytes)} bytes/node, ceiling "
                    f"{_BM25_MAX_TOTAL_BYTES // 1_000_000} MB). Corpus metadata is too heavy "
                    "for in-memory BM25 — falling back to vector-only. Trim node metadata "
                    "(see _strip_relationship_metadata) or raise _BM25_MAX_TOTAL_BYTES."
                )

        for doc_id, text, meta in zip(ids, documents, metadatas):
            if not text:
                continue
            nodes.append(TextNode(text=text, id_=doc_id, metadata=meta or {}))
        if len(ids) < _BM25_PAGE_SIZE:
            break
        offset += _BM25_PAGE_SIZE

    logger.info("Loaded nodes from Chroma for BM25 | count=%s", len(nodes))
    return nodes


def _matches_filters(node: TextNode, filters: MetadataFilters | None) -> bool:
    if filters is None:
        return True

    metadata = node.metadata or {}
    return all(metadata.get(item.key) == item.value for item in filters.filters)


def _build_bm25_retriever(nodes: list[TextNode], similarity_top_k: int) -> BM25Retriever:
    if not nodes:
        raise ValueError("No nodes in Chroma for BM25 index")

    # bm25s требует k <= размера корпуса; при узком metadata-фильтре узлов может быть меньше top_k.
    effective_k = _effective_bm25_top_k(similarity_top_k, len(nodes))

    return BM25Retriever.from_defaults(
        nodes=nodes,
        similarity_top_k=effective_k,
    )


def _node_identity(node_with_score: NodeWithScore) -> str:
    node = getattr(node_with_score, "node", node_with_score)
    node_id = getattr(node, "node_id", None) or getattr(node, "id_", None)
    if node_id is not None:
        return str(node_id)
    return str(id(node))


def _fuse_with_reciprocal_rank(
    result_sets: list[list[NodeWithScore]],
    similarity_top_k: int,
) -> list[NodeWithScore]:
    fused_scores: dict[str, float] = {}
    fused_nodes: dict[str, NodeWithScore] = {}

    for result_set in result_sets:
        for rank, node_with_score in enumerate(result_set, start=1):
            node_key = _node_identity(node_with_score)
            fused_scores[node_key] = fused_scores.get(node_key, 0.0) + 1.0 / (_RRF_K + rank)
            fused_nodes[node_key] = node_with_score

    ranked_keys = sorted(fused_scores, key=lambda key: fused_scores[key], reverse=True)
    fused = []
    for key in ranked_keys[:similarity_top_k]:
        original = fused_nodes[key]
        fused.append(
            NodeWithScore(
                node=getattr(original, "node", original),
                score=fused_scores[key],
            )
        )

    return fused


def get_bm25_retriever(
    collection,
    similarity_top_k: int,
    filters: MetadataFilters | None = None,
) -> BM25Retriever:
    """Build a BM25 retriever from Chroma nodes, using cache for unfiltered retrieval.

    Supports caching multiple top_k values simultaneously, so queries with different
    top_k (e.g., fast=2 and quality=10) both benefit from pre-warmed cache.
    """
    global _cached_bm25_retrievers

    if filters is not None:
        filtered_nodes = [
            node for node in _nodes_from_chroma(collection) if _matches_filters(node, filters)
        ]
        retriever = _build_bm25_retriever(filtered_nodes, similarity_top_k)
        logger.info(
            "BM25Retriever built for filtered retrieval | nodes=%s | top_k=%s",
            len(filtered_nodes),
            similarity_top_k,
        )
        return retriever

    with _bm25_lock:
        if similarity_top_k in _cached_bm25_retrievers:
            logger.info("BM25Retriever cache hit | top_k=%s | cached_variants=%s", similarity_top_k, len(_cached_bm25_retrievers))
            return _cached_bm25_retrievers[similarity_top_k]

        disk_retriever = _load_bm25_from_disk(similarity_top_k)
        if disk_retriever is not None:
            _cached_bm25_retrievers[similarity_top_k] = disk_retriever
            return disk_retriever

        nodes = _nodes_from_chroma(collection)
        try:
            retriever = _build_bm25_retriever(nodes, similarity_top_k)
        except BaseException as exc:
            if isinstance(exc, (SystemExit, KeyboardInterrupt, GeneratorExit)):
                raise
            raise RuntimeError(
                f"BM25 index build failed after loading {len(nodes)} nodes "
                f"({type(exc).__name__}). "
                "The corpus may be too large for in-memory BM25; "
                "lower BM25_MAX_NODES or switch retrieval_mode to vector_only."
            ) from exc
        _cached_bm25_retrievers[similarity_top_k] = retriever
        _save_bm25_to_disk(retriever)
        logger.info("BM25Retriever built and cached | nodes=%s | top_k=%s | total_cached=%s", len(nodes), similarity_top_k, len(_cached_bm25_retrievers))
        return retriever


def invalidate_bm25_cache(*, clear_disk: bool = False):
    """Reset in-memory BM25 cache; optionally delete the disk index too.

    Pass clear_disk=True only when the underlying Chroma corpus has changed
    (i.e. after reindex/staging activation). On normal shutdown keep the disk
    index so the next startup can load it instantly instead of rebuilding.
    """
    global _cached_bm25_retrievers
    with _bm25_lock:
        count = len(_cached_bm25_retrievers)
        _cached_bm25_retrievers.clear()
    if clear_disk:
        persist_dir = _bm25_persist_dir()
        if persist_dir.exists():
            shutil.rmtree(persist_dir, ignore_errors=True)
            logger.info("BM25 disk index cleared | dir=%s", persist_dir)
    logger.info("BM25 cache invalidated | cleared %d cached variants | clear_disk=%s", count, clear_disk)


def warm_bm25_cache_if_configured(collection, retrieval_mode: str, similarity_top_k: int) -> None:
    """
    Прогрев глобального кэша BM25 для hybrid/bm25_only (дорогая загрузка узлов из Chroma).
    Для vector_only — no-op. Вызывать из фонового потока после get_base_services().
    """
    mode = (retrieval_mode or "").strip().lower()
    if mode not in ("hybrid", "bm25_only"):
        return

    logger.info("BM25 cache warm-up started | mode=%s | top_k=%s", mode, similarity_top_k)
    get_bm25_retriever(collection, int(similarity_top_k), filters=None)
    logger.info("BM25 cache warm-up completed | top_k=%s", similarity_top_k)


def build_hybrid_retriever(index, collection, similarity_top_k: int, filters=None):
    """Build a parallel hybrid retriever using BM25 + vector retrieval with RRF fusion.

    Falls back to vector-only if BM25 construction fails (OOM, corpus too large, Rust panic)
    so a single bad query never crashes the Streamlit thread.
    """
    vector_retriever = index.as_retriever(
        similarity_top_k=similarity_top_k,
        filters=filters,
    )
    try:
        bm25_retriever = get_bm25_retriever(collection, similarity_top_k, filters=filters)
    except BaseException as exc:
        # BaseException catches pyo3_runtime.PanicException which does NOT inherit
        # from Exception. Re-raise real signals so the process can shut down cleanly.
        if isinstance(exc, (SystemExit, KeyboardInterrupt, GeneratorExit)):
            raise
        logger.warning(
            "BM25 retriever construction failed, falling back to vector-only | reason=%s: %s",
            type(exc).__name__,
            exc,
        )
        return vector_retriever

    hybrid_retriever = ParallelHybridRetriever(
        bm25_retriever=bm25_retriever,
        vector_retriever=vector_retriever,
        similarity_top_k=similarity_top_k,
    )

    logger.info(
        "Hybrid retriever built | mode=parallel_rrf | top_k=%s",
        similarity_top_k,
    )
    return hybrid_retriever


def build_bm25_only_retriever(collection, similarity_top_k: int, filters=None):
    """Build a BM25-only retriever, primarily for exact-match keyword queries."""
    retriever = get_bm25_retriever(collection, similarity_top_k, filters=filters)
    logger.info(
        "BM25-only retriever built | top_k=%s | filtered=%s",
        similarity_top_k,
        filters is not None,
    )
    return retriever
