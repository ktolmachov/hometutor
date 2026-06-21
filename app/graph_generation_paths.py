"""
Пути артефактов knowledge graph по generation (blue-green), ADR-020.

Staging: ``data/graph_generations/staging/<slug>`` — до swap.
Active: ``data/graph_generations/by_generation/<generation_id>/`` — после активации.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from app.config import DATA_DIR
from app.logging_config import setup_logging

logger = setup_logging()

GRAPH_GENERATIONS_ROOT = DATA_DIR / "graph_generations"
STAGING_ROOT = GRAPH_GENERATIONS_ROOT / "staging"
BY_GENERATION_ROOT = GRAPH_GENERATIONS_ROOT / "by_generation"


def _slug_collection_name(collection_name: str) -> str:
    t = re.sub(r"[^a-zA-Z0-9_.-]+", "_", (collection_name or "").strip())[:120].strip("_")
    return t or "staging"


def staging_bundle_dir(staging_chunks_collection: str) -> Path:
    """Каталог сборки графа для текущей staging-коллекции Chroma (уникален на reindex)."""
    return STAGING_ROOT / _slug_collection_name(staging_chunks_collection)


def generation_bundle_dir(generation_id: str) -> Path:
    """Каталог графа для активной (или исторической) generation из registry."""
    gid = (generation_id or "").strip() or "legacy"
    return BY_GENERATION_ROOT / gid


def promote_staging_bundle(staging_chunks_collection: str, generation_id: str) -> bool:
    """
    После успешной активации staging: перенести артефакт графа в каталог generation.

    Если staging отсутствует (старый путь без bundle) — no-op, False.
    Gate-before-promote: skip when graph_quality_report.json reports gate_passed=false.
    """
    from app.knowledge_graph_bundle import staging_bundle_gate_allows_promote

    if not staging_bundle_gate_allows_promote(staging_chunks_collection):
        logger.info(
            "knowledge_graph_promote_skip | reason=gate_not_passed | collection=%s",
            staging_chunks_collection,
        )
        return False
    src = staging_bundle_dir(staging_chunks_collection)
    if not src.exists():
        logger.info(
            "knowledge_graph_promote_skip | staging_missing=%s",
            src,
        )
        return False
    dst = generation_bundle_dir(generation_id)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.move(str(src), str(dst))
    logger.info(
        "knowledge_graph_promoted | from=%s | to=%s | generation_id=%s",
        src,
        dst,
        generation_id,
    )
    return True
