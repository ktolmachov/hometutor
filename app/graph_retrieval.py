"""
Graph-augmented retrieval (итерация 17 Core): расширение набора документов через активный knowledge graph.

Используется как NodePostprocessor после базового retrieve/rerank для query_type
``synthesis`` и ``learning_plan``.
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import time
from contextlib import contextmanager
from typing import Any, Generator

_graph_expansion_trace_ctx: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "graph_expansion_trace", default=None
)

from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters

from app.logging_config import log_event, setup_logging
from app.models import GraphEvidence, GraphRelationDirection

logger = setup_logging()

GRAPH_AUGMENT_QUERY_TYPES = frozenset({"synthesis", "learning_plan"})
_CONCEPT_ID_SAMPLE_CAP = 32
_CONCEPT_ROUTE_SAMPLE_CAP = 8
_DOC_REASON_SAMPLE_CAP = 8


def _merge_filters(base: MetadataFilters | None, extra: list[MetadataFilter]) -> MetadataFilters | None:
    if not extra:
        return base
    if base is None:
        return MetadataFilters(filters=list(extra))
    return MetadataFilters(filters=list(base.filters) + list(extra))


def extract_doc_ids_from_nodes(nodes: list[NodeWithScore]) -> list[str]:
    """Уникальные doc_id из metadata узлов retrieval."""
    seen: list[str] = []
    for nws in nodes or []:
        node = getattr(nws, "node", nws)
        meta = getattr(node, "metadata", {}) or {}
        if not isinstance(meta, dict):
            continue
        did = str(meta.get("doc_id") or meta.get("relative_path") or "").strip()
        if did and did not in seen:
            seen.append(did)
    return seen


def _expand_concepts_multi_hop(
    concepts: dict[str, dict[str, Any]],
    seed_concepts: set[str],
    *,
    max_hops: int,
) -> tuple[set[str], int, dict[str, dict[str, Any]]]:
    """Расширяет множество концептов по prerequisites и related_concepts до ``max_hops`` волн."""
    touched: set[str] = set(seed_concepts)
    routes: dict[str, dict[str, Any]] = {
        concept_id: {
            "concept_id": concept_id,
            "hop": 0,
            "relation": "seed",
            "via_concept": None,
        }
        for concept_id in touched
    }
    hops_applied = 0
    waves = max(1, int(max_hops))
    frontier: set[str] = set(seed_concepts)
    if not seed_concepts:
        return touched, 1 if waves > 0 else 0, routes
    for _ in range(waves):
        hops_applied += 1
        next_frontier: set[str] = set()
        for cname in list(frontier):
            cnode = concepts.get(cname) or {}
            if not isinstance(cnode, dict):
                continue
            for relation, items in (
                ("prerequisite", cnode.get("prerequisites") or []),
                ("related", cnode.get("related_concepts") or []),
            ):
                for raw_target in items:
                    target = str(raw_target).strip()
                    if not target:
                        continue
                    if target not in touched:
                        touched.add(target)
                        next_frontier.add(target)
                        routes[target] = {
                            "concept_id": target,
                            "hop": hops_applied,
                            "relation": relation,
                            "via_concept": cname,
                        }
        if not next_frontier:
            break
        frontier = next_frontier
    return touched, hops_applied, routes


def _trace_route_sample(routes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    sample: list[dict[str, Any]] = []
    for concept_id, item in sorted(
        routes.items(),
        key=lambda pair: (
            int((pair[1] or {}).get("hop") or 0),
            str(pair[0]),
        ),
    )[:_CONCEPT_ROUTE_SAMPLE_CAP]:
        route = item or {}
        sample.append(
            {
                "concept_id": concept_id,
                "hop": int(route.get("hop") or 0),
                "relation": str(route.get("relation") or "seed"),
                "via_concept": route.get("via_concept"),
            }
        )
    return sample


def _doc_reason_sample(
    *,
    added_doc_ids: list[str],
    concepts: dict[str, dict[str, Any]],
    routes: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for doc_id in added_doc_ids[:_DOC_REASON_SAMPLE_CAP]:
        reasons: list[dict[str, Any]] = []
        for concept_id, cnode in concepts.items():
            if not isinstance(cnode, dict):
                continue
            docs_raw = list(cnode.get("documents") or []) + list(cnode.get("related_documents") or [])
            docs_norm = {str(d).strip() for d in docs_raw if str(d).strip()}
            if doc_id not in docs_norm:
                continue
            route = routes.get(str(concept_id).strip()) or {}
            reasons.append(
                {
                    "concept_id": str(concept_id).strip(),
                    "hop": int(route.get("hop") or 0),
                    "relation": str(route.get("relation") or "seed"),
                    "via_concept": route.get("via_concept"),
                }
            )
        reasons = sorted(reasons, key=lambda item: (int(item.get("hop") or 0), str(item.get("concept_id") or "")))
        if reasons:
            out.append(
                {
                    "doc_id": doc_id,
                    "reasons": reasons[:2],
                }
            )
    return out


def expand_doc_ids_via_graph(
    seed_doc_ids: list[str],
    concepts: dict[str, dict[str, Any]],
    *,
    max_extra: int,
    max_hops: int = 1,
) -> tuple[list[str], dict[str, Any]]:
    """
    Добавляет doc_id соседних концептов (prerequisites, related, общие документы).

    ``concepts`` — словарь ``get_concepts()`` из активного графа.
    ``max_hops`` — число волн обхода рёбер графа концептов (E4 multi-hop); ``1`` совместимо с прежним одним проходом.
    """
    seed = {str(d).strip() for d in seed_doc_ids if str(d).strip()}
    if not seed:
        return [], {"seed_doc_ids": [], "added_doc_ids": [], "reason": "empty_seed"}

    initial_touched: set[str] = set()
    for cname, cnode in concepts.items():
        if not isinstance(cnode, dict):
            continue
        docs_raw = list(cnode.get("documents") or []) + list(cnode.get("related_documents") or [])
        docs_norm = {str(d).strip() for d in docs_raw if str(d).strip()}
        if seed & docs_norm:
            initial_touched.add(str(cname).strip())

    touched, hops_applied, routes = _expand_concepts_multi_hop(
        concepts,
        initial_touched,
        max_hops=max_hops,
    )

    expanded: set[str] = set()
    for cname in touched:
        cnode = concepts.get(cname) or {}
        if not isinstance(cnode, dict):
            continue
        for d in list(cnode.get("documents") or []) + list(cnode.get("related_documents") or []):
            ds = str(d).strip()
            if ds and ds not in seed:
                expanded.add(ds)

    added = [d for d in expanded if d not in seed][: max(0, max_extra)]
    sample = sorted(touched)[:_CONCEPT_ID_SAMPLE_CAP]
    trace = {
        "seed_doc_ids": list(seed),
        "seed_concept_ids_sample": sorted(initial_touched)[:_CONCEPT_ROUTE_SAMPLE_CAP],
        "added_doc_ids": added,
        "concepts_touched": len(touched),
        "concept_ids_sample": sample,
        "concept_route_sample": _trace_route_sample(routes),
        "added_doc_reason_sample": _doc_reason_sample(
            added_doc_ids=added,
            concepts=concepts,
            routes=routes,
        ),
        "max_hops": int(max_hops),
        "hops_applied": hops_applied,
    }
    return added, trace


def _retrieve_chunks_for_doc(
    base_index,
    query_str: str,
    doc_id: str,
    similarity_top_k: int,
    base_filters: MetadataFilters | None,
) -> list[NodeWithScore]:
    filter_attempts: list[list[MetadataFilter]] = [
        [MetadataFilter(key="doc_id", value=doc_id)],
    ]
    # fallback: некоторые чанки только с relative_path
    if doc_id:
        filter_attempts.append([MetadataFilter(key="relative_path", value=doc_id)])

    for extra_filters in filter_attempts:
        filters = _merge_filters(base_filters, extra_filters)
        chunk_retriever = base_index.as_retriever(similarity_top_k=similarity_top_k, filters=filters)
        chunk_nodes = chunk_retriever.retrieve(QueryBundle(query_str))
        if chunk_nodes:
            return chunk_nodes
    return []


def _node_dedupe_key(nws: NodeWithScore) -> str:
    node = getattr(nws, "node", nws)
    nid = getattr(node, "node_id", None) or getattr(node, "id_", None)
    if nid is not None:
        return str(nid)
    meta = getattr(node, "metadata", {}) or {}
    return str(meta.get("doc_id", "")) + "|" + str(hash(getattr(node, "text", "") or ""))[:16]


def baseline_unique_node_count(nodes: list[NodeWithScore]) -> int:
    seen: set[str] = set()
    for nws in nodes or []:
        seen.add(_node_dedupe_key(nws))
    return len(seen)


def evaluate_composite_graph_gating(
    *,
    use_composite_graph_gating: bool,
    effective_graph_augmented: bool,
    classify_confidence: float,
    graph_augment_min_confidence: float,
    baseline_dedupe_count: int,
    baseline_thin_k: int,
    effective_profile: str,
) -> tuple[bool, str | None]:
    """
    ADR-021 §4.4 композитный gate (включён только когда есть execution context retrieval).

    ``use_composite_graph_gating=False`` сохраняет legacy-поведение: только флаги включения и query_type.
    """
    if not use_composite_graph_gating:
        return True, None
    if not effective_graph_augmented:
        return False, "routing_graph_disabled"
    try:
        cval = float(classify_confidence)
    except (TypeError, ValueError):
        cval = 0.0
    if cval < float(graph_augment_min_confidence):
        return False, "composite_gating_confidence"
    thin = int(baseline_dedupe_count) < int(baseline_thin_k)
    prof = str(effective_profile or "").strip().lower()
    explicit_graph = prof == "graph_aware"
    if not thin and not explicit_graph:
        return False, "composite_gating_baseline"
    return True, None


def _active_kg_generation_id() -> str | None:
    try:
        from app.index_registry import get_active_generation_view

        gid = getattr(get_active_generation_view(), "generation_id", None)
        s = str(gid or "").strip()
        return s or None
    except Exception:  # noqa: BLE001 - registry optional in some tests
        return None


def _stable_relation_id(*parts: str) -> str:
    raw = "|".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha256(raw).hexdigest()[:32]


def _edge_direction(relation: str) -> GraphRelationDirection:
    rel = (relation or "").strip().lower()
    if rel == "prerequisite":
        return "reverse"
    if rel == "related":
        return "undirected"
    return "forward"


def _relation_confidence(classify_confidence: float, hop: int) -> float:
    base = max(0.0, min(1.0, float(classify_confidence)))
    damp = 1.0 / (1.0 + 0.42 * max(0, int(hop)))
    return max(0.05, min(1.0, base * damp))


def graph_evidences_from_reason_rows(
    *,
    doc_id: str,
    reason_rows: list[dict[str, Any]],
    classify_confidence: float,
    weak_threshold: float,
    generation_id: str | None,
) -> list[GraphEvidence]:
    out: list[GraphEvidence] = []
    evid_doc = str(doc_id).strip()
    if not evid_doc:
        return out
    wthr = float(weak_threshold)
    for raw in reason_rows or []:
        if not isinstance(raw, dict):
            continue
        concept_id = str(raw.get("concept_id") or "").strip()
        if not concept_id:
            continue
        hop = int(raw.get("hop") or 0)
        relation_type = str(raw.get("relation") or "relation").strip() or "relation"
        via = raw.get("via_concept")
        src = str(via).strip() if via else concept_id
        tgt = concept_id
        confidence = _relation_confidence(classify_confidence, hop)
        weak = confidence < wthr
        rid = _stable_relation_id(src, tgt, relation_type, evid_doc, generation_id or "")
        out.append(
            GraphEvidence(
                source_entity=src,
                target_entity=tgt,
                relation_id=rid,
                relation_type=relation_type,
                direction=_edge_direction(relation_type),
                evidence_doc_id=evid_doc,
                confidence=confidence,
                generation_id=generation_id,
                weak_evidence=weak,
                inferred_relation=weak,
            )
        )
    return out


class GraphExpansionPostprocessor(BaseNodePostprocessor):
    """Добавляет чанки из смежных по графу документов."""

    def __init__(
        self,
        *,
        base_index: Any,
        base_filters: MetadataFilters | None,
        similarity_top_k: int,
        query_type: str,
        max_extra_docs: int,
        classify_confidence: float = 1.0,
        effective_profile: str = "quality",
        effective_graph_augmented: bool = True,
        use_composite_graph_gating: bool = False,
    ) -> None:
        super().__init__()
        self._base_index = base_index
        self._base_filters = base_filters
        self._similarity_top_k = similarity_top_k
        self._query_type = (query_type or "").strip().lower()
        self._max_extra_docs = max(0, int(max_extra_docs))
        try:
            self._classify_confidence = float(classify_confidence)
        except (TypeError, ValueError):
            self._classify_confidence = 0.0
        self._effective_profile = (effective_profile or "quality").strip().lower()
        self._effective_graph_augmented = bool(effective_graph_augmented)
        self._use_composite_graph_gating = bool(use_composite_graph_gating)

    def _postprocess_nodes(
        self,
        nodes: list[NodeWithScore],
        query_bundle: QueryBundle | None = None,
    ) -> list[NodeWithScore]:
        from app.rag_runtime_preferences import effective_settings

        s = effective_settings()
        holder = _graph_expansion_trace_ctx.get()
        if isinstance(holder, dict):
            holder.pop("graph_expansion", None)

        t0 = time.perf_counter()

        def _put_graph_trace(tr: dict[str, Any]) -> None:
            tr["graph_expansion_ms"] = round((time.perf_counter() - t0) * 1000, 3)
            if isinstance(holder, dict):
                holder["graph_expansion"] = tr
        if not s.enable_graph_augmented_retrieval:
            return nodes
        if self._query_type not in GRAPH_AUGMENT_QUERY_TYPES:
            _put_graph_trace({"skipped": True, "reason": "query_type"})
            return nodes
        if self._max_extra_docs == 0:
            _put_graph_trace({"skipped": True, "reason": "max_extra_zero"})
            return nodes

        qstr = ""
        if query_bundle is not None:
            qstr = getattr(query_bundle, "query_str", None) or str(query_bundle)
        if not qstr.strip():
            _put_graph_trace({"skipped": True, "reason": "empty_query"})
            return nodes

        baseline_ct = baseline_unique_node_count(nodes)
        ok_gate, gate_reason = evaluate_composite_graph_gating(
            use_composite_graph_gating=self._use_composite_graph_gating,
            effective_graph_augmented=self._effective_graph_augmented,
            classify_confidence=self._classify_confidence,
            graph_augment_min_confidence=float(s.graph_augment_min_confidence),
            baseline_dedupe_count=baseline_ct,
            baseline_thin_k=int(s.graph_augment_baseline_thin_k),
            effective_profile=self._effective_profile,
        )
        if not ok_gate:
            _put_graph_trace(
                {
                    "skipped": True,
                    "reason": gate_reason,
                    "composite_gating": True,
                    "baseline_dedupe_count": baseline_ct,
                    "effective_profile": self._effective_profile,
                    "classify_confidence": self._classify_confidence,
                }
            )
            return nodes

        try:
            from app.knowledge_graph import get_active_knowledge_graph

            kg = get_active_knowledge_graph()
            concepts = kg.get_concepts()
        except Exception as exc:  # noqa: BLE001 - KG load may fail opaquely; passthrough base nodes
            logger.error("graph_expansion_kg_failed | error=%s", exc, exc_info=True)
            _put_graph_trace({"ok": False, "error": str(exc), "error_type": type(exc).__name__})
            return nodes

        seed_ids = extract_doc_ids_from_nodes(nodes)
        added_ids, trace = expand_doc_ids_via_graph(
            seed_ids,
            concepts,
            max_extra=self._max_extra_docs,
            max_hops=int(s.graph_expand_max_hops),
        )
        if not added_ids:
            trace["skipped"] = True
            trace["reason"] = "no_extra_docs"
            _put_graph_trace(trace)
            return nodes

        reason_by_doc: dict[str, list[dict[str, Any]]] = {}
        sample = trace.get("added_doc_reason_sample") or []
        if isinstance(sample, list):
            for item in sample:
                if not isinstance(item, dict):
                    continue
                did = str(item.get("doc_id") or "").strip()
                reasons = item.get("reasons")
                if did and isinstance(reasons, list):
                    reason_by_doc[did] = [r for r in reasons if isinstance(r, dict)]

        gen_id = _active_kg_generation_id()
        all_evidence: list[dict[str, Any]] = []

        extra_nodes: list[NodeWithScore] = []
        for doc_id in added_ids:
            try:
                got = _retrieve_chunks_for_doc(
                    self._base_index,
                    qstr,
                    doc_id,
                    self._similarity_top_k,
                    self._base_filters,
                )
                rows = reason_by_doc.get(str(doc_id).strip()) or []
                evidences = graph_evidences_from_reason_rows(
                    doc_id=str(doc_id),
                    reason_rows=rows,
                    classify_confidence=self._classify_confidence,
                    weak_threshold=float(s.graph_evidence_weak_threshold),
                    generation_id=gen_id,
                )
                evid_dump = [e.model_dump() for e in evidences][:5]
                for item in evid_dump:
                    all_evidence.append(dict(item))

                for nws in got:
                    node_inner = getattr(nws, "node", None)
                    if node_inner is None:
                        continue
                    meta = getattr(node_inner, "metadata", None)
                    if meta is None:
                        node_inner.metadata = {}
                        meta = node_inner.metadata
                    if not isinstance(meta, dict):
                        continue
                    meta["retrieval_source"] = "graph_expansion"
                    if evid_dump:
                        meta["graph_evidence"] = list(evid_dump)

                extra_nodes.extend(got)
            except Exception as exc:  # noqa: BLE001 - per-doc retriever may fail for many reasons; skip doc
                logger.error("graph_expansion_doc_failed | doc_id=%s error=%s", doc_id, exc, exc_info=True)

        if not extra_nodes:
            trace["skipped"] = True
            trace["reason"] = "no_chunks_for_added_docs"
            _put_graph_trace(trace)
            return nodes

        seen: set[str] = set()
        for nws in nodes:
            seen.add(_node_dedupe_key(nws))

        merged = list(nodes)
        for nws in extra_nodes:
            k = _node_dedupe_key(nws)
            if k in seen:
                continue
            seen.add(k)
            merged.append(nws)

        trace["ok"] = True
        trace["extra_chunk_count"] = len(extra_nodes)
        trace["merged_total"] = len(merged)
        if all_evidence:
            trace["graph_evidence"] = all_evidence[:24]
            trace["weak_graph_evidence_count"] = sum(
                1 for row in all_evidence if isinstance(row, dict) and row.get("weak_evidence")
            )
        _put_graph_trace(trace)
        log_event(
            logger,
            logging.INFO,
            "graph_expansion_applied",
            added_docs=len(added_ids),
            merged_total=len(merged),
        )
        return merged


def append_graph_expansion_postprocessor(
    postprocessors: list,
    *,
    execution_plan_query_type: str,
    base_index: Any,
    filters: Any,
    similarity_top_k: int,
    classify_confidence: float = 1.0,
    effective_profile: str = "quality",
    effective_graph_augmented: bool = True,
    use_composite_graph_gating: bool = False,
) -> list:
    """Добавляет graph expansion в конец цепочки postprocessors."""
    from app.rag_runtime_preferences import effective_settings

    settings = effective_settings()
    if not settings.enable_graph_augmented_retrieval:
        return postprocessors
    q = (execution_plan_query_type or "").strip().lower()
    if q not in GRAPH_AUGMENT_QUERY_TYPES:
        return postprocessors
    max_extra = int(settings.graph_augment_max_extra_docs)
    pp = list(postprocessors)
    pp.append(
        GraphExpansionPostprocessor(
            base_index=base_index,
            base_filters=filters,
            similarity_top_k=similarity_top_k,
            query_type=q,
            max_extra_docs=max_extra,
            classify_confidence=classify_confidence,
            effective_profile=effective_profile,
            effective_graph_augmented=effective_graph_augmented,
            use_composite_graph_gating=use_composite_graph_gating,
        )
    )
    return pp


@contextmanager
def graph_expansion_trace_scope() -> Generator[dict[str, Any], None, None]:
    """Привязывает dict для trace graph expansion на время ``engine.query``."""
    box: dict[str, Any] = {}
    token = _graph_expansion_trace_ctx.set(box)
    try:
        yield box
    finally:
        _graph_expansion_trace_ctx.reset(token)
