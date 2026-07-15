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


# P3: status-independent copy for draft-map preview (not computed by the view).
LEARNER_MAP_PREVIEW_WARNING = (
    "Показан черновик карты, который ещё не прошёл проверку качества. "
    "Он виден для диагностики и не используется в ответах и плане."
)


def _metric_line(metrics: dict[str, Any], key: str, *, label: str, as_pct: bool = False) -> str | None:
    """P4: include a metric only when the key is present (skip synthetic zeros)."""
    if key not in metrics:
        return None
    raw = metrics.get(key)
    if raw is None:
        return None
    try:
        if as_pct:
            return f"{label} {round(float(raw), 1)}%"
        return f"{label} {int(raw)}"
    except (TypeError, ValueError):
        return None


def _failed_attempt_view(failed: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(failed, dict):
        return {"title": None, "reasons": [], "metrics": [], "debug_line": None}
    report = failed.get("report") if isinstance(failed.get("report"), dict) else {}
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    metric_lines = [
        line
        for line in (
            _metric_line(metrics, "concept_count", label="концепты"),
            _metric_line(metrics, "semantic_relation_count", label="связи"),
            _metric_line(metrics, "docs_participating_pct", label="документы", as_pct=True),
            _metric_line(metrics, "relations_with_evidence_pct", label="evidence", as_pct=True),
        )
        if line
    ]
    from app.course_quality_passport import rewrite_fail_reasons_for_learners

    raw_reasons = [str(r).strip() for r in (report.get("fail_reasons") or []) if str(r).strip()]
    reasons = rewrite_fail_reasons_for_learners(report) or raw_reasons
    label = str(failed.get("label") or "").strip()
    return {
        "title": "Почему последняя попытка обновить карту не прошла проверку",
        "reasons": reasons,
        "metrics": metric_lines,
        "debug_line": f"last_attempt={label}" if label else None,
    }


def build_learner_publish_status_view(status: dict[str, Any] | None) -> dict[str, Any]:
    """Learner-facing copy for graph publish UI (material plan C2).

    Primary surface avoids engineer jargon (bundle / staging / promote / generation).
    Technical ids live only under ``debug_lines`` for an optional collapsed expander.
    Compact MC badge fields: ``badge_label`` / ``badge_title`` (empty when active).
    """
    if not isinstance(status, dict):
        return {
            "tone": "info",
            "primary": "Статус карты временно недоступен.",
            "captions": [],
            "debug_lines": [],
            "failed_title": None,
            "failed_reasons": [],
            "failed_metrics": [],
            "badge_label": None,
            "badge_title": None,
        }

    reader_source = str(status.get("reader_source") or "legacy")
    active = status.get("active") if isinstance(status.get("active"), dict) else {}
    previous = status.get("previous") if isinstance(status.get("previous"), dict) else {}
    reader_gid = str(status.get("reader_generation_id") or "").strip()
    active_gid = str(active.get("generation_id") or "").strip()
    previous_gid = str(previous.get("generation_id") or "").strip()

    if reader_source == "active":
        tone = "success"
        primary = "Карта актуальна"
        captions: list[str] = []
        badge_label: str | None = None
    elif reader_source == "previous":
        tone = "warning"
        primary = "Показана предыдущая версия карты — новая ещё не готова"
        captions = [
            "Ответы и план могут опираться на прошлую карту, пока новая не пройдёт проверку качества."
        ]
        badge_label = "⚠ предыдущая карта"
    else:
        tone = "warning"
        primary = "Карта знаний пока не собрана для текущих материалов"
        captions = [
            "После индексации с картой знаний здесь появится опубликованная версия."
        ]
        badge_label = "⚠ карта не собрана"

    debug_lines: list[str] = []
    if reader_gid:
        debug_lines.append(f"read={reader_source} id={reader_gid}")
    if active_gid:
        state = "ok" if active.get("exists") else "missing"
        debug_lines.append(f"active id={active_gid} ({state})")
    if previous_gid and reader_source != "active":
        state = "ok" if previous.get("exists") else "missing"
        debug_lines.append(f"previous id={previous_gid} ({state})")
    active_report = active.get("report") if isinstance(active.get("report"), dict) else None
    if active_report is not None:
        gate = "pass" if active_report.get("gate_passed") else "fail"
        pub = "yes" if active_report.get("published") else "no"
        debug_lines.append(f"quality gate={gate} published={pub}")

    failed = _failed_attempt_view(status.get("latest_failed_staging"))
    if failed["debug_line"]:
        debug_lines.append(failed["debug_line"])

    return {
        "tone": tone,
        "primary": primary,
        "captions": captions,
        "debug_lines": debug_lines,
        "failed_title": failed["title"],
        "failed_reasons": failed["reasons"],
        "failed_metrics": failed["metrics"],
        "badge_label": badge_label,
        "badge_title": primary if badge_label else None,
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
