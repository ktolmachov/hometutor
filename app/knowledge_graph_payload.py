"""Сборка словаря графа концептов из метаданных документов при ingestion."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


def _clean_concept_name(value: Any) -> str:
    text = str(value or "").strip()
    return " ".join(text.split())


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _split_concept_values(value: Any) -> List[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value or "").split(",")
    out: List[str] = []
    for item in raw_items:
        concept = _clean_concept_name(item)
        if concept and concept not in out:
            out.append(concept)
    return out


def _ordered_metadata_concepts(metadata: Dict[str, Any]) -> List[str]:
    ordered: List[str] = []

    def _push_many(values: List[str]) -> None:
        for value in values:
            if value and value not in ordered:
                ordered.append(value)

    topic = _clean_concept_name(metadata.get("topic"))
    if topic:
        ordered.append(topic)

    _push_many(_split_concept_values(metadata.get("key_concepts")))
    _push_many(_split_concept_values(metadata.get("concepts")))

    if not ordered:
        section_path = str(metadata.get("section_path") or metadata.get("structural_path") or "").strip()
        if section_path:
            _push_many([_clean_concept_name(part) for part in section_path.split(">")])

    if not ordered:
        fallback_title = _clean_concept_name(
            metadata.get("section_title") or metadata.get("title") or metadata.get("html_title") or metadata.get("file_name")
        )
        if fallback_title:
            ordered.append(fallback_title)

    return ordered


def _ensure_concept_provenance_defaults(data: Dict[str, Any]) -> None:
    """Старые bundle без полей provenance: безопасные значения по умолчанию."""
    ts = str(data.get("graph_build_updated_at") or data.get("generated_at") or "").strip()
    for _name, c in (data.get("concepts") or {}).items():
        if not isinstance(c, dict) or c.get("provenance"):
            continue
        docs = c.get("documents") or c.get("related_documents") or []
        sid = str(docs[0]).strip() if docs else ""
        c["provenance"] = {
            "source_doc_id": sid,
            "extraction_method": "legacy",
            "confidence": None,
            "updated_at": ts,
        }


def build_graph_payload_from_documents(
    documents: List[Any],
    existing_concepts: Dict[str, Dict],
) -> Dict[str, Any]:
    """
    Собирает словарь графа (concepts/documents/edges) из документов ingestion.
    ``existing_concepts`` — предыдущее состояние (learned, prerequisites и т.д.).
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for doc in documents or []:
        metadata = dict(getattr(doc, "metadata", None) or {})
        doc_id = str(metadata.get("doc_id") or metadata.get("relative_path") or "").strip()
        if not doc_id:
            continue
        grouped.setdefault(doc_id, []).append(metadata)

    concepts_bucket: Dict[str, Dict[str, Any]] = {}
    documents_bucket: Dict[str, Dict[str, Any]] = {}
    edges_bucket: Dict[str, List[str]] = {}
    relation_count = 0

    def _ensure_concept_node(name: str) -> Dict[str, Any]:
        clean_name = _clean_concept_name(name)
        existing = existing_concepts.get(clean_name, {})
        if clean_name not in concepts_bucket:
            concepts_bucket[clean_name] = {
                "description": str(existing.get("description") or ""),
                "prerequisites": list(existing.get("prerequisites") or []),
                "related_concepts": list(existing.get("related_concepts") or []),
                "documents": list(existing.get("documents") or []),
                "related_documents": list(existing.get("related_documents") or existing.get("documents") or []),
                "learned": bool(existing.get("learned")),
            }
            if existing.get("learned_at"):
                concepts_bucket[clean_name]["learned_at"] = existing.get("learned_at")
            if existing.get("level"):
                concepts_bucket[clean_name]["level"] = existing.get("level")
            if existing.get("provenance") and isinstance(existing.get("provenance"), dict):
                concepts_bucket[clean_name]["provenance"] = dict(existing["provenance"])
        return concepts_bucket[clean_name]

    for doc_id, metadata_rows in grouped.items():
        base = metadata_rows[0] if metadata_rows else {}
        ordered_concepts: List[str] = []
        for row in metadata_rows:
            for concept in _ordered_metadata_concepts(row):
                if concept and concept not in ordered_concepts:
                    ordered_concepts.append(concept)
        if not ordered_concepts:
            continue
        relative_path = str(base.get("relative_path") or doc_id).strip() or doc_id
        title = str(base.get("title") or base.get("html_title") or base.get("file_name") or relative_path).strip()
        topic = _clean_concept_name(base.get("topic"))

        documents_bucket[doc_id] = {
            "relative_path": relative_path,
            "title": title,
            "topic": topic or None,
            "concepts": ordered_concepts,
        }

        for idx, concept in enumerate(ordered_concepts):
            node = _ensure_concept_node(concept)
            if not node.get("_primary_source_doc_id"):
                node["_primary_source_doc_id"] = doc_id
            if not node.get("description"):
                node["description"] = title
            if relative_path not in node["documents"]:
                node["documents"].append(relative_path)
            if relative_path not in node["related_documents"]:
                node["related_documents"].append(relative_path)

            if idx > 0:
                prereq = ordered_concepts[idx - 1]
                if prereq and prereq != concept and prereq not in node["prerequisites"]:
                    node["prerequisites"].append(prereq)
                    relation_count += 1
                prev_node = _ensure_concept_node(prereq)
                if concept not in prev_node["related_concepts"]:
                    prev_node["related_concepts"].append(concept)
                if prereq not in node["related_concepts"]:
                    node["related_concepts"].append(prereq)

    iso_now = datetime.now(timezone.utc).isoformat()
    for concept_name, node in concepts_bucket.items():
        node["prerequisites"] = list(dict.fromkeys(_split_concept_values(node.get("prerequisites"))))
        node["related_concepts"] = [
            item
            for item in dict.fromkeys(_split_concept_values(node.get("related_concepts")))
            if item != concept_name
        ]
        node["documents"] = list(dict.fromkeys(_split_concept_values(node.get("documents"))))
        node["related_documents"] = list(dict.fromkeys(_split_concept_values(node.get("related_documents"))))
        edges_bucket[concept_name] = list(node["prerequisites"])
        prov = node.get("provenance")
        if isinstance(prov, dict) and prov.get("extraction_method") == "manual":
            continue
        pid = node.pop("_primary_source_doc_id", None) or ""
        if not pid and node.get("documents"):
            pid = str(node["documents"][0])
        node["provenance"] = {
            "source_doc_id": str(pid or ""),
            "extraction_method": "heuristic",
            "confidence": 0.72,
            "updated_at": iso_now,
        }

    return {
        "concepts": concepts_bucket,
        "documents": documents_bucket,
        "edges": edges_bucket,
        "generated_at": datetime.now().isoformat(),
        "graph_build_updated_at": iso_now,
        "source_doc_count": len(documents_bucket),
        "source_concept_count": len(concepts_bucket),
        "_relation_count": relation_count,
    }
