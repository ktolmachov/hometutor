"""
Сборка и сохранение knowledge graph bundle: SQLite payload + LlamaIndex PropertyGraph store.

Итерация 16 tail (ADR-020): персистентность не одним JSON; увязка с generation.
Course Graph Compiler (course-graph-compiler-v1): gate-before-promote + quality sidecar.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

from app.graph_generation_paths import generation_bundle_dir, staging_bundle_dir
from app.logging_config import setup_logging

logger = setup_logging()

KG_SQLITE_NAME = "kg.sqlite"
PROPERTY_GRAPH_STORE_NAME = "property_graph_store.json"
GRAPH_QUALITY_REPORT_NAME = "graph_quality_report.json"


class KnowledgeGraphBundleError(RuntimeError):
    """Raised when the bundle SQLite artifact cannot be read or written."""


def load_graph_snapshot_payload(bundle_dir: Path | str) -> str | None:
    """Read the JSON graph snapshot payload from a bundle-owned SQLite artifact."""
    sqlite_path = Path(bundle_dir) / KG_SQLITE_NAME
    if not sqlite_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(sqlite_path))
        try:
            row = conn.execute("SELECT payload FROM graph_snapshot WHERE id=1").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise KnowledgeGraphBundleError(f"Failed to load graph snapshot from {sqlite_path}") from exc
    if not row or not row[0]:
        return None
    return str(row[0])


def write_graph_snapshot_payload(bundle_dir: Path | str, payload: str) -> None:
    """Write the JSON graph snapshot payload to a bundle-owned SQLite artifact."""
    bundle_path = Path(bundle_dir)
    sqlite_path = bundle_path / KG_SQLITE_NAME
    try:
        bundle_path.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(sqlite_path))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS graph_snapshot (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)"
            )
            conn.execute("INSERT OR REPLACE INTO graph_snapshot (id, payload) VALUES (1, ?)", (payload,))
            conn.commit()
        finally:
            conn.close()
    except (OSError, sqlite3.Error) as exc:
        raise KnowledgeGraphBundleError(f"Failed to write graph snapshot to {sqlite_path}") from exc


def write_graph_quality_report_sidecar(bundle_dir: Path | str, report: dict[str, Any]) -> None:
    """Persist compact quality report next to bundle artifacts."""
    path = Path(bundle_dir) / GRAPH_QUALITY_REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def load_graph_quality_report(bundle_dir: Path | str) -> dict[str, Any] | None:
    path = Path(bundle_dir) / GRAPH_QUALITY_REPORT_NAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def staging_bundle_gate_allows_promote(staging_chunks_collection: str) -> bool:
    """True only when the staging sidecar explicitly reports gate_passed."""
    report = load_graph_quality_report(staging_bundle_dir(staging_chunks_collection))
    if report is None:
        return False
    return bool(report.get("gate_passed"))


def _graph_dict_to_simple_property_graph_store(data: Dict[str, Any]) -> Any:
    """Строит SimplePropertyGraphStore из словаря (концепты + prerequisites + related)."""
    from llama_index.core.graph_stores.simple_labelled import SimplePropertyGraphStore
    from llama_index.core.graph_stores.types import EntityNode, Relation

    store = SimplePropertyGraphStore()
    concepts = data.get("concepts") or {}
    seen_entities: set[str] = set()

    for name, c in concepts.items():
        if not isinstance(c, dict):
            continue
        clean = str(c.get("label") or name).strip()
        if not clean:
            continue
        props = {
            k: v
            for k, v in c.items()
            if k not in ("prerequisites", "related_concepts", "documents", "related_documents")
        }
        store.upsert_nodes([EntityNode(name=clean, properties=props)])
        seen_entities.add(clean)

        for p in c.get("prerequisites") or []:
            ps = str(p).strip()
            if not ps or ps == clean:
                continue
            if ps not in seen_entities:
                store.upsert_nodes([EntityNode(name=ps, properties={})])
                seen_entities.add(ps)
            store.upsert_relations(
                [
                    Relation(
                        label="prerequisite_for",
                        source_id=ps,
                        target_id=clean,
                        properties={},
                    )
                ]
            )

        for r in c.get("related_concepts") or []:
            rs = str(r).strip()
            if not rs or rs == clean:
                continue
            if rs not in seen_entities:
                store.upsert_nodes([EntityNode(name=rs, properties={})])
                seen_entities.add(rs)
            store.upsert_relations(
                [
                    Relation(
                        label="related_concept",
                        source_id=clean,
                        target_id=rs,
                        properties={},
                    )
                ]
            )

    return store


def persist_graph_bundle_to_dir(bundle_dir: Path, data: Dict[str, Any]) -> None:
    """
    1) Полный JSON-снимок в SQLite (совместимость с JsonKnowledgeGraph-логикой).
    2) SimplePropertyGraphStore → property_graph_store.json (артефакт PropertyGraphIndex / LlamaIndex).
    """
    bundle_dir = Path(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = bundle_dir / KG_SQLITE_NAME

    payload = json.dumps(data, ensure_ascii=False)
    write_graph_snapshot_payload(bundle_dir, payload)

    store = _graph_dict_to_simple_property_graph_store(data)
    pg_path = bundle_dir / PROPERTY_GRAPH_STORE_NAME
    pg_path.write_text(store.graph.model_dump_json(), encoding="utf-8")

    logger.info(
        "knowledge_graph_bundle_persisted | dir=%s | concepts=%s | sqlite=%s | pgi_store=%s",
        bundle_dir,
        len((data.get("concepts") or {})),
        sqlite_path.name,
        pg_path.name,
    )


def _quality_summary_from_report(report_dict: dict[str, Any]) -> dict[str, Any]:
    return {
        "gate_passed": bool(report_dict.get("gate_passed")),
        "published": bool(report_dict.get("published")),
        "metrics": dict(report_dict.get("metrics") or {}),
        "gates": list(report_dict.get("gates") or []),
        "fail_reasons": list(report_dict.get("fail_reasons") or []),
        "generation_id": str(report_dict.get("generation_id") or ""),
        "scope_hash": str(report_dict.get("scope_hash") or ""),
    }


def write_bundle_via_compiler(
    documents: List[Any],
    *,
    bundle_dir: Path,
    generation_id: str,
    scope_hash: str,
    source_content_hashes: list[str] | None = None,
    existing_concepts: Dict[str, Dict] | None = None,
    source_paths: list[str] | None = None,
    bind_on_publish: bool = True,
    llm_extract_fn=None,
) -> Dict[str, Any]:
    """Compile course graph, persist bundle + quality sidecar; publish only when gate_passed."""
    from app.course_cache import normalize_source_paths
    from app.course_graph_compiler import compile_course_graph

    # Normalize once so compiler sidecar matches heuristic path contract.
    paths = normalize_source_paths(source_paths or [])
    hashes = sorted({str(h).strip() for h in (source_content_hashes or []) if str(h).strip()})

    result = compile_course_graph(
        documents,
        generation_id=generation_id,
        scope_hash=scope_hash,
        source_content_hashes=hashes,
        existing_concepts=existing_concepts or {},
        llm_extract_fn=llm_extract_fn,
    )
    report_dict = result.quality_report.model_dump()
    report_dict["published"] = False
    report_dict["source_paths"] = list(paths)
    report_dict["source_content_hashes"] = list(hashes)
    rel_count = result.relation_count

    if result.payload:
        persist_graph_bundle_to_dir(bundle_dir, result.payload)
        rel_count = int(result.payload.pop("_relation_count", rel_count))
        if result.gate_passed:
            report_dict["published"] = True
            result.published = True
            result.quality_report.published = True
        write_graph_quality_report_sidecar(bundle_dir, report_dict)
    elif documents:
        from app.knowledge_graph_payload import build_graph_payload_from_documents

        heuristic_data = build_graph_payload_from_documents(documents, existing_concepts or {})
        if heuristic_data.get("concepts"):
            compiler_fail_reasons = list(report_dict.get("fail_reasons") or [])
            heuristic_stats = _heuristic_bundle_stats(
                bundle_dir,
                heuristic_data,
                generation_id=generation_id,
                scope_hash=scope_hash,
                source_paths=paths,
                source_content_hashes=hashes,
                report_overrides={
                    "compiler_fail_reasons": compiler_fail_reasons,
                    "heuristic_fallback": True,
                    "fail_reasons": [
                        *compiler_fail_reasons,
                        "Heuristic fallback after compiler failure (metadata-only graph)",
                    ],
                },
            )
            heuristic_stats["compiler_error"] = result.error
            heuristic_stats["heuristic_fallback"] = True
            heuristic_stats["truncated"] = result.truncated
            return heuristic_stats
        write_graph_quality_report_sidecar(bundle_dir, report_dict)
    else:
        write_graph_quality_report_sidecar(bundle_dir, report_dict)

    if bind_on_publish and result.gate_passed and paths:
        from app.course_cache import update_course_graph_binding

        update_course_graph_binding(
            paths,
            generation_id=generation_id,
            scope_hash=scope_hash,
            graph_quality_summary=_quality_summary_from_report(report_dict),
            source_content_hashes=hashes,
        )

    quality_report = _quality_summary_from_report(report_dict)
    return {
        "ok": True,
        "published": bool(report_dict.get("published")),
        "gate_passed": result.gate_passed,
        "quality_report": quality_report,
        "generation_id": generation_id,
        "scope_hash": scope_hash,
        "concept_count": result.concept_count,
        "relation_count": rel_count,
        "cross_doc_relations": result.cross_doc_relations,
        "documents": len(result.payload.get("documents") or {}) if result.payload else 0,
        "concepts": result.concept_count,
        "relations": rel_count,
        "path": str(bundle_dir),
        "storage": "sqlite_bundle",
        "truncated": result.truncated,
        "error": result.error,
    }


def _heuristic_bundle_stats(
    bundle_dir: Path,
    data: Dict[str, Any],
    *,
    generation_id: str,
    scope_hash: str,
    source_paths: list[str] | None = None,
    source_content_hashes: list[str] | None = None,
    report_overrides: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    rel_count = int(data.pop("_relation_count", 0))
    persist_graph_bundle_to_dir(bundle_dir, data)
    report = {
        "generation_id": generation_id,
        "scope_hash": scope_hash,
        "gate_passed": False,
        "published": False,
        "metrics": {
            "concept_count": len(data.get("concepts") or {}),
            "semantic_relation_count": rel_count,
        },
        "gates": [],
        "fail_reasons": ["Heuristic fallback path — semantic gate не пройден"],
    }
    # Normalize so sidecar matches compiler path contract.
    from app.course_cache import normalize_source_paths

    paths = normalize_source_paths(source_paths) if source_paths is not None else []
    hashes: list[str] = []
    if source_paths is not None:
        report["source_paths"] = paths
    if source_content_hashes is not None:
        hashes = sorted({str(h).strip() for h in source_content_hashes if str(h).strip()})
        report["source_content_hashes"] = hashes
    if report_overrides:
        report.update(report_overrides)
    write_graph_quality_report_sidecar(bundle_dir, report)

    return {
        "ok": True,
        "published": False,
        "gate_passed": False,
        "quality_report": _quality_summary_from_report(report),
        "generation_id": generation_id,
        "scope_hash": scope_hash,
        "concept_count": len(data.get("concepts") or {}),
        "relation_count": rel_count,
        "cross_doc_relations": 0,
        "documents": len(data.get("documents") or {}),
        "concepts": len(data.get("concepts") or {}),
        "relations": rel_count,
        "path": str(bundle_dir),
        "storage": "sqlite_bundle",
        "source_paths": paths,
        "source_content_hashes": hashes,
    }


def write_bundle_for_staging(
    documents: List[Any],
    staging_chunks_collection: str,
    existing_concepts: Dict[str, Dict],
    *,
    generation_id: str = "",
    scope_hash: str = "",
    source_content_hashes: list[str] | None = None,
    source_paths: list[str] | None = None,
    use_compiler: bool = False,
    llm_extract_fn=None,
) -> Dict[str, Any]:
    """Пишет bundle в staging-каталог (до swap)."""
    bundle_dir = staging_bundle_dir(staging_chunks_collection)
    if use_compiler:
        from app.course_cache import course_scope_hash, normalize_source_paths

        paths = normalize_source_paths(source_paths or [])
        gid = generation_id or f"staging:{staging_chunks_collection}"
        sh = scope_hash or (course_scope_hash(paths) if paths else "global")
        return write_bundle_via_compiler(
            documents,
            bundle_dir=bundle_dir,
            generation_id=gid,
            scope_hash=sh,
            source_content_hashes=source_content_hashes,
            existing_concepts=existing_concepts,
            source_paths=paths or None,
            bind_on_publish=False,
            llm_extract_fn=llm_extract_fn,
        )

    from app.knowledge_graph import build_graph_payload_from_documents

    data = build_graph_payload_from_documents(documents, existing_concepts)
    return _heuristic_bundle_stats(
        bundle_dir,
        data,
        generation_id=generation_id or "staging",
        scope_hash=scope_hash or "heuristic",
        source_paths=source_paths,
        source_content_hashes=source_content_hashes,
    )


def retarget_staging_bundle_generation(
    staging_chunks_collection: str,
    generation_id: str,
) -> bool:
    """Rewrite staging provenance to the generation assigned during activation."""
    bundle_dir = staging_bundle_dir(staging_chunks_collection)
    report = load_graph_quality_report(bundle_dir)
    payload_raw = load_graph_snapshot_payload(bundle_dir)
    if report is None or payload_raw is None:
        return False
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError as exc:
        raise KnowledgeGraphBundleError("Invalid staging graph snapshot JSON") from exc
    if not isinstance(payload, dict):
        raise KnowledgeGraphBundleError("Invalid staging graph snapshot payload")

    payload["generation_id"] = generation_id
    for concept in (payload.get("concepts") or {}).values():
        if isinstance(concept, dict):
            provenance = concept.get("provenance")
            if isinstance(provenance, dict):
                provenance["generation_id"] = generation_id
    for relation in payload.get("typed_relations") or []:
        if isinstance(relation, dict):
            relation["generation_id"] = generation_id
    report["generation_id"] = generation_id
    persist_graph_bundle_to_dir(bundle_dir, payload)
    write_graph_quality_report_sidecar(bundle_dir, report)
    return True


def bind_promoted_course_graph(generation_id: str) -> bool:
    """Update course binding only after a gate-passed bundle was promoted."""
    report = load_graph_quality_report(generation_bundle_dir(generation_id))
    if not report or not report.get("gate_passed"):
        return False
    source_paths = [str(path) for path in (report.get("source_paths") or []) if str(path).strip()]
    if not source_paths:
        return False
    from app.course_cache import update_course_graph_binding

    update_course_graph_binding(
        source_paths,
        generation_id=generation_id,
        scope_hash=str(report.get("scope_hash") or ""),
        graph_quality_summary=_quality_summary_from_report(report),
        source_content_hashes=[
            str(value)
            for value in (report.get("source_content_hashes") or [])
            if str(value).strip()
        ],
    )
    return True


def write_bundle_for_generation(
    documents: List[Any],
    generation_id: str,
    existing_concepts: Dict[str, Dict],
    *,
    scope_hash: str = "",
    source_content_hashes: list[str] | None = None,
    source_paths: list[str] | None = None,
    use_compiler: bool = False,
    llm_extract_fn=None,
) -> Dict[str, Any]:
    """Пишет bundle сразу в каталог generation (reset=true)."""
    bundle_dir = generation_bundle_dir(generation_id)
    if use_compiler:
        from app.course_cache import course_scope_hash, normalize_source_paths

        paths = normalize_source_paths(source_paths or [])
        sh = scope_hash or (course_scope_hash(paths) if paths else "global")
        return write_bundle_via_compiler(
            documents,
            bundle_dir=bundle_dir,
            generation_id=generation_id,
            scope_hash=sh,
            source_content_hashes=source_content_hashes,
            existing_concepts=existing_concepts,
            source_paths=paths or None,
            llm_extract_fn=llm_extract_fn,
        )

    from app.knowledge_graph import build_graph_payload_from_documents

    data = build_graph_payload_from_documents(documents, existing_concepts)
    return _heuristic_bundle_stats(
        bundle_dir,
        data,
        generation_id=generation_id,
        scope_hash=scope_hash or "heuristic",
        source_paths=source_paths,
        source_content_hashes=source_content_hashes,
    )
