#!/usr/bin/env python3
"""Rebuild the knowledge graph bundle for the active index generation.

Does not re-embed Chroma chunks — only re-runs graph compilation / heuristic
fallback from documents in ``data/``. Use after a failed graph LLM extraction
or registry/data-root migration.

Usage::

    .\\.venv\\Scripts\\python.exe scripts/rebuild_knowledge_graph.py
    .\\.venv\\Scripts\\python.exe scripts/rebuild_knowledge_graph.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild knowledge graph for active generation.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load documents and print plan without writing kg.sqlite.",
    )
    args = parser.parse_args(argv)

    from app.config import CHROMA_DIR, DATA_DIR, get_settings
    from app.index_registry import get_active_generation_view
    from app.ingestion_content_state import build_file_manifest, compute_doc_content_hashes
    import app.ingestion as ing
    from app.knowledge_graph import (
        get_active_knowledge_graph,
        invalidate_knowledge_graph_singleton,
        write_generation_knowledge_graph_bundle,
    )

    settings = get_settings()
    view = get_active_generation_view()
    generation_id = str(view.generation_id or "").strip()
    if not generation_id or generation_id == "legacy":
        print(
            "ERROR: active generation is unset or legacy — run ingest.py first.",
            file=sys.stderr,
        )
        return 1

    file_manifest = build_file_manifest(DATA_DIR, ing.get_doc_supported_exts())
    if not file_manifest:
        print(f"ERROR: no supported files under {DATA_DIR}", file=sys.stderr)
        return 1

    documents = ing._load_documents_with_extraction_cache(  # noqa: SLF001 — CLI orchestration
        data_dir=DATA_DIR,
        chroma_dir=CHROMA_DIR,
        file_manifest=file_manifest,
    )
    if not documents:
        print("ERROR: document loader returned zero fragments.", file=sys.stderr)
        return 1

    current_hashes = compute_doc_content_hashes(documents)
    source_paths = sorted(current_hashes)
    source_content_hashes = sorted(set(current_hashes.values()))
    existing_concepts = get_active_knowledge_graph().get_concepts()

    plan = {
        "generation_id": generation_id,
        "documents_fragments": len(documents),
        "source_paths": len(source_paths),
        "existing_concepts": len(existing_concepts),
        "data_dir": str(DATA_DIR),
        "registry_path": str(settings.index_registry_path),
        "graph_llm_configured": bool((settings.graph_llm_api_base or settings.graph_model)),
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2))

    if args.dry_run:
        return 0

    stats = write_generation_knowledge_graph_bundle(
        documents,
        generation_id,
        existing_concepts=existing_concepts,
        source_paths=source_paths,
        source_content_hashes=source_content_hashes,
    )
    invalidate_knowledge_graph_singleton()
    ing.logger.info("rebuild_knowledge_graph | stats=%s", stats)
    print(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
    concepts = int(stats.get("concept_count") or stats.get("concepts") or 0)
    if concepts <= 0:
        print("WARN: graph bundle has zero concepts — check graph LLM or logs.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
