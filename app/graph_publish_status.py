"""Read-only Knowledge Graph publish status for UI diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Core helpers for set-based freshness (used only in gap computation; imported at top
# to avoid repeated import cost on every Mission Control render).
from app.course_cache import normalize_source_paths
from app.course_folder_filter import is_user_source_path


def _compact_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(report, dict):
        return None
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    fail_reasons: list[str] = []
    seen: set[str] = set()
    for reason in report.get("fail_reasons") or []:
        text = str(reason).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        fail_reasons.append(text)

    # A1 (wave-material-freshness): preserve the actual source_paths *set* (not just
    # count) so that graph_freshness_gap can detect staleness of the *set* of materials,
    # not merely |index| != |graph|. Technical/service paths are filtered at comparison time.
    sp = report.get("source_paths")
    source_paths: list[str] = []
    if isinstance(sp, (list, tuple)):
        source_paths = [str(p).strip() for p in sp if str(p).strip()]

    ch = report.get("source_content_hashes")
    source_content_hashes: list[str] = []
    if isinstance(ch, (list, tuple)):
        source_content_hashes = sorted({str(h).strip() for h in ch if str(h).strip()})

    return {
        "gate_passed": bool(report.get("gate_passed")),
        "published": bool(report.get("published")),
        "generation_id": str(report.get("generation_id") or ""),
        "scope_hash": str(report.get("scope_hash") or ""),
        "metrics": metrics,
        "fail_reasons": fail_reasons,
        "source_paths_count": len(source_paths),
        "source_paths": source_paths,
        "source_content_hashes": source_content_hashes,
        "source_content_hashes_count": len(source_content_hashes),
    }


def _bundle_state(label: str, generation: dict[str, Any] | None) -> dict[str, Any]:
    from app.graph_generation_paths import generation_bundle_dir
    from app.knowledge_graph_bundle import load_graph_quality_report

    gid = str((generation or {}).get("generation_id") or "").strip()
    bundle_dir = generation_bundle_dir(gid) if gid else Path("")
    sqlite_path = bundle_dir / "kg.sqlite" if gid else Path("")
    exists = bool(gid and sqlite_path.exists())
    report = load_graph_quality_report(bundle_dir) if exists else None
    return {
        "label": label,
        "generation_id": gid,
        "chunks_collection": str((generation or {}).get("chunks_collection") or ""),
        "bundle_dir": str(bundle_dir) if gid else "",
        "exists": exists,
        "report": _compact_report(report),
    }


def _staging_states(limit: int) -> list[dict[str, Any]]:
    from app.graph_generation_paths import STAGING_ROOT
    from app.knowledge_graph_bundle import load_graph_quality_report

    if not STAGING_ROOT.exists():
        return []
    dirs = sorted(
        [path for path in STAGING_ROOT.iterdir() if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    for bundle_dir in dirs[: max(0, limit)]:
        sqlite_path = bundle_dir / "kg.sqlite"
        report = load_graph_quality_report(bundle_dir)
        out.append(
            {
                "label": bundle_dir.name,
                "bundle_dir": str(bundle_dir),
                "exists": sqlite_path.exists(),
                "report": _compact_report(report),
            }
        )
    return out


def get_graph_publish_status(*, staging_limit: int = 3) -> dict[str, Any]:
    """Return current active/previous/staging graph publish state for UI panels."""
    from app.index_registry import load_registry

    registry = load_registry()
    active = _bundle_state("active", registry.get("active_generation") or {})
    previous = _bundle_state("previous", registry.get("previous_generation") or {})
    staging = _staging_states(staging_limit)

    if active["exists"]:
        reader_source = "active"
        reader_generation_id = active["generation_id"]
    elif previous["exists"]:
        reader_source = "previous"
        reader_generation_id = previous["generation_id"]
    else:
        reader_source = "legacy"
        reader_generation_id = ""

    latest_failed_staging = next(
        (
            item
            for item in staging
            if item.get("exists")
            and isinstance(item.get("report"), dict)
            and not item["report"].get("gate_passed")
        ),
        None,
    )
    return {
        "reader_source": reader_source,
        "reader_generation_id": reader_generation_id,
        "active": active,
        "previous": previous,
        "staging": staging,
        "latest_failed_staging": latest_failed_staging,
    }


def graph_freshness_gap(
    index_stats: dict[str, Any] | None, publish_status: dict[str, Any] | None
) -> int:
    """How many indexed *user* materials are not yet on the published graph (0 = fresh).

    Compares the *set* (normalized) of currently-indexed source files against the
    ``source_paths`` (and when present ``source_content_hashes``) from the active
    graph bundle quality report.

    This is set-based (not count) so that renames, replaces, adds/removes with same
    cardinality are correctly reported as lag. Content hashes are stored for
    contract (heuristic now preserves them) and can be used for finer content-staleness
    in future; current gap uses the path set (index side currently provides files list).

    Falls back to count only for very old reports. Non-user paths filtered.
    """
    if not isinstance(index_stats, dict) or not isinstance(publish_status, dict):
        return 0

    indexed_raw = index_stats.get("files") or []
    indexed = [
        str(f).strip()
        for f in indexed_raw
        if str(f).strip() and is_user_source_path(str(f).strip())
    ]
    if not indexed:
        return 0

    active = publish_status.get("active") or {}
    report = active.get("report") or {}

    graph_paths_raw = report.get("source_paths")
    if isinstance(graph_paths_raw, (list, tuple)) and any(str(p).strip() for p in graph_paths_raw):
        try:
            idx_set = set(normalize_source_paths(indexed))
            g_set = set(normalize_source_paths([str(p) for p in graph_paths_raw]))
            missing = idx_set - g_set
            return len(missing)
        except Exception:  # noqa: BLE001 - never let freshness crash the home UI
            pass

    # Legacy fallback (old bundles or error): count only. May over/under report on set changes.
    on_graph = int(report.get("source_paths_count") or 0)
    return max(0, len(indexed) - on_graph)
