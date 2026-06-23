#!/usr/bin/env python3
"""Read-only audit of JSON concept_graph for SSR L4 readiness (cycles, dangling refs, topology)."""

# Package: kg-completeness-audit — contract write-set aligns with backlog deliverables only.

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR
from app.knowledge_graph import JsonKnowledgeGraph


def _normalized_prereqs(concept: dict) -> list[str]:
    if not isinstance(concept, dict):
        return []
    raw = concept.get("prerequisites")
    if raw is None or raw == []:
        raw = concept.get("prerequisite_for")
    out: list[str] = []
    for p in raw or []:
        s = str(p).strip()
        if s:
            out.append(s)
    return out


def _gather_metrics(graph_path: Path) -> dict:
    kg = JsonKnowledgeGraph(graph_path)
    concepts = kg.get_concepts()
    all_ids = sorted(cid for cid, c in concepts.items() if isinstance(c, dict))

    dangling: list[dict[str, str]] = []
    edge_count = 0
    concepts_with_any_prereq = 0
    invalid_entries = sum(1 for c in concepts.values() if not isinstance(c, dict))

    for cid in all_ids:
        c = concepts[cid]
        prereqs = _normalized_prereqs(c)
        if prereqs:
            concepts_with_any_prereq += 1
        for p in prereqs:
            if p not in concepts or not isinstance(concepts.get(p), dict):
                dangling.append({"concept_id": cid, "missing_prerequisite_id": p})
            elif p in all_ids:
                edge_count += 1

    trace: dict = {}
    cycles = kg.find_prerequisite_cycles(all_ids)
    kg.topological_sort(all_ids, trace=trace)
    topo_ok = bool(trace.get("topological_order_ok", True))

    dependents: dict[str, int] = {cid: 0 for cid in all_ids}
    prereqs_in_graph: dict[str, list[str]] = {}
    for cid in all_ids:
        ing: list[str] = []
        for p in _normalized_prereqs(concepts[cid]):
            if p in all_ids:
                ing.append(p)
                dependents[p] = dependents.get(p, 0) + 1
        prereqs_in_graph[cid] = ing

    orphan_spine = sum(
        1
        for cid in all_ids
        if len(prereqs_in_graph[cid]) == 0 and dependents.get(cid, 0) == 0
    )

    n = len(all_ids)

    classification: str
    notes: list[str] = []

    if cycles:
        classification = "blocker"
        notes.append("Prerequisite cycles prevent safe L4 prerequisite-aware routing.")
    elif not topo_ok:
        classification = "blocker"
        notes.append("Topological ordering failed — treat graph as blocking L4 until inspected.")
    elif n == 0:
        classification = "patchable"
        notes.append("Graph has no declared concepts — populate concepts before routing.")
    elif dangling:
        classification = "patchable"
        notes.append("Dangling prerequisite IDs must be repaired (not in concepts map).")
    elif n > 1 and edge_count == 0:
        classification = "patchable"
        notes.append(
            "Multiple concepts with zero in-graph prerequisite edges — weak prerequisite signal for L4."
        )
    else:
        classification = "ready"
        notes.append(
            "No prerequisite cycles detected; no dangling prerequisites; topo sort aligns with prerequisites."
        )

    return {
        "schema_version": 1,
        "graph_path": str(graph_path.resolve()),
        "concept_count": n,
        "invalid_concept_entries": invalid_entries,
        "concepts_with_declared_prerequisites": concepts_with_any_prereq,
        "prerequisite_internal_edge_count": edge_count,
        "dangling_prerequisite_count": len(dangling),
        "dangling_prerequisite_examples": dangling[:20],
        "cycle_count": len(cycles),
        "cycle_examples": cycles[:10],
        "topological_order_ok": topo_ok,
        "orphan_spine_count": orphan_spine,
        "ssr_l4_readiness_classification": classification,
        "notes": notes,
        "concept_graph_readable": graph_path.exists(),
        "audit_timestamp_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _write_report(md_path: Path, payload: dict) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# KG completeness audit (SSR L4 gate)",
        "",
        f"_Generated `{payload['audit_timestamp_iso']}` (UTC) from `_gather_metrics()`._",
        "",
        "## Classification",
        "",
        f"- **SSR L4 readiness:** `{payload['ssr_l4_readiness_classification']}`",
        f"- **Graph path:** `{payload['graph_path']}`",
        f"- **Readable path:** `{payload['concept_graph_readable']}`",
        "",
        "### Notes",
        "",
    ]
    for n in payload.get("notes") or []:
        lines.append(f"- {n}")
    lines.extend(
        [
            "",
            "## Metrics",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Concept count | {payload['concept_count']} |",
            f"| Concepts declaring any prerequisites | {payload['concepts_with_declared_prerequisites']} |",
            f"| Internal prerequisite edges (among declared IDs) | {payload['prerequisite_internal_edge_count']} |",
            f"| Dangling prerequisite refs | {payload['dangling_prerequisite_count']} |",
            f"| Cycle count | {payload['cycle_count']} |",
            f"| Topological order OK | {payload['topological_order_ok']} |",
            f"| Orphan spine nodes (no in/out prereq edges in-graph) | {payload['orphan_spine_count']} |",
            f"| Invalid concept entries | {payload['invalid_concept_entries']} |",
            "",
        ]
    )

    def _dump(title: str, items: object) -> None:
        lines.append(f"### {title}")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(items, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")

    if payload.get("dangling_prerequisite_examples"):
        _dump("Dangling examples (first entries)", payload["dangling_prerequisite_examples"])
    if payload.get("cycle_examples"):
        _dump("Cycle examples", payload["cycle_examples"])

    lines.extend(
        [
            "## Follow-ups",
            "",
            "- This package is **audit-only**; repair belongs to separate backlog work.",
            "- For SQLite bundle deployments, audit the bundle export JSON or staged `concept_graph.json` explicitly.",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit SSR L4 prerequisites over concept_graph JSON.")
    parser.add_argument(
        "--graph",
        type=Path,
        default=None,
        help=f"concept_graph JSON path (default: DATA_DIR/concept_graph.json → {DATA_DIR / 'concept_graph.json'})",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "doc" / "kg_completeness_report.md",
        help="Markdown report output path.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Skip writing Markdown report.",
    )
    args = parser.parse_args()

    gpath = Path(args.graph) if args.graph is not None else Path(DATA_DIR) / "concept_graph.json"
    if not gpath.exists():
        stub = {
            "schema_version": 1,
            "graph_path": str(gpath.resolve()),
            "concept_graph_readable": False,
            "concept_count": 0,
            "invalid_concept_entries": 0,
            "concepts_with_declared_prerequisites": 0,
            "prerequisite_internal_edge_count": 0,
            "dangling_prerequisite_count": 0,
            "dangling_prerequisite_examples": [],
            "cycle_count": 0,
            "cycle_examples": [],
            "topological_order_ok": True,
            "orphan_spine_count": 0,
            "ssr_l4_readiness_classification": "patchable",
            "notes": [
                "Graph file missing — treat coverage as incomplete; populate/export JSON before trusting L4 scoping.",
            ],
            "audit_timestamp_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        print(json.dumps(stub, ensure_ascii=False, indent=2))
        if not args.no_write:
            _write_report(Path(args.report), stub)
        return 0

    payload = _gather_metrics(gpath)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not args.no_write:
        _write_report(Path(args.report), payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
