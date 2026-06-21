"""Pure helpers for prerequisite-aware weak-concept ordering in SSR."""

from __future__ import annotations

from typing import Any

from app.knowledge_graph import KnowledgeGraphReader


def _dedupe_weak_ids(weak_ids: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in weak_ids:
        wid = str(raw).strip()
        if not wid or wid in seen:
            continue
        seen.add(wid)
        deduped.append(wid)
    return deduped


def order_weak_concepts_for_ssr(
    weak_ids: list[str],
    kg: KnowledgeGraphReader,
) -> str | None:
    """Return prerequisite-first weak concept id, or None when graph signal is unusable."""
    deduped = _dedupe_weak_ids(weak_ids)
    if not deduped:
        return None

    concepts = kg.get_concepts()
    present = [wid for wid in deduped if wid in concepts]
    if not present:
        return None

    cycles = kg.find_prerequisite_cycles(present)
    if cycles:
        return None

    trace: dict[str, Any] = {}
    ordered = kg.topological_sort(present, trace=trace)
    if trace.get("topological_order_ok") is False:
        return None

    seen_ordered = set(ordered)
    tail = [wid for wid in deduped if wid not in seen_ordered]
    return (ordered + tail)[0]
