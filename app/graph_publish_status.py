"""Read-only Knowledge Graph publish status for UI diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import Any


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
    return {
        "gate_passed": bool(report.get("gate_passed")),
        "published": bool(report.get("published")),
        "generation_id": str(report.get("generation_id") or ""),
        "scope_hash": str(report.get("scope_hash") or ""),
        "metrics": metrics,
        "fail_reasons": fail_reasons,
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
