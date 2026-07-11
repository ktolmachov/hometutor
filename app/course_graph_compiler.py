"""Course Graph Compiler: LLM extraction, normalization, quality gate, honest publication."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from app.logging_config import setup_logging
from app.models import GraphQualityGateResult, GraphQualityReport
from app.prompts.course_graph_extraction import (
    build_course_graph_extraction_prompt,
    is_truncated_llm_response,
)

logger = setup_logging()

WEAK_EVIDENCE_CONFIDENCE = 0.55
SEMANTIC_RELATION_TYPES = frozenset(
    {"prerequisite", "uses", "extends", "contrasts", "part_of", "precedes", "related"}
)
PREREQUISITE_ROUTING_TYPES = frozenset({"prerequisite"})

_CYRILLIC = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


@dataclass
class CompileResult:
    payload: dict[str, Any]
    quality_report: GraphQualityReport
    gate_passed: bool
    published: bool = False
    relation_count: int = 0
    concept_count: int = 0
    cross_doc_relations: int = 0
    truncated: bool = False
    error: str | None = None


@dataclass
class _ConceptDraft:
    concept_id: str
    label: str
    normalized_label: str
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    source_doc_ids: set[str] = field(default_factory=set)
    source_chunk_ids: set[str] = field(default_factory=set)
    extraction_method: str = "llm"


@dataclass
class _RelationDraft:
    source_id: str
    target_id: str
    relation_type: str
    evidence_doc_id: str
    evidence_chunk_id: str
    confidence: float
    weak_evidence: bool = False
    inferred_relation: bool = False


def slugify_concept_id(label: str) -> str:
    text = str(label or "").strip().lower()
    text = text.translate(_CYRILLIC)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "concept"


def _lesson_anchor_id(relative_path: str) -> str:
    """Stable curriculum anchor id — not counted as filename-fallback semantic node."""
    slug = slugify_concept_id(relative_path) or slugify_concept_id(os.path.basename(relative_path))
    return f"lesson:{slug}"


def _lesson_sort_key(item: tuple[str, list[dict[str, Any]]]) -> tuple[int, str]:
    doc_id, rows = item
    base = rows[0] if rows else {}
    path = str(base.get("relative_path") or doc_id).strip()
    stem = os.path.splitext(os.path.basename(path))[0]
    nums = re.findall(r"\d+", stem)
    return (int(nums[0]) if nums else 9999, path.casefold())


def _lesson_display_label(relative_path: str, title: str) -> str:
    clean_title = str(title or "").strip()
    if clean_title and clean_title.casefold() not in {relative_path.casefold(), os.path.basename(relative_path).casefold()}:
        return clean_title
    stem = os.path.splitext(os.path.basename(relative_path))[0]
    return stem.replace("_", " ").strip() or relative_path


def _append_lesson_anchor_nodes(
    concepts_bucket: dict[str, dict[str, Any]],
    typed_relations: list[dict[str, Any]],
    documents_grouped: dict[str, list[dict[str, Any]]],
    documents_bucket: dict[str, dict[str, Any]],
    concepts: dict[str, _ConceptDraft],
    *,
    generation_id: str,
    iso_now: str,
) -> None:
    """Add one visible lesson node per course document + part_of / precedes links."""
    if not documents_grouped:
        return

    concepts_by_doc: dict[str, list[str]] = {}
    for cid, draft in concepts.items():
        for doc_id in draft.source_doc_ids:
            concepts_by_doc.setdefault(doc_id, []).append(cid)

    lesson_ids: list[str] = []
    lesson_meta: list[tuple[str, str, str]] = []
    for doc_id, rows in sorted(documents_grouped.items(), key=_lesson_sort_key):
        base = rows[0] if rows else {}
        relative_path = str(base.get("relative_path") or doc_id).strip()
        title = str(base.get("title") or base.get("file_name") or relative_path).strip()
        label = _lesson_display_label(relative_path, title)
        anchor_id = _lesson_anchor_id(relative_path or doc_id)
        chunk_id = _chunk_id_from_metadata(base, doc_id) if rows else doc_id
        lesson_ids.append(anchor_id)
        lesson_meta.append((anchor_id, doc_id, chunk_id))

        concepts_bucket[anchor_id] = {
            "label": label,
            "concept_id": anchor_id,
            "aliases": [os.path.basename(relative_path)] if relative_path else [],
            "description": f"Лекция курса: {label}",
            "prerequisites": [],
            "related_concepts": [],
            "documents": [relative_path],
            "related_documents": [relative_path],
            "learned": False,
            "level": "lesson",
            "provenance": {
                "source_doc_id": doc_id,
                "extraction_method": "curriculum_anchor",
                "confidence": 1.0,
                "generation_id": generation_id,
                "updated_at": iso_now,
            },
        }

        doc_entry = documents_bucket.get(doc_id)
        if isinstance(doc_entry, dict):
            doc_entry["lesson_anchor_id"] = anchor_id

        for cid in concepts_by_doc.get(doc_id, []):
            typed_relations.append(
                {
                    "source_concept_id": cid,
                    "target_concept_id": anchor_id,
                    "relation_type": "part_of",
                    "evidence_doc_id": doc_id,
                    "evidence_chunk_id": chunk_id,
                    "confidence": 1.0,
                    "extraction_method": "curriculum_anchor",
                    "generation_id": generation_id,
                    "weak_evidence": False,
                    "inferred_relation": False,
                }
            )

    for (_prev_id, _prev_doc, _prev_chunk), (next_id, next_doc, next_chunk) in zip(
        lesson_meta, lesson_meta[1:]
    ):
        typed_relations.append(
            {
                "source_concept_id": _prev_id,
                "target_concept_id": next_id,
                "relation_type": "precedes",
                "evidence_doc_id": next_doc,
                "evidence_chunk_id": next_chunk,
                "confidence": 1.0,
                "extraction_method": "curriculum_anchor",
                "generation_id": generation_id,
                "weak_evidence": False,
                "inferred_relation": False,
            }
        )


def _doc_id_from_metadata(metadata: dict[str, Any]) -> str:
    return str(metadata.get("doc_id") or metadata.get("relative_path") or "").strip()


def _chunk_id_from_metadata(metadata: dict[str, Any], doc_id: str) -> str:
    return str(
        metadata.get("chunk_id")
        or metadata.get("node_id")
        or metadata.get("id")
        or doc_id
    ).strip()


def _group_documents(documents: list[Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for doc in documents or []:
        metadata = dict(getattr(doc, "metadata", None) or {})
        doc_id = _doc_id_from_metadata(metadata)
        if not doc_id:
            continue
        text = str(getattr(doc, "text", "") or "").strip()
        if not text:
            get_content = getattr(doc, "get_content", None)
            if callable(get_content):
                text = str(get_content() or "").strip()
        metadata["text"] = text
        grouped.setdefault(doc_id, []).append(metadata)
    return grouped


def _valid_chunk_ids_by_doc(
    documents_grouped: dict[str, list[dict[str, Any]]],
) -> dict[str, set[str]]:
    return {
        doc_id: {_chunk_id_from_metadata(row, doc_id) for row in rows}
        for doc_id, rows in documents_grouped.items()
    }


def _first_valid_chunk_id(valid_chunk_ids: dict[str, set[str]], doc_id: str) -> str:
    chunks = sorted(valid_chunk_ids.get(doc_id) or [])
    return chunks[0] if chunks else ""


def _parse_extraction_json(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("extraction payload must be a JSON object")
    return data


def _default_llm_extract(doc_id: str, metadata_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], str | None]:
    from app.provider import get_graph_llm

    base = metadata_rows[0] if metadata_rows else {}
    relative_path = str(base.get("relative_path") or doc_id).strip()
    title = str(base.get("title") or base.get("file_name") or relative_path).strip()
    chunks = []
    for row in metadata_rows:
        chunks.append(
            {
                "chunk_id": _chunk_id_from_metadata(row, doc_id),
                "text": str(row.get("text") or row.get("section_title") or title)[:4000],
            }
        )
    prompt = build_course_graph_extraction_prompt(
        doc_id=doc_id,
        relative_path=relative_path,
        title=title,
        chunks_json=json.dumps(chunks, ensure_ascii=False),
    )
    llm = get_graph_llm()
    # LM Studio defaults can truncate dense lesson JSON (finish_reason=length); 8192 is enough for 1 doc.
    response = llm.chat(prompt.format_messages(), max_tokens=8192)
    finish_reason = getattr(getattr(response, "raw", None), "choices", [None])[0]
    finish_reason = getattr(finish_reason, "finish_reason", None) if finish_reason else None
    raw_text = str(getattr(response, "message", response).content or "")
    if is_truncated_llm_response(finish_reason, raw_text):
        raise TruncatedExtractionError("truncated graph LLM output")
    return _parse_extraction_json(raw_text), finish_reason


class TruncatedExtractionError(RuntimeError):
    pass


def _merge_concepts(
    extractions: list[tuple[str, dict[str, Any]]],
    valid_chunk_ids: dict[str, set[str]],
) -> tuple[dict[str, _ConceptDraft], dict[str, str], list[str]]:
    concepts: dict[str, _ConceptDraft] = {}
    concept_id_map: dict[str, str] = {}
    merge_conflicts: list[str] = []

    def _lookup_by_label(label: str) -> _ConceptDraft | None:
        key = label.strip().lower()
        for draft in concepts.values():
            names = {draft.label.lower(), draft.normalized_label.lower(), *(
                alias.lower() for alias in draft.aliases
            )}
            if key in names:
                return draft
        return None

    for doc_id, payload in extractions:
        for item in payload.get("concepts") or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("normalized_label") or "").strip()
            normalized = str(item.get("normalized_label") or label).strip()
            if not label or not normalized:
                continue
            cid = slugify_concept_id(normalized)
            aliases = [str(a).strip() for a in (item.get("aliases") or []) if str(a).strip()]
            chunk_id = str(item.get("source_chunk_id") or "").strip()
            existing = _lookup_by_label(normalized) or _lookup_by_label(label)
            if existing and existing.concept_id != cid:
                # _lookup_by_label only matches on exact (casefolded) equality against the
                # existing concept's label, normalized_label, or one of its aliases — any
                # match is already an explicit same-concept assertion (either this doc's
                # extraction used an inconsistent normalized_label, or an earlier doc
                # listed this label/alias as a synonym). Canonicalize onto the first-seen
                # concept instead of dropping the mention as an unresolved conflict.
                cid = existing.concept_id
            if cid not in concepts:
                concepts[cid] = _ConceptDraft(
                    concept_id=cid,
                    label=label,
                    normalized_label=normalized,
                    aliases=list(dict.fromkeys(aliases)),
                    description=str(item.get("description") or "").strip(),
                )
            draft = concepts[cid]
            draft.source_doc_ids.add(doc_id)
            if chunk_id in valid_chunk_ids.get(doc_id, set()):
                draft.source_chunk_ids.add(chunk_id)
            for alias in aliases:
                if alias not in draft.aliases:
                    draft.aliases.append(alias)
            concept_id_map[label] = cid
            concept_id_map[normalized] = cid
    return concepts, concept_id_map, merge_conflicts


def _assemble_relations(
    extractions: list[tuple[str, dict[str, Any]]],
    concepts: dict[str, _ConceptDraft],
    concept_id_map: dict[str, str],
    valid_chunk_ids: dict[str, set[str]],
    *,
    generation_id: str,
) -> list[_RelationDraft]:
    relations: list[_RelationDraft] = []
    for doc_id, payload in extractions:
        for item in payload.get("relations") or []:
            if not isinstance(item, dict):
                continue
            rel_type = str(item.get("type") or "").strip().lower()
            if rel_type not in SEMANTIC_RELATION_TYPES:
                continue
            source_label = str(item.get("source") or "").strip()
            target_label = str(item.get("target") or "").strip()
            source_id = concept_id_map.get(source_label) or slugify_concept_id(source_label)
            target_id = concept_id_map.get(target_label) or slugify_concept_id(target_label)
            if source_id not in concepts or target_id not in concepts:
                continue
            confidence = float(item.get("confidence") or 0.7)
            weak = rel_type == "related" or confidence < WEAK_EVIDENCE_CONFIDENCE
            evidence_doc_id = str(item.get("evidence_doc_id") or doc_id).strip()
            evidence_chunk_id = str(item.get("evidence_chunk_id") or "").strip()
            if not evidence_chunk_id:
                evidence_chunk_id = _first_valid_chunk_id(valid_chunk_ids, evidence_doc_id)
            relations.append(
                _RelationDraft(
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=rel_type,
                    evidence_doc_id=evidence_doc_id,
                    evidence_chunk_id=evidence_chunk_id,
                    confidence=max(0.0, min(1.0, confidence)),
                    weak_evidence=weak,
                    inferred_relation=weak,
                )
            )
    for rel in relations:
        if not rel.evidence_doc_id:
            for doc_id, _payload in extractions:
                rel.evidence_doc_id = doc_id
                rel.evidence_chunk_id = _first_valid_chunk_id(valid_chunk_ids, doc_id)
                break
        elif not rel.evidence_chunk_id:
            rel.evidence_chunk_id = _first_valid_chunk_id(valid_chunk_ids, rel.evidence_doc_id)
    return relations


def _build_payload(
    concepts: dict[str, _ConceptDraft],
    relations: list[_RelationDraft],
    documents_grouped: dict[str, list[dict[str, Any]]],
    *,
    generation_id: str,
    existing_concepts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    iso_now = datetime.now(timezone.utc).isoformat()
    concepts_bucket: dict[str, dict[str, Any]] = {}
    typed_relations: list[dict[str, Any]] = []
    documents_bucket: dict[str, dict[str, Any]] = {}
    relation_count = 0
    concept_id_by_name = {
        name.casefold(): cid
        for cid, draft in concepts.items()
        for name in (draft.label, draft.normalized_label, cid, *draft.aliases)
        if name
    }

    def _normalize_existing_refs(values: list[Any]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            raw = str(value or "").strip()
            concept_id = concept_id_by_name.get(raw.casefold())
            if concept_id and concept_id not in normalized:
                normalized.append(concept_id)
        return normalized

    for doc_id, rows in documents_grouped.items():
        base = rows[0] if rows else {}
        relative_path = str(base.get("relative_path") or doc_id).strip()
        title = str(base.get("title") or base.get("file_name") or relative_path).strip()
        linked = [
            draft.label
            for draft in concepts.values()
            if doc_id in draft.source_doc_ids
        ]
        documents_bucket[doc_id] = {
            "relative_path": relative_path,
            "title": title,
            "topic": None,
            "concepts": linked,
        }

    for cid, draft in concepts.items():
        existing = existing_concepts.get(cid) or existing_concepts.get(draft.label) or {}
        docs = sorted(
            {
                str(row.get("relative_path") or doc_id).strip()
                for doc_id in draft.source_doc_ids
                for row in documents_grouped.get(doc_id, [{"relative_path": doc_id}])
            }
        )
        concepts_bucket[cid] = {
            "label": draft.label,
            "concept_id": cid,
            "aliases": list(draft.aliases),
            "description": draft.description or draft.label,
            "prerequisites": _normalize_existing_refs(list(existing.get("prerequisites") or [])),
            "related_concepts": _normalize_existing_refs(list(existing.get("related_concepts") or [])),
            "documents": docs,
            "related_documents": docs,
            "learned": bool(existing.get("learned")),
            "provenance": {
                "source_doc_id": next(iter(draft.source_doc_ids), ""),
                "source_chunk_id": next(iter(draft.source_chunk_ids), ""),
                "extraction_method": draft.extraction_method,
                "confidence": 0.85,
                "generation_id": generation_id,
                "updated_at": iso_now,
            },
        }

    for rel in relations:
        typed_relations.append(
            {
                "source_concept_id": rel.source_id,
                "target_concept_id": rel.target_id,
                "relation_type": rel.relation_type,
                "evidence_doc_id": rel.evidence_doc_id,
                "evidence_chunk_id": rel.evidence_chunk_id,
                "confidence": rel.confidence,
                "extraction_method": "llm",
                "generation_id": generation_id,
                "weak_evidence": rel.weak_evidence,
                "inferred_relation": rel.inferred_relation,
            }
        )
        if rel.relation_type == "prerequisite":
            target = concepts_bucket.get(rel.target_id)
            source = concepts_bucket.get(rel.source_id)
            if target and source:
                if rel.source_id not in target["prerequisites"]:
                    target["prerequisites"].append(rel.source_id)
                    relation_count += 1
        elif rel.relation_type == "related":
            source = concepts_bucket.get(rel.source_id)
            target = concepts_bucket.get(rel.target_id)
            if source and target:
                if rel.target_id not in source["related_concepts"]:
                    source["related_concepts"].append(rel.target_id)
                if rel.source_id not in target["related_concepts"]:
                    target["related_concepts"].append(rel.source_id)

    _append_lesson_anchor_nodes(
        concepts_bucket,
        typed_relations,
        documents_grouped,
        documents_bucket,
        concepts,
        generation_id=generation_id,
        iso_now=iso_now,
    )

    edges_bucket = {
        cid: list(node.get("prerequisites") or [])
        for cid, node in concepts_bucket.items()
    }
    return {
        "concepts": concepts_bucket,
        "documents": documents_bucket,
        "edges": edges_bucket,
        "typed_relations": typed_relations,
        "generated_at": datetime.now().isoformat(),
        "graph_build_updated_at": iso_now,
        "source_doc_count": len(documents_bucket),
        "source_concept_count": len(concepts_bucket),
        "generation_id": generation_id,
        "_relation_count": relation_count,
    }


def _tarjan_cycles(concepts: dict[str, dict[str, Any]]) -> list[list[str]]:
    vertices = list(concepts.keys())
    id_set = set(vertices)
    adj: dict[str, list[str]] = {cid: [] for cid in vertices}
    for cid, node in concepts.items():
        for prereq_label in node.get("prerequisites") or []:
            for other_id, other in concepts.items():
                if other.get("label") == prereq_label or other_id == prereq_label:
                    if other_id in id_set and other_id != cid:
                        adj[cid].append(other_id)
    index_counter = [0]
    stack: list[str] = []
    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        index[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in adj.get(v, []):
            if w not in index:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index[w])
        if lowlink[v] == index[v]:
            component: list[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                sccs.append(component)

    for v in vertices:
        if v not in index:
            strongconnect(v)
    return sccs


def _compute_metrics(
    payload: dict[str, Any],
    documents_grouped: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    concepts = payload.get("concepts") or {}
    typed_relations = payload.get("typed_relations") or []
    doc_ids = set(documents_grouped.keys())
    semantic_relations = [
        rel
        for rel in typed_relations
        if isinstance(rel, dict)
        and str(rel.get("relation_type") or "") in SEMANTIC_RELATION_TYPES
        and not rel.get("weak_evidence")
    ]
    cross_doc = 0
    for rel in semantic_relations:
        src = str(rel.get("source_concept_id") or "")
        tgt = str(rel.get("target_concept_id") or "")
        src_docs = set((concepts.get(src) or {}).get("documents") or [])
        tgt_docs = set((concepts.get(tgt) or {}).get("documents") or [])
        if src_docs and tgt_docs and not src_docs.intersection(tgt_docs):
            cross_doc += 1
    concepts_with_evidence = sum(
        1
        for c in concepts.values()
        if isinstance(c, dict) and (c.get("provenance") or {}).get("source_doc_id")
    )
    valid_chunk_ids = {
        doc_id: {
            str(row.get("chunk_id") or "").strip()
            for row in rows
            if str(row.get("chunk_id") or "").strip()
        }
        for doc_id, rows in documents_grouped.items()
    }
    relations_with_evidence = sum(
        1
        for rel in typed_relations
        if isinstance(rel, dict)
        and rel.get("evidence_doc_id")
        and rel.get("evidence_chunk_id")
        and str(rel.get("evidence_chunk_id")) in valid_chunk_ids.get(str(rel.get("evidence_doc_id")), set())
    )
    docs_participating = sum(
        1
        for info in (payload.get("documents") or {}).values()
        if isinstance(info, dict) and info.get("concepts")
    )
    dangling = 0
    for rel in typed_relations:
        if not isinstance(rel, dict):
            continue
        src = str(rel.get("source_concept_id") or "")
        tgt = str(rel.get("target_concept_id") or "")
        if src not in concepts or tgt not in concepts:
            dangling += 1
    connected_ids = {
        str(rel.get(key) or "")
        for rel in typed_relations
        if isinstance(rel, dict)
        for key in ("source_concept_id", "target_concept_id")
        if str(rel.get(key) or "") in concepts
    }
    orphan_count = sum(1 for cid in concepts if cid not in connected_ids)
    concept_count = len(concepts)
    orphan_rate = (orphan_count / concept_count) if concept_count else 1.0
    filename_candidates: set[str] = set()
    for doc_id, rows in documents_grouped.items():
        for row in rows:
            relative_path = str(row.get("relative_path") or doc_id).strip()
            file_name = str(row.get("file_name") or "").strip()
            title = str(row.get("title") or "").strip()
            for value in (doc_id, relative_path, file_name, title):
                if not value:
                    continue
                filename_candidates.add(value.casefold())
                filename_candidates.add(re.sub(r"\.[^.]+$", "", value).casefold())
    filename_fallback = sum(
        1
        for c in concepts.values()
        if isinstance(c, dict)
        and (c.get("provenance") or {}).get("extraction_method") not in {"curriculum_anchor"}
        and (
            (c.get("provenance") or {}).get("extraction_method") == "heuristic"
            or str(c.get("label") or "").strip().casefold() in filename_candidates
            or str(c.get("concept_id") or "").strip().casefold() in filename_candidates
        )
    )
    cycles = _tarjan_cycles(concepts if isinstance(concepts, dict) else {})
    return {
        "concept_count": concept_count,
        "semantic_relation_count": len(semantic_relations),
        "cross_doc_relations": cross_doc,
        "docs_participating_pct": (docs_participating / len(doc_ids) * 100.0) if doc_ids else 0.0,
        "concepts_with_evidence_pct": (concepts_with_evidence / concept_count * 100.0) if concept_count else 0.0,
        "relations_with_evidence_pct": (
            relations_with_evidence / len(typed_relations) * 100.0 if typed_relations else 0.0
        ),
        "orphan_rate_pct": orphan_rate * 100.0,
        "dangling_refs": dangling,
        "prerequisite_cycles": len(cycles),
        "filename_fallback_nodes": filename_fallback,
        "doc_count": len(doc_ids),
    }


def evaluate_graph_quality_gate(metrics: dict[str, Any]) -> tuple[bool, list[GraphQualityGateResult], list[str]]:
    """Plan §6 thresholds for courses with >=3 documents."""
    doc_count = int(metrics.get("doc_count") or 0)
    gates: list[GraphQualityGateResult] = []
    fail_reasons: list[str] = []

    def _gate(name: str, required: str, actual_num: float, passed: bool, fail_ru: str) -> None:
        gates.append(
            GraphQualityGateResult(
                name=name,
                required=required,
                actual=str(int(actual_num) if actual_num == int(actual_num) else round(actual_num, 2)),
                passed=passed,
            )
        )
        if not passed:
            fail_reasons.append(fail_ru)

    if doc_count < 3:
        _gate("min_documents", ">= 3", doc_count, False, "Недостаточно документов для семантического графа")
        return False, gates, fail_reasons

    checks = [
        ("normalized_concepts", ">= 12", metrics.get("concept_count", 0), 12, "Мало нормализованных концептов"),
        ("semantic_relations", ">= 10", metrics.get("semantic_relation_count", 0), 10, "Мало семантических связей"),
        ("cross_doc_relations", ">= 3", metrics.get("cross_doc_relations", 0), 3, "Мало междокументных связей"),
        ("concept_evidence", "100%", metrics.get("concepts_with_evidence_pct", 0), 100, "Не все концепты с evidence"),
        ("relation_evidence", "100%", metrics.get("relations_with_evidence_pct", 0), 100, "Не все связи с evidence"),
        ("orphan_rate", "<= 25%", metrics.get("orphan_rate_pct", 100), 25, "Слишком много сиротских концептов"),
        ("dangling_refs", "0", metrics.get("dangling_refs", 1), 0, "Есть висячие ссылки"),
        ("prerequisite_cycles", "0", metrics.get("prerequisite_cycles", 1), 0, "Есть циклы prerequisites"),
        ("filename_fallback", "0", metrics.get("filename_fallback_nodes", 1), 0, "Есть узлы filename-fallback"),
    ]
    for name, required, actual, threshold, fail_ru in checks:
        if name in {"orphan_rate"}:
            passed = float(actual) <= float(threshold)
        elif name in {"concept_evidence", "relation_evidence"}:
            passed = float(actual) >= float(threshold)
        elif name.endswith("_refs") or name.endswith("_cycles") or name.endswith("_fallback"):
            passed = float(actual) <= float(threshold)
        else:
            passed = float(actual) >= float(threshold)
        _gate(name, required, float(actual), passed, fail_ru)

    docs_pct = float(metrics.get("docs_participating_pct") or 0)
    docs_passed = docs_pct >= 100.0
    _gate("docs_participating", "100%", docs_pct, docs_passed, "Не все документы участвуют в графе")
    gate_passed = all(g.passed for g in gates)
    return gate_passed, gates, fail_reasons


def compile_course_graph(
    documents: list[Any],
    *,
    generation_id: str,
    scope_hash: str,
    source_content_hashes: list[str] | None = None,
    existing_concepts: dict[str, dict[str, Any]] | None = None,
    llm_extract_fn: Callable[[str, list[dict[str, Any]]], tuple[dict[str, Any], str | None]] | None = None,
) -> CompileResult:
    """Orchestrate scope resolve → per-doc extract → merge → validate → quality report."""
    grouped = _group_documents(documents)
    if not grouped:
        report = GraphQualityReport(
            generation_id=generation_id,
            scope_hash=scope_hash,
            gate_passed=False,
            fail_reasons=["Нет документов в scope"],
        )
        return CompileResult(payload={}, quality_report=report, gate_passed=False, error="no_documents")

    extract_fn = llm_extract_fn or _default_llm_extract
    extractions: list[tuple[str, dict[str, Any]]] = []
    truncated = False
    try:
        for doc_id, rows in grouped.items():
            payload, _finish = extract_fn(doc_id, rows)
            extractions.append((doc_id, payload))
    except TruncatedExtractionError as exc:
        truncated = True
        report = GraphQualityReport(
            generation_id=generation_id,
            scope_hash=scope_hash,
            gate_passed=False,
            truncated=True,
            fail_reasons=[str(exc)],
        )
        return CompileResult(
            payload={},
            quality_report=report,
            gate_passed=False,
            truncated=True,
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - compiler returns diagnostic report
        report = GraphQualityReport(
            generation_id=generation_id,
            scope_hash=scope_hash,
            gate_passed=False,
            fail_reasons=[f"Ошибка extraction: {exc}"],
        )
        return CompileResult(payload={}, quality_report=report, gate_passed=False, error=str(exc))

    valid_chunk_ids = _valid_chunk_ids_by_doc(grouped)
    concepts, concept_id_map, merge_conflicts = _merge_concepts(extractions, valid_chunk_ids)
    relations = _assemble_relations(
        extractions,
        concepts,
        concept_id_map,
        valid_chunk_ids,
        generation_id=generation_id,
    )
    payload = _build_payload(
        concepts,
        relations,
        grouped,
        generation_id=generation_id,
        existing_concepts=existing_concepts or {},
    )
    payload["scope_hash"] = scope_hash
    payload["source_content_hashes"] = sorted(set(source_content_hashes or []))
    metrics = _compute_metrics(payload, grouped)
    gate_passed, gates, fail_reasons = evaluate_graph_quality_gate(metrics)
    if merge_conflicts:
        fail_reasons.extend([f"Конфликт alias: {c}" for c in merge_conflicts[:3]])
        gates.append(
            GraphQualityGateResult(
                name="alias_conflicts",
                required="0",
                actual=str(len(merge_conflicts)),
                passed=False,
            )
        )
        gate_passed = False
    report = GraphQualityReport(
        generation_id=generation_id,
        scope_hash=scope_hash,
        gate_passed=gate_passed,
        metrics=metrics,
        gates=gates,
        fail_reasons=fail_reasons,
        concept_id_map=concept_id_map,
        truncated=truncated,
    )
    logger.info(
        "course_graph_compiler | generation_id=%s scope_hash=%s docs=%s concepts=%s gate_passed=%s",
        generation_id,
        scope_hash,
        len(grouped),
        metrics.get("concept_count"),
        gate_passed,
    )
    return CompileResult(
        payload=payload,
        quality_report=report,
        gate_passed=gate_passed,
        relation_count=int(payload.get("_relation_count") or 0),
        concept_count=int(metrics.get("concept_count") or 0),
        cross_doc_relations=int(metrics.get("cross_doc_relations") or 0),
        truncated=truncated,
    )
