"""Course quality passport — aggregate already-computed readiness signals.

Wave ``wave-material-passport`` (evolutionary analysis #3, P1 B1/B2):
one pure view over graph publish/freshness, konspekt coverage, media sidecars,
source readiness, and audit duplicates. No LLM, no recompute of retrieval.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.course_cache import normalize_source_paths
from app.course_folder_filter import is_user_source_path
from app.knowledge_graph_audit import GRAPH_AUDIT_JSON_NAME

_MIN_DOCUMENTS_REQUIRED = 3


def format_min_documents_ladder(
    report: dict[str, Any] | None,
    *,
    required: int = _MIN_DOCUMENTS_REQUIRED,
) -> str | None:
    """B2: positive ladder when the only blocker is ``min_documents``.

    Returns a learner-facing string, or ``None`` if this special case does not apply.
    """
    if not isinstance(report, dict):
        return None
    fail_reasons = [str(r).strip() for r in (report.get("fail_reasons") or []) if str(r).strip()]
    if not fail_reasons:
        return None
    min_doc_hits = [r for r in fail_reasons if "min_documents" in r.lower() or "недостаточно документов" in r.lower()]
    if not min_doc_hits:
        return None
    # Only reframe when min_documents is the sole semantic blocker (ignore heuristic-fallback noise).
    substantive = [
        r
        for r in fail_reasons
        if "heuristic" not in r.lower() and "metadata-only" not in r.lower()
    ]
    if substantive and not all(
        "min_documents" in r.lower() or "недостаточно документов" in r.lower() for r in substantive
    ):
        return None

    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    try:
        actual = int(metrics.get("doc_count") or metrics.get("document_count") or 0)
    except (TypeError, ValueError):
        actual = 0
    if actual <= 0:
        # Latent fallback: gate list may be missing/malformed on old sidecars.
        raw_gates = report.get("gates")
        gates = raw_gates if isinstance(raw_gates, list) else []
        for gate in gates:
            if not isinstance(gate, dict):
                continue
            if str(gate.get("name") or "") != "min_documents":
                continue
            try:
                actual = int(float(str(gate.get("actual") or "0")))
            except (TypeError, ValueError):
                actual = 0
            break
    need = max(0, int(required) - max(0, actual))
    if need <= 0:
        # Still show the ladder with unknown actual when fail text matches.
        return (
            f"Добавьте документы курса до {required} — появится семантическая карта."
        )
    docs_word = "документ" if need == 1 else ("документа" if need < 5 else "документов")
    return (
        f"Добавьте ещё {need} {docs_word} курса — появится семантическая карта "
        f"(сейчас {actual} из {required})."
    )


def rewrite_fail_reasons_for_learners(report: dict[str, Any] | None) -> list[str]:
    """Return fail_reasons with min_documents reframed as a ladder when applicable."""
    if not isinstance(report, dict):
        return []
    reasons = [str(r).strip() for r in (report.get("fail_reasons") or []) if str(r).strip()]
    ladder = format_min_documents_ladder(report)
    if not ladder:
        return reasons
    out: list[str] = []
    replaced = False
    for r in reasons:
        if "min_documents" in r.lower() or "недостаточно документов" in r.lower():
            if not replaced:
                out.append(ladder)
                replaced = True
            continue
        out.append(r)
    if not replaced:
        out.insert(0, ladder)
    return out


def _graph_section(
    *,
    publish_status: dict[str, Any] | None,
    index_stats: dict[str, Any] | None,
    source_paths: list[str],
) -> dict[str, Any]:
    from app.graph_publish_status import graph_freshness_gap

    status = publish_status if isinstance(publish_status, dict) else {}
    active = status.get("active") if isinstance(status.get("active"), dict) else {}
    report = active.get("report") if isinstance(active.get("report"), dict) else {}
    published = bool(active.get("exists")) and bool(report.get("published") or report.get("gate_passed"))
    gap = 0
    try:
        gap = int(graph_freshness_gap(index_stats, status) or 0)
    except Exception:  # noqa: BLE001 - passport must never break prepare UI
        gap = 0

    failed = status.get("latest_failed_staging")
    failed_report = None
    if isinstance(failed, dict) and isinstance(failed.get("report"), dict):
        failed_report = failed["report"]
    ladder = format_min_documents_ladder(failed_report or report)

    if published and gap <= 0:
        line = "🗺 Карта: опубликована, свежая"
    elif published and gap > 0:
        line = f"🗺 Карта: опубликована, отстаёт на {gap} материал(ов)"
    elif ladder:
        line = f"🗺 Карта: {ladder}"
    else:
        line = "🗺 Карта: не опубликована"

    return {
        "published": published,
        "freshness_gap": gap,
        "ladder": ladder,
        "line": line,
        "reader_source": str(status.get("reader_source") or ""),
        "generation_id": str(active.get("generation_id") or status.get("reader_generation_id") or ""),
        "source_paths_count": len(source_paths),
    }


def _konspekt_section(source_paths: list[str]) -> dict[str, Any]:
    from app.konspekt_discovery import coverage_summary

    summary = coverage_summary(source_paths)
    covered, total = int(summary.covered), int(summary.total)
    if total <= 0:
        line = "📝 Конспекты: нет документов в scope"
    else:
        line = f"📝 Конспекты: {covered}/{total}"
        if covered == total:
            line += " · все на месте"
    return {"covered": covered, "total": total, "pct": float(summary.pct), "line": line}


def _konspekt_has_media_sidecar(konspekt_path: Path, *, data_dir: Path | None) -> bool:
    """True when frontmatter ``media_sidecar:`` points at a loadable sidecar.

    Uses the canonical discovery path (pointer → load), not filename heuristics.
    Orphan ``*.media.json`` without a pointer does not count; a renamed target
    named only in the pointer does count.
    """
    from app.media_sidecar import load_media_sidecar_for_konspekt

    try:
        return load_media_sidecar_for_konspekt(konspekt_path, data_dir=data_dir) is not None
    except Exception:  # noqa: BLE001 - broken pointer/schema = no usable media on passport
        return False


def _media_section(source_paths: list[str], *, data_dir: Path | None = None) -> dict[str, Any]:
    """Count sources whose matched konspekt declares a loadable media sidecar."""
    from app.konspekt_discovery import find_konspekt_for_source_in_data

    with_media = 0
    for rel in source_paths:
        km = find_konspekt_for_source_in_data(rel)
        if km is None:
            continue
        if _konspekt_has_media_sidecar(km.path, data_dir=data_dir):
            with_media += 1
    total = len(source_paths)
    if total <= 0:
        line = "🎬 Медиа: нет документов в scope"
    else:
        pct = round(100.0 * with_media / total)
        line = f"🎬 Медиа: {with_media}/{total} ({pct}%) с sidecar"
    return {"with_media": with_media, "total": total, "line": line}


def _readiness_section(data_dir: Path | None) -> dict[str, Any]:
    if data_dir is None:
        return {
            "readiness_score": None,
            "problematic": None,
            "line": "📂 Готовность корпуса: недоступна",
        }
    try:
        from app.config import get_settings
        from app.source_readiness import build_source_readiness_summary

        summary = build_source_readiness_summary(data_dir, get_settings())
    except Exception:  # noqa: BLE001 - readiness is optional on passport surface
        return {
            "readiness_score": None,
            "problematic": None,
            "line": "📂 Готовность корпуса: временно недоступна",
        }
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    score = summary.get("readiness_score")
    problematic = int(counts.get("problematic") or 0)
    score_txt = f"{float(score):.0%}" if isinstance(score, (int, float)) else "—"
    if problematic > 0:
        line = f"📂 Готовность корпуса: {score_txt} · проблемных файлов {problematic}"
    else:
        line = f"📂 Готовность корпуса: {score_txt}"
    return {
        "readiness_score": score,
        "problematic": problematic,
        "counts": counts,
        "primary_next_action": str(summary.get("primary_next_action") or ""),
        "line": line,
    }


def _audit_section(publish_status: dict[str, Any] | None) -> dict[str, Any]:
    status = publish_status if isinstance(publish_status, dict) else {}
    active = status.get("active") if isinstance(status.get("active"), dict) else {}
    bundle_dir = str(active.get("bundle_dir") or "").strip()
    if not bundle_dir:
        return {"duplicate_count": None, "line": "🔬 Аудит дубликатов: нет active bundle"}
    path = Path(bundle_dir) / GRAPH_AUDIT_JSON_NAME
    if not path.is_file():
        return {"duplicate_count": None, "line": "🔬 Аудит дубликатов: ещё не запускался"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"duplicate_count": None, "line": "🔬 Аудит дубликатов: файл не читается"}
    findings = payload.get("findings") if isinstance(payload, dict) else None
    dup_count = 0
    if isinstance(findings, list):
        for item in findings:
            if not isinstance(item, dict):
                continue
            if str(item.get("kind") or "") == "duplicate_candidates":
                items = item.get("items") or []
                dup_count = len(items) if isinstance(items, list) else 0
                break
    if dup_count <= 0:
        counters = payload.get("counters") if isinstance(payload.get("counters"), dict) else {}
        dup_count = int(counters.get("duplicate_candidates") or payload.get("duplicate_count") or 0)
    if dup_count > 0:
        line = f"🔬 Аудит: кандидатов-дубликатов {dup_count}"
    else:
        line = "🔬 Аудит: явных дубликатов не найдено"
    return {"duplicate_count": dup_count, "line": line}


def build_course_quality_passport(
    source_paths: list[str] | None,
    *,
    publish_status: dict[str, Any] | None = None,
    index_stats: dict[str, Any] | None = None,
    data_dir: Path | str | None = None,
    fetch_live: bool = True,
) -> dict[str, Any]:
    """Aggregate readiness signals for the active course scope.

    When ``fetch_live`` is True and ``publish_status``/``data_dir`` are omitted,
    the function loads them via existing helpers (UI convenience path).
    Tests should pass explicit inputs with ``fetch_live=False``.
    """
    paths = [
        p
        for p in normalize_source_paths(source_paths or [])
        if is_user_source_path(p)
    ]

    status = publish_status
    if status is None and fetch_live:
        try:
            from app.graph_publish_status import get_graph_publish_status

            status = get_graph_publish_status()
        except Exception:  # noqa: BLE001 - passport degrades without graph status
            status = {}

    root: Path | None
    if data_dir is not None:
        root = Path(data_dir)
    elif fetch_live:
        try:
            from app.config import get_settings

            root = Path(get_settings().data_dir)
        except Exception:  # noqa: BLE001 - optional corpus root
            root = None
    else:
        root = None

    graph = _graph_section(publish_status=status, index_stats=index_stats, source_paths=paths)
    konspekts = _konspekt_section(paths)
    media = _media_section(paths, data_dir=root)
    readiness = _readiness_section(root)
    audit = _audit_section(status)
    lines = [
        graph["line"],
        konspekts["line"],
        media["line"],
        readiness["line"],
        audit["line"],
    ]
    return {
        "source_paths": paths,
        "graph": graph,
        "konspekts": konspekts,
        "media": media,
        "source_readiness": readiness,
        "audit": audit,
        "lines": lines,
    }
