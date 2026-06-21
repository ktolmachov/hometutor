"""Topic catalog built from summary collection metadata (TTL cache, clustering)."""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import defaultdict
from typing import Any

from app.knowledge_text import normalize_topic_name, split_concepts
from app.retrieval_cache import get_base_services

# ---------------------------------------------------------------------------
# Topics catalog TTL cache (avoids repeated Chroma fetch on every Streamlit rerun)
# ---------------------------------------------------------------------------
_catalog_cache: dict[str, Any] = {}
_catalog_cache_lock = threading.Lock()
_CATALOG_TTL_SECONDS = 600  # 10 minutes — longer than Streamlit bootstrap cache (300s) to avoid cold scan on reload


def _catalog_cache_get() -> dict[str, Any] | None:
    with _catalog_cache_lock:
        entry = _catalog_cache.get("value")
        ts = _catalog_cache.get("ts", 0.0)
        if entry is not None and (time.monotonic() - ts) < _CATALOG_TTL_SECONDS:
            return entry
    return None


def _catalog_cache_set(value: dict[str, Any]) -> None:
    with _catalog_cache_lock:
        _catalog_cache["value"] = value
        _catalog_cache["ts"] = time.monotonic()


def invalidate_catalog_cache() -> None:
    """Call this after reindex so the next request rebuilds the catalog."""
    with _catalog_cache_lock:
        _catalog_cache.clear()


def _stable_topic_id(name: str, doc_paths: list[str]) -> str:
    digest = hashlib.sha1(f"{name}|{'|'.join(sorted(doc_paths))}".encode("utf-8")).hexdigest()
    return f"topic_{digest[:12]}"


def _cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if left is None or right is None:
        return 0.0
    if len(left) == 0 or len(right) == 0 or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _fetch_summary_records(services: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    services = services or get_base_services()
    summary_collection = services.get("summary_collection")
    if summary_collection is None:
        return []

    # Fetch metadata and text only — embeddings are large and only needed
    # for unassigned-document clustering in _cluster_records.
    result = summary_collection.get(include=["documents", "metadatas"])
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []

    records: list[dict[str, Any]] = []
    for idx, record_id in enumerate(ids):
        metadata = metadatas[idx] or {}
        summary_text = documents[idx] or ""
        topic_name = normalize_topic_name(metadata.get("topic"))
        concepts = split_concepts(metadata.get("key_concepts") or metadata.get("concepts"))
        records.append(
            {
                "id": record_id,
                "doc_id": metadata.get("doc_id") or record_id,
                "relative_path": metadata.get("relative_path") or metadata.get("file_name") or record_id,
                "file_name": metadata.get("file_name"),
                "folder_name": metadata.get("folder_name"),
                "topic_name": topic_name,
                "doc_type": metadata.get("doc_type"),
                "difficulty": metadata.get("difficulty"),
                "concepts": concepts,
                "summary": summary_text,
                "embedding": None,  # lazy — populated below only for unassigned records
                "metadata": metadata,
            }
        )

    # Only fetch embeddings for records without a topic_name (embedding-based clustering path).
    unassigned_ids = [r["id"] for r in records if not r["topic_name"]]
    if unassigned_ids:
        emb_result = summary_collection.get(ids=unassigned_ids, include=["embeddings"])
        emb_by_id = dict(zip(emb_result.get("ids") or [], emb_result.get("embeddings") or []))
        for record in records:
            if record["id"] in emb_by_id:
                record["embedding"] = emb_by_id[record["id"]]

    return records


def _cluster_records(records: list[dict[str, Any]], similarity_threshold: float = 0.88) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []

    topic_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unassigned: list[dict[str, Any]] = []
    for record in records:
        if record["topic_name"]:
            topic_groups[record["topic_name"].lower()].append(record)
        else:
            unassigned.append(record)

    for grouped_records in topic_groups.values():
        topic_name = grouped_records[0]["topic_name"] or "Untitled Topic"
        doc_paths = [record["relative_path"] for record in grouped_records]
        concept_counter: dict[str, int] = defaultdict(int)
        for record in grouped_records:
            for concept in record["concepts"]:
                concept_counter[concept] += 1
        key_concepts = [
            concept for concept, _ in sorted(concept_counter.items(), key=lambda item: (-item[1], item[0].lower()))
        ][:8]
        clusters.append(
            {
                "topic_id": _stable_topic_id(topic_name, doc_paths),
                "topic_name": topic_name,
                "documents": grouped_records,
                "key_concepts": key_concepts,
            }
        )

    embedding_clusters: list[dict[str, Any]] = []
    for record in unassigned:
        best_cluster = None
        best_score = -1.0
        for cluster in embedding_clusters:
            score = _cosine_similarity(record["embedding"], cluster.get("centroid"))
            if score > best_score:
                best_score = score
                best_cluster = cluster
        if best_cluster is None or best_score < similarity_threshold:
            embedding_clusters.append(
                {
                    "documents": [record],
                    "centroid": record["embedding"],
                }
            )
            continue

        best_cluster["documents"].append(record)
        embeddings = [item["embedding"] for item in best_cluster["documents"] if item.get("embedding")]
        if embeddings:
            dims = len(embeddings[0])
            best_cluster["centroid"] = [
                sum(vector[dim] for vector in embeddings) / len(embeddings)
                for dim in range(dims)
            ]

    for cluster in embedding_clusters:
        grouped_records = cluster["documents"]
        concept_counter: dict[str, int] = defaultdict(int)
        for record in grouped_records:
            for concept in record["concepts"]:
                concept_counter[concept] += 1
        key_concepts = [
            concept for concept, _ in sorted(concept_counter.items(), key=lambda item: (-item[1], item[0].lower()))
        ][:8]
        fallback_name = key_concepts[0] if key_concepts else (grouped_records[0]["file_name"] or "Misc")
        doc_paths = [record["relative_path"] for record in grouped_records]
        clusters.append(
            {
                "topic_id": _stable_topic_id(fallback_name, doc_paths),
                "topic_name": fallback_name,
                "documents": grouped_records,
                "key_concepts": key_concepts,
            }
        )

    return clusters


def get_topics_catalog(services: dict[str, Any] | None = None) -> dict[str, Any]:
    cached = _catalog_cache_get()
    if cached is not None:
        return cached

    records = _fetch_summary_records(services=services)
    clusters = _cluster_records(records)
    serialized_topics = []

    for cluster in sorted(clusters, key=lambda item: (-len(item["documents"]), item["topic_name"].lower())):
        documents = sorted(
            (
                {
                    "doc_id": record["doc_id"],
                    "relative_path": record["relative_path"],
                    "file_name": record["file_name"],
                    "folder_name": record["folder_name"],
                    "summary": record["summary"],
                    "doc_type": record["doc_type"],
                    "difficulty": record["difficulty"],
                    "key_concepts": record["concepts"],
                }
                for record in cluster["documents"]
            ),
            key=lambda item: item["relative_path"],
        )
        serialized_topics.append(
            {
                "topic_id": cluster["topic_id"],
                "topic_name": cluster["topic_name"],
                "document_count": len(documents),
                "key_concepts": cluster["key_concepts"],
                "documents": documents,
            }
        )

    result = {
        "topics": serialized_topics,
        "total_topics": len(serialized_topics),
        "total_documents": len(records),
    }
    _catalog_cache_set(result)
    return result


def compute_source_coverage(
    source_paths: list[str],
    topic_id: str | None = None,
    services: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute how many topic documents are covered by the given source paths.

    Returns coverage ratio, missing documents and a human-readable label.
    """
    if not source_paths:
        return {"covered": 0, "total": 0, "ratio": 0.0, "missing": [], "label": "Нет источников"}

    catalog = get_topics_catalog(services=services)
    source_set = set(source_paths)

    best_topic = None
    best_overlap = 0

    for topic in catalog.get("topics", []):
        topic_docs = {
            doc.get("relative_path") or doc.get("file_name")
            for doc in topic.get("documents", [])
        }
        if topic_id and topic["topic_id"] == topic_id:
            best_topic = topic
            break
        overlap = len(source_set & topic_docs)
        if overlap > best_overlap:
            best_overlap = overlap
            best_topic = topic

    if best_topic is None:
        return {
            "covered": len(source_paths),
            "total": catalog.get("total_documents", 0),
            "ratio": 0.0,
            "missing": [],
            "topic_name": None,
            "label": f"Использовано {len(source_paths)} документов",
        }

    topic_doc_paths = {
        doc.get("relative_path") or doc.get("file_name")
        for doc in best_topic.get("documents", [])
    }
    covered = len(source_set & topic_doc_paths)
    total = len(topic_doc_paths)
    missing = sorted(topic_doc_paths - source_set)
    ratio = covered / total if total > 0 else 0.0

    if ratio >= 0.8:
        label = "Высокое покрытие"
    elif ratio >= 0.4:
        label = "Среднее покрытие"
    else:
        label = "Низкое покрытие"

    return {
        "covered": covered,
        "total": total,
        "ratio": round(ratio, 2),
        "missing": missing[:10],
        "topic_name": best_topic.get("topic_name"),
        "topic_id": best_topic.get("topic_id"),
        "label": label,
    }
