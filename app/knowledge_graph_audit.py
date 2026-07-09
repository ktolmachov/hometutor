"""Pure post-build audit helpers for Knowledge Graph bundles."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.course_folder_filter import is_user_source_path
from app.knowledge_graph import SqliteBundleKnowledgeGraph
from app.knowledge_graph_bundle import load_graph_quality_report

GRAPH_AUDIT_JSON_NAME = "graph_audit_report.json"
GRAPH_AUDIT_MD_NAME = "graph_audit_report.md"


def _norm(value: object) -> str:
    return re.sub(r"[^a-zа-яё0-9]+", "-", str(value or "").strip().lower()).strip("-")


def _concept_paths(concept_id: str, info: dict[str, Any]) -> list[str]:
    values = [
        *(info.get("related_documents") or []),
        *(info.get("documents") or []),
    ]
    provenance = info.get("provenance")
    if isinstance(provenance, dict):
        values.append(provenance.get("source_doc_id"))
    if concept_id.startswith("lesson:") and not values:
        values.append(concept_id.removeprefix("lesson:"))
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        path = str(raw or "").strip().replace("\\", "/")
        if path and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _concept_terms(concept_id: str, info: dict[str, Any]) -> set[str]:
    terms = {concept_id, info.get("label"), info.get("normalized_label")}
    terms.update(info.get("aliases") or [])
    return {_norm(term) for term in terms if _norm(term)}


def _duplicate_candidates(concepts: dict[str, Any], *, limit: int = 20) -> list[dict[str, str]]:
    items = [
        (str(cid), raw)
        for cid, raw in concepts.items()
        if isinstance(raw, dict) and not str(cid).startswith("lesson:")
    ]
    pairs: list[dict[str, str]] = []
    for idx, (left_id, left) in enumerate(items):
        left_terms = _concept_terms(left_id, left)
        if not left_terms:
            continue
        for right_id, right in items[idx + 1 :]:
            right_terms = _concept_terms(right_id, right)
            if not right_terms:
                continue
            overlap = sorted(left_terms & right_terms)
            left_label = _norm(left.get("label") or left_id)
            right_label = _norm(right.get("label") or right_id)
            nested = bool(
                left_label
                and right_label
                and left_label != right_label
                and (left_label in right_label or right_label in left_label)
            )
            if not overlap and not nested:
                continue
            pairs.append(
                {
                    "source": left_id,
                    "target": right_id,
                    "reason": "alias_overlap" if overlap else "nested_label",
                    "match": ", ".join(overlap[:3]) if overlap else f"{left_label} ↔ {right_label}",
                }
            )
    return pairs[:limit]


def build_graph_audit_report(
    *,
    concepts: dict[str, Any],
    typed_relations: list[dict[str, Any]],
    compiler_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    test_artifacts = [
        cid
        for cid, info in concepts.items()
        if isinstance(info, dict)
        and any(not is_user_source_path(path) for path in _concept_paths(str(cid), info))
    ]
    relations_without_evidence = [
        {
            "source": str(rel.get("source_concept_id") or rel.get("source") or "?"),
            "target": str(rel.get("target_concept_id") or rel.get("target") or "?"),
            "relation_type": str(rel.get("relation_type") or rel.get("type") or "relation"),
        }
        for rel in typed_relations
        if isinstance(rel, dict)
        and not (str(rel.get("evidence_doc_id") or "").strip() and str(rel.get("evidence_chunk_id") or "").strip())
    ]
    duplicates = _duplicate_candidates(concepts)
    metrics = compiler_report.get("metrics") if isinstance(compiler_report, dict) else {}
    fail_reasons = compiler_report.get("fail_reasons") if isinstance(compiler_report, dict) else []
    findings: list[dict[str, Any]] = []
    if test_artifacts:
        findings.append(
            {
                "severity": "P1",
                "kind": "test_artifacts",
                "title": f"Test/source artifacts in graph: {len(test_artifacts)}",
                "items": test_artifacts[:10],
            }
        )
    if relations_without_evidence:
        findings.append(
            {
                "severity": "P1",
                "kind": "relation_evidence",
                "title": f"Relations without full evidence: {len(relations_without_evidence)}",
                "items": relations_without_evidence[:10],
            }
        )
    if duplicates:
        findings.append(
            {
                "severity": "P2",
                "kind": "duplicate_candidates",
                "title": f"Duplicate/alias candidates: {len(duplicates)}",
                "items": duplicates[:10],
            }
        )
    next_actions: list[str] = []
    if test_artifacts:
        next_actions.append("Rebuild with source hygiene filter and verify test_artifacts=0.")
    if relations_without_evidence:
        next_actions.append("Inspect evidence_doc_id/evidence_chunk_id fallback for listed relations.")
    if duplicates:
        next_actions.append("Review duplicate candidates and decide merge/keep/parent-child.")
    if isinstance(fail_reasons, list) and fail_reasons:
        next_actions.append("Resolve compiler gate fail_reasons before publish.")
    if not next_actions:
        next_actions.append("No blocking audit findings detected.")
    return {
        "schema_version": 1,
        "gate_passed": bool((compiler_report or {}).get("gate_passed")),
        "published": bool((compiler_report or {}).get("published")),
        "metrics": metrics if isinstance(metrics, dict) else {},
        "fail_reasons": [str(item) for item in (fail_reasons or []) if str(item).strip()],
        "counters": {
            "concepts": len(concepts),
            "relations": len(typed_relations),
            "test_artifacts": len(test_artifacts),
            "relations_without_evidence": len(relations_without_evidence),
            "duplicate_candidates": len(duplicates),
        },
        "findings": findings,
        "next_actions": next_actions,
    }


def render_graph_audit_markdown(report: dict[str, Any]) -> str:
    counters = report.get("counters") if isinstance(report.get("counters"), dict) else {}
    lines = [
        "# Knowledge Graph Audit",
        "",
        f"- gate_passed: `{bool(report.get('gate_passed'))}`",
        f"- published: `{bool(report.get('published'))}`",
        f"- concepts: `{counters.get('concepts', 0)}`",
        f"- relations: `{counters.get('relations', 0)}`",
        f"- test_artifacts: `{counters.get('test_artifacts', 0)}`",
        f"- relations_without_evidence: `{counters.get('relations_without_evidence', 0)}`",
        f"- duplicate_candidates: `{counters.get('duplicate_candidates', 0)}`",
        "",
    ]
    fail_reasons = [str(item) for item in (report.get("fail_reasons") or []) if str(item).strip()]
    if fail_reasons:
        lines.extend(["## Gate Fail Reasons", ""])
        lines.extend(f"- {reason}" for reason in fail_reasons)
        lines.append("")
    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    if findings:
        lines.extend(["## Findings", ""])
        for item in findings:
            if not isinstance(item, dict):
                continue
            lines.append(f"- **{item.get('severity')} {item.get('kind')}**: {item.get('title')}")
            for sub in (item.get("items") or [])[:5]:
                lines.append(f"  - `{sub}`")
        lines.append("")
    lines.extend(["## Next Actions", ""])
    lines.extend(f"- {action}" for action in report.get("next_actions") or [])
    lines.append("")
    return "\n".join(lines)


def write_graph_audit_report(bundle_dir: Path | str) -> dict[str, Any]:
    bundle_path = Path(bundle_dir)
    kg = SqliteBundleKnowledgeGraph(bundle_path)
    report = build_graph_audit_report(
        concepts=kg.get_concepts(),
        typed_relations=kg.get_typed_relations(),
        compiler_report=load_graph_quality_report(bundle_path) or {},
    )
    (bundle_path / GRAPH_AUDIT_JSON_NAME).write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (bundle_path / GRAPH_AUDIT_MD_NAME).write_text(
        render_graph_audit_markdown(report),
        encoding="utf-8",
    )
    return report
