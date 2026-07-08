"""JSON cache for Course Workspace preparation artifacts."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from app.config import DATA_DIR, get_settings
from app.pace_engine import DEFAULT_PACE_MODE, normalize_pace_mode

COURSE_PREPARE_PROMPT_VERSION = "course_prepare_v1"
_NEXT_SESSION_PROMISES_KEY = "next_session_promises"
_PROMISE_TTL_HOURS = 36

# Документы курсов (эвристика кандидатов): см. ingestion / index_diff
_COURSE_INGEST_EXTENSIONS = frozenset({".pdf", ".txt", ".md", ".docx", ".html"})
_TECHNICAL_COURSE_FOLDER_PREFIXES = frozenset(("_", "test-", "tmp", "temp"))
_TECHNICAL_COURSE_FOLDER_NAMES = frozenset({
    ".cache",
    ".chroma",
    ".git",
    "__pycache__",
    "cache",
    "chroma_db",
    "graph_generations",
    "logs",
    "tmp",
})

GraphCourseStatus = Literal["ready", "pending", "unavailable"]

_GRAPH_BADGE_RU: dict[GraphCourseStatus, tuple[str, str, str]] = {
    "ready": (
        "Граф знаний: готов",
        "Концепты и prerequisites доступны для плана курса",
        "graph-status-badge-ready",
    ),
    "pending": (
        "Граф знаний: готовится",
        "Индексация завершена; обогащение графа ещё идёт или не запускалось",
        "graph-status-badge-pending",
    ),
    "unavailable": (
        "Граф знаний: недоступен",
        "Курс работает в режиме indexed-only; проверьте GRAPH_MODEL и ключ API",
        "graph-status-badge-unavailable",
    ),
}


@dataclass(frozen=True)
class GraphStatusView:
    status: GraphCourseStatus
    indexed: bool
    prerequisite_labels: list[str]
    caption_ru: str
    detail_ru: str
    testid: str
    has_prerequisite_cycles: bool = False


def _normalize_folder_rel(folder_rel: str) -> str:
    return str(folder_rel or "").strip().replace("\\", "/")


def detect_stale_graph_binding(
    *,
    artifact_generation_id: str | None,
    active_generation_id: str | None,
    artifact_scope_hash: str | None,
    current_scope_hash: str | None,
) -> bool:
    """True when cached artifact binding no longer matches active registry generation/scope."""
    ag = str(artifact_generation_id or "").strip()
    active = str(active_generation_id or "").strip()
    if ag and active and ag != active:
        return True
    ash = str(artifact_scope_hash or "").strip()
    csh = str(current_scope_hash or "").strip()
    if ash and csh and ash != csh:
        return True
    return False


def graph_quality_summary_from_refresh(graph_refresh: dict | None) -> dict[str, Any] | None:
    if not isinstance(graph_refresh, dict):
        return None
    report = graph_refresh.get("quality_report")
    return report if isinstance(report, dict) else None


def _compute_confidence_p50(typed_relations: list[Any]) -> float | None:
    """Median confidence across typed relations; None when no numeric values."""
    confidences: list[float] = []
    for rel in typed_relations or []:
        if not isinstance(rel, dict):
            continue
        raw = rel.get("confidence")
        if raw is None:
            continue
        try:
            confidences.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not confidences:
        return None
    confidences.sort()
    mid = len(confidences) // 2
    if len(confidences) % 2:
        return confidences[mid]
    return (confidences[mid - 1] + confidences[mid]) / 2.0


def _scope_label_from_source_paths(source_paths: list[str], *, scope_hash: str = "") -> str:
    """Human-readable course folder label from StudyScope source paths."""
    normalized = normalize_source_paths(source_paths)
    if not normalized:
        return scope_hash[:12] if scope_hash else ""
    parts_list = [[seg for seg in p.replace("\\", "/").split("/") if seg] for p in normalized]
    if not parts_list:
        return scope_hash[:12] if scope_hash else ""
    if len(parts_list) == 1:
        segs = parts_list[0]
        if len(segs) > 1:
            return "/".join(segs[:-1])
        return segs[0] if segs else (scope_hash[:12] if scope_hash else "")
    common: list[str] = []
    for group in zip(*parts_list, strict=False):
        if len(set(group)) == 1:
            common.append(group[0])
        else:
            break
    if common:
        return "/".join(common)
    first = normalized[0].replace("\\", "/")
    if "/" in first:
        return first.rsplit("/", 1)[0]
    return scope_hash[:12] if scope_hash else first.split("/")[0]


def _load_bundle_typed_relations(bundle_dir: Path) -> list[Any]:
    from app.knowledge_graph_bundle import load_graph_snapshot_payload

    raw = load_graph_snapshot_payload(bundle_dir)
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    relations = payload.get("typed_relations")
    return relations if isinstance(relations, list) else []


def resolve_compiler_health_for_kg(
    *,
    source_paths: list[str] | tuple[str, ...],
    active_generation_id: str | None = None,
) -> dict[str, Any] | None:
    """Read-only compiler health blob for D3 Knowledge Graph diagnostics."""
    paths = normalize_source_paths(source_paths)
    current_scope_hash = course_scope_hash(paths) if paths else ""

    active_gen = str(active_generation_id or "").strip()
    if not active_gen:
        try:
            from app.index_registry import get_active_generation_view

            active_gen = str(get_active_generation_view().generation_id or "").strip()
        except (ImportError, OSError, ValueError, AttributeError):
            active_gen = ""

    artifact = load_course_artifact(paths) if paths else None
    artifact_gen = str((artifact or {}).get("generation_id") or "").strip()
    generation_id = active_gen or artifact_gen
    if not generation_id:
        return None

    from app.graph_generation_paths import generation_bundle_dir
    from app.knowledge_graph_bundle import load_graph_quality_report

    bundle_dir = generation_bundle_dir(generation_id)
    report = load_graph_quality_report(bundle_dir)
    if report is None:
        return None

    scope_hash = str(
        report.get("scope_hash") or (artifact or {}).get("scope_hash") or current_scope_hash or ""
    )
    generation_id = str(report.get("generation_id") or generation_id)
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    semantic_relation_count = int(metrics.get("semantic_relation_count") or 0)
    concept_count = int(metrics.get("concept_count") or 0)
    fail_reasons_raw = report.get("fail_reasons") or []
    fail_reasons = [str(reason) for reason in fail_reasons_raw[:3] if str(reason).strip()]

    typed_relations = _load_bundle_typed_relations(bundle_dir)
    confidence_p50 = _compute_confidence_p50(typed_relations)

    artifact_gen_for_stale = str((artifact or {}).get("generation_id") or report.get("generation_id") or "")
    stale_binding = detect_stale_graph_binding(
        artifact_generation_id=artifact_gen_for_stale,
        active_generation_id=active_gen,
        artifact_scope_hash=str((artifact or {}).get("scope_hash") or scope_hash),
        current_scope_hash=current_scope_hash,
    )

    scope_label = _scope_label_from_source_paths(paths, scope_hash=scope_hash)
    if not scope_label and scope_hash:
        scope_label = scope_hash[:12]

    return {
        "generation_id": generation_id,
        "scope_hash": scope_hash,
        "gate_passed": bool(report.get("gate_passed")),
        "confidence_p50": confidence_p50,
        "semantic_relation_count": semantic_relation_count,
        "stale_binding": stale_binding,
        "scope_label": scope_label,
        "concept_count": concept_count,
        "fail_reasons": fail_reasons,
    }


def update_course_graph_binding(
    source_paths: list[str] | tuple[str, ...],
    *,
    generation_id: str,
    scope_hash: str,
    graph_quality_summary: dict[str, Any],
    source_content_hashes: list[str] | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any] | None:
    """Attach generation/scope binding fields to an existing or minimal course artifact."""
    normalized = normalize_source_paths(source_paths)
    if not normalized:
        return None
    path = cache_path or default_course_cache_path()
    existing = load_course_artifact(normalized, cache_path=path) or {}
    merged = {
        **existing,
        "generation_id": generation_id,
        "scope_hash": scope_hash,
        "graph_quality_summary": graph_quality_summary,
        "source_content_hashes": list(source_content_hashes or []),
    }
    return save_course_artifact(
        normalized,
        merged,
        cache_path=path,
    )


def evaluate_graph_quality_gate(metrics: dict[str, Any]):
    """Re-export compiler gate for resolver/UI contract."""
    from app.course_graph_compiler import evaluate_graph_quality_gate as _eval

    return _eval(metrics)


def resolve_active_generation_uplift_prerequisites(
    generation_id: str | None = None,
) -> dict[str, Any]:
    """Read-only compiler/uplift prerequisites for active generation binding."""
    active_gen = str(generation_id or "").strip()
    if not active_gen:
        try:
            from app.index_registry import get_active_generation_view

            active_gen = str(get_active_generation_view().generation_id or "").strip()
        except (ImportError, OSError, ValueError, AttributeError):
            active_gen = ""

    if not active_gen:
        return {
            "generation_id": None,
            "gate_passed": False,
            "stale_binding": True,
            "stale_binding_reason": "missing_generation_id",
            "uplift_prerequisites_met": False,
        }

    from app.graph_generation_paths import generation_bundle_dir
    from app.knowledge_graph_bundle import load_graph_quality_report

    bundle_dir = generation_bundle_dir(active_gen)
    report = load_graph_quality_report(bundle_dir) or {}
    report_gen = str(report.get("generation_id") or active_gen).strip()
    stale = bool(report_gen and active_gen and report_gen != active_gen)
    gate_passed = bool(report.get("gate_passed"))
    stale_reason = "generation_id_mismatch" if stale else None

    return {
        "generation_id": active_gen,
        "report_generation_id": report_gen,
        "gate_passed": gate_passed,
        "stale_binding": stale,
        "stale_binding_reason": stale_reason,
        "uplift_prerequisites_met": gate_passed and not stale,
    }


def _filename_fallback_node_count(concepts: dict[str, Any]) -> int:
    count = 0
    for node in (concepts or {}).values():
        if not isinstance(node, dict):
            continue
        prov = node.get("provenance") or {}
        if prov.get("extraction_method") == "heuristic":
            count += 1
    return count


def graph_llm_probe_ok(*, settings=None) -> bool:
    """True when local graph LLM is configured (no ingestion cloud)."""
    from app.provider import get_graph_llm

    try:
        get_graph_llm()
        return True
    except (ValueError, TypeError, OSError):
        return False


def scope_paths_indexed(
    source_paths: list[str] | tuple[str, ...],
    index_stats: dict | None,
) -> bool:
    """True when every scope path appears in the active index manifest."""
    normalized = normalize_source_paths(source_paths)
    if not normalized:
        return False
    if not isinstance(index_stats, dict):
        return False
    indexed_files = {
        str(path).strip().replace("\\", "/")
        for path in index_stats.get("files") or []
        if str(path).strip()
    }
    if not indexed_files:
        return False
    return all(path.replace("\\", "/") in indexed_files for path in normalized)


def _prerequisite_labels_from_bundle(bundle: dict[str, Any], *, limit: int = 8) -> list[str]:
    preview = bundle.get("topological_preview") if isinstance(bundle, dict) else None
    if not isinstance(preview, list):
        return []
    labels: list[str] = []
    for item in preview[: max(0, limit)]:
        text = str(item or "").strip()
        if text:
            labels.append(text)
    return labels


def _graph_status_view(
    status: GraphCourseStatus,
    *,
    indexed: bool,
    prerequisite_labels: list[str] | None = None,
    detail_ru: str | None = None,
    has_prerequisite_cycles: bool = False,
) -> GraphStatusView:
    caption_ru, default_detail, testid = _GRAPH_BADGE_RU[status]
    labels = list(prerequisite_labels or [])
    resolved_detail = detail_ru or default_detail
    if status == "ready" and not labels:
        resolved_detail = "Список prerequisites пока пуст"
    if status == "ready" and has_prerequisite_cycles:
        caption_ru = f"{caption_ru} (есть циклы prerequisites)"
    return GraphStatusView(
        status=status,
        indexed=indexed,
        prerequisite_labels=labels,
        caption_ru=caption_ru,
        detail_ru=resolved_detail,
        testid=testid,
        has_prerequisite_cycles=has_prerequisite_cycles,
    )


def resolve_graph_status(
    *,
    source_paths: list[str] | tuple[str, ...],
    index_stats: dict | None = None,
    graph_refresh: dict | None = None,
    artifact_binding: dict[str, Any] | None = None,
    active_generation_id: str | None = None,
    settings=None,
    graph_probe: Callable[[], bool] | None = None,
    health_fn: Callable[[], dict[str, Any]] | None = None,
    bundle_fn: Callable[..., dict[str, Any]] | None = None,
) -> GraphStatusView:
    """Deterministic graph/indexed status for course prepare (no Streamlit, no HTTP)."""
    paths = normalize_source_paths(source_paths)
    current_scope_hash = course_scope_hash(paths) if paths else ""
    if not paths:
        return _graph_status_view(
            "unavailable",
            indexed=False,
            detail_ru="Нет документов в активном курсе",
        )

    if not scope_paths_indexed(paths, index_stats):
        return _graph_status_view(
            "pending",
            indexed=False,
            detail_ru="Сначала проиндексируйте документы курса",
        )

    probe_fn = graph_probe or graph_llm_probe_ok
    try:
        probe_ok = bool(probe_fn(settings=settings))
    except TypeError:
        probe_ok = bool(probe_fn())
    if not probe_ok:
        return _graph_status_view("unavailable", indexed=True)

    binding = artifact_binding if isinstance(artifact_binding, dict) else {}
    refresh = graph_refresh if isinstance(graph_refresh, dict) else None
    refresh_gen = str((refresh or {}).get("generation_id") or "").strip()
    active_gen = str(active_generation_id or refresh_gen or "").strip()
    if detect_stale_graph_binding(
        artifact_generation_id=str(binding.get("generation_id") or ""),
        active_generation_id=active_gen,
        artifact_scope_hash=str(binding.get("scope_hash") or ""),
        current_scope_hash=current_scope_hash,
    ):
        return _graph_status_view(
            "pending",
            indexed=True,
            detail_ru="Привязка графа устарела — требуется повторная индексация с graph LLM",
        )

    refresh_ok: bool | None = None
    gate_passed: bool | None = None
    gate_enforced = False
    if refresh is not None and "ok" in refresh:
        refresh_ok = bool(refresh.get("ok"))
    if refresh is not None and "gate_passed" in refresh:
        gate_passed = bool(refresh.get("gate_passed"))
        gate_enforced = True
    elif isinstance(binding.get("graph_quality_summary"), dict):
        gate_passed = bool(binding["graph_quality_summary"].get("gate_passed"))
        gate_enforced = True

    if refresh_ok is False:
        return _graph_status_view("pending", indexed=True)

    quality = graph_quality_summary_from_refresh(refresh) or binding.get("graph_quality_summary")
    fail_reasons: list[str] = []
    if isinstance(quality, dict):
        fail_reasons = [str(r) for r in (quality.get("fail_reasons") or []) if str(r).strip()]

    if gate_enforced and gate_passed is False:
        detail = fail_reasons[0] if fail_reasons else "Граф не прошёл проверку качества"
        return _graph_status_view("pending", indexed=True, detail_ru=detail)

    from app.knowledge_graph import (
        get_graph_prerequisites_health,
        get_learning_plan_graph_bundle,
    )

    health_loader = health_fn or get_graph_prerequisites_health
    bundle_loader = bundle_fn or (
        lambda: get_learning_plan_graph_bundle(topo_preview_limit=8)
    )
    health = health_loader() if callable(health_loader) else {}
    concept_count = int((health or {}).get("concept_count") or 0)
    relation_count = int((health or {}).get("relation_count") or 0)
    has_cycles = bool((health or {}).get("has_prerequisite_cycles"))

    if concept_count == 0 or relation_count == 0:
        return _graph_status_view("pending", indexed=True)

    if refresh_ok is not True and not (gate_enforced and gate_passed is True):
        return _graph_status_view("pending", indexed=True)

    if gate_enforced and gate_passed is not True:
        return _graph_status_view(
            "pending",
            indexed=True,
            detail_ru=fail_reasons[0] if fail_reasons else "Семантический граф ещё не опубликован",
        )

    bundle = bundle_loader() if callable(bundle_loader) else {}
    labels = _prerequisite_labels_from_bundle(bundle if isinstance(bundle, dict) else {})
    return _graph_status_view(
        "ready",
        indexed=True,
        prerequisite_labels=labels,
        has_prerequisite_cycles=has_cycles,
    )


def build_mission_control_course_options(index_stats: dict | None) -> list[dict[str, Any]]:
    """Index folders first, then heuristic ``list_course_candidates`` not yet indexed."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scope in _course_options_from_index_stats(index_stats):
        rel = _normalize_folder_rel(scope.get("folder_rel") or "")
        if not rel or rel in seen:
            continue
        seen.add(rel)
        merged.append({**scope, "needs_reindex": False})
    for cand in list_course_candidates():
        rel = _normalize_folder_rel(cand.get("folder_rel") or "")
        if not rel or rel in seen:
            continue
        seen.add(rel)
        merged.append(
            {
                **study_scope_from_course_option(
                    {
                        "folder_rel": rel,
                        "title": f"Курс: {rel}",
                        "source_paths": [],
                    }
                ),
                "needs_reindex": True,
                "supported_file_count": int(cand.get("supported_file_count") or 0),
            }
        )
    return merged


def is_user_course_folder_rel(folder_rel: str) -> bool:
    """Return False for service/test folders that must not be shown as courses."""
    normalized = str(folder_rel or "").strip().replace("\\", "/").strip("/")
    if not normalized:
        return False
    first = normalized.split("/", 1)[0].strip().lower()
    if not first:
        return False
    if first in _TECHNICAL_COURSE_FOLDER_NAMES:
        return False
    return not any(first.startswith(prefix) for prefix in _TECHNICAL_COURSE_FOLDER_PREFIXES)


def list_course_candidates(
    *,
    docs_root: Path | None = None,
    min_supported_files: int = 3,
) -> list[dict[str, Any]]:
    """Папки-кандидаты под ``data/docs`` с минимумом поддерживаемых файлов Course Delight heuristic."""
    root = docs_root if docs_root is not None else (DATA_DIR / "docs")
    if not root.is_dir():
        return []
    candidates: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not is_user_course_folder_rel(child.name):
            continue
        n = sum(
            1
            for path in child.rglob("*")
            if path.is_file() and path.suffix.lower() in _COURSE_INGEST_EXTENSIONS
        )
        if n >= max(1, min_supported_files):
            try:
                rel = str(child.relative_to(root))
            except ValueError:
                rel = child.name
            candidates.append({"folder_rel": rel, "supported_file_count": n})
    return candidates


def _balance_data_mode_tag(settings=None) -> str:
    s = settings or get_settings()
    return str(getattr(s, "home_rag_data_mode", "real") or "real").strip().lower()


# Persisted learner choice: how many due steps they plan today (recovery budget slider).
_RECOVERY_CATCH_UP_KEY = "recovery_catch_up_by_scope"


def normalize_source_paths(source_paths: list[str] | tuple[str, ...]) -> list[str]:
    """Return stable, non-empty source paths for cache keys and payloads."""
    return sorted({str(path).strip() for path in source_paths if str(path).strip()})


def course_scope_hash(source_paths: list[str] | tuple[str, ...]) -> str:
    """Stable scope hash based only on the course document set."""
    normalized = normalize_source_paths(source_paths)
    return hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()[:12]


def course_artifact_key(
    source_paths: list[str] | tuple[str, ...],
    *,
    model_id: str | None = None,
    prompt_version: str = COURSE_PREPARE_PROMPT_VERSION,
) -> str:
    """Stable cache key for course preparation output."""
    normalized = normalize_source_paths(source_paths)
    s = get_settings()
    model = model_id or s.llm_model
    raw = json.dumps(
        {
            "source_paths": normalized,
            "model_id": model,
            "prompt_version": prompt_version,
            "data_mode_partition": _balance_data_mode_tag(s),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def default_course_cache_path() -> Path:
    """Course cache next to the configured user-state database."""
    user_state_db = Path(get_settings().user_state_db)
    return user_state_db.parent / "cache" / "course_artifacts.json"


def _read_cache_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _promise_scope_ids(scope: dict[str, Any]) -> tuple[str, str, str]:
    """scope_id (StudyScope), documents hash, folder_rel for labels."""
    sid = str(scope.get("id") or "").strip()
    paths = scope.get("source_paths") if isinstance(scope.get("source_paths"), list) else []
    doc_hash = course_scope_hash(paths) if paths else ""
    folder = str(scope.get("folder_rel") or "").strip()
    return sid, doc_hash, folder


def _promise_time_ok(blob: dict[str, Any] | None) -> bool:
    if not isinstance(blob, dict):
        return False
    vu = blob.get("valid_until")
    if not vu:
        return False
    try:
        until = datetime.fromisoformat(str(vu).replace("Z", "+00:00"))
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return datetime.now(timezone.utc) <= until


def _promise_documents_match(blob: dict[str, Any] | None, current_doc_hash: str) -> bool:
    if not isinstance(blob, dict):
        return False
    if not current_doc_hash:
        return True
    stored = str(blob.get("documents_scope_hash") or "")
    if not stored:
        return True
    return stored == current_doc_hash


def save_next_session_promise(
    scope: dict[str, Any],
    *,
    promise_text: str,
    runway_goal_line: str = "",
    micro_target: int = 0,
    due_today: int = 0,
    active_slot: str = "",
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """Сохраняет обещание на следующий визит (Course Workspace) в JSON-кэш рядом с user-state."""
    sid, doc_hash, folder = _promise_scope_ids(scope)
    if not sid:
        return {}
    path = cache_path or default_course_cache_path()
    data = _read_cache_file(path)
    root = data.setdefault(_NEXT_SESSION_PROMISES_KEY, {})
    if not isinstance(root, dict):
        root = {}
        data[_NEXT_SESSION_PROMISES_KEY] = root
    now = datetime.now(timezone.utc)
    valid_until = (now + timedelta(hours=_PROMISE_TTL_HOURS)).isoformat()
    blob: dict[str, Any] = {
        "scope_id": sid,
        "documents_scope_hash": doc_hash,
        "folder_rel": folder,
        "promise_text": str(promise_text or "").strip(),
        "runway_goal_line": str(runway_goal_line or "").strip(),
        "micro_target": int(micro_target),
        "due_today": int(due_today),
        "active_slot": str(active_slot or "").strip(),
        "saved_at": now.isoformat(),
        "valid_until": valid_until,
    }
    by_scope = root.setdefault("by_scope_id", {})
    if not isinstance(by_scope, dict):
        by_scope = {}
        root["by_scope_id"] = by_scope
    by_scope[sid] = blob
    root["last_closed"] = dict(blob)
    _write_cache_file(path, data)
    return blob


def save_recovery_catch_up_for_scope(
    scope: dict[str, Any],
    *,
    catch_up_steps: int,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """Persist daily recovery budget (slider) per StudyScope beside user-state."""
    sid, _doc_hash, _folder = _promise_scope_ids(scope)
    if not sid:
        return {}
    path = cache_path or default_course_cache_path()
    data = _read_cache_file(path)
    root = data.setdefault(_RECOVERY_CATCH_UP_KEY, {})
    if not isinstance(root, dict):
        root = {}
        data[_RECOVERY_CATCH_UP_KEY] = root
    by_scope = root.setdefault("by_scope_id", {})
    if not isinstance(by_scope, dict):
        by_scope = {}
        root["by_scope_id"] = by_scope
    by_scope[sid] = max(1, int(catch_up_steps))
    root["saved_at_latest"] = datetime.now(timezone.utc).isoformat()
    _write_cache_file(path, data)
    return {"scope_id": sid, "catch_up_steps": by_scope[sid]}


def load_recovery_catch_up_for_scope(
    scope: dict[str, Any],
    *,
    cache_path: Path | None = None,
) -> int | None:
    """Load persisted recovery budget for scope, if any."""
    sid, _, _ = _promise_scope_ids(scope)
    if not sid:
        return None
    path = cache_path or default_course_cache_path()
    data = _read_cache_file(path)
    root = data.get(_RECOVERY_CATCH_UP_KEY)
    if not isinstance(root, dict):
        return None
    by_scope = root.get("by_scope_id")
    if not isinstance(by_scope, dict):
        return None
    raw = by_scope.get(sid)
    if raw is None:
        return None
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return None


def clear_recovery_catch_up_for_scope(
    scope: dict[str, Any],
    *,
    cache_path: Path | None = None,
) -> None:
    sid, _, _ = _promise_scope_ids(scope)
    if not sid:
        return
    path = cache_path or default_course_cache_path()
    data = _read_cache_file(path)
    root = data.get(_RECOVERY_CATCH_UP_KEY)
    if not isinstance(root, dict):
        return
    by_scope = root.get("by_scope_id")
    if isinstance(by_scope, dict) and sid in by_scope:
        del by_scope[sid]
    _write_cache_file(path, data)


def load_next_session_promise_for_scope(
    scope: dict[str, Any],
    *,
    cache_path: Path | None = None,
) -> dict[str, Any] | None:
    """Активное обещание для текущего курса с проверкой TTL и смены набора документов."""
    sid, doc_hash, _folder = _promise_scope_ids(scope)
    if not sid:
        return None
    path = cache_path or default_course_cache_path()
    data = _read_cache_file(path)
    root = data.get(_NEXT_SESSION_PROMISES_KEY)
    if not isinstance(root, dict):
        return None
    by_scope = root.get("by_scope_id")
    if not isinstance(by_scope, dict):
        return None
    blob = by_scope.get(sid)
    if not isinstance(blob, dict):
        return None
    if not _promise_time_ok(blob) or not _promise_documents_match(blob, doc_hash):
        return None
    return blob


def load_last_closed_promise(*, cache_path: Path | None = None) -> dict[str, Any] | None:
    """Последнее обещание при возврате на главный экран (до активации StudyScope)."""
    path = cache_path or default_course_cache_path()
    data = _read_cache_file(path)
    root = data.get(_NEXT_SESSION_PROMISES_KEY)
    if not isinstance(root, dict):
        return None
    blob = root.get("last_closed")
    if not isinstance(blob, dict) or not _promise_time_ok(blob):
        return None
    return blob


def ensure_plan_v2_pace_mode(artifact: dict[str, Any]) -> dict[str, Any]:
    """Guarantee `learning_plan.plan.v2.pace_mode` exists and is valid."""
    learning_plan = artifact.get("learning_plan")
    if not isinstance(learning_plan, dict):
        return artifact
    plan = learning_plan.get("plan")
    if not isinstance(plan, dict):
        return artifact
    plan_v2 = plan.get("v2")
    if not isinstance(plan_v2, dict):
        plan_v2 = {}
        plan["v2"] = plan_v2
    plan_v2["pace_mode"] = normalize_pace_mode(plan_v2.get("pace_mode"), default=DEFAULT_PACE_MODE)
    return artifact


def load_course_artifact(
    source_paths: list[str] | tuple[str, ...],
    *,
    model_id: str | None = None,
    prompt_version: str = COURSE_PREPARE_PROMPT_VERSION,
    cache_path: Path | None = None,
) -> dict[str, Any] | None:
    """Load a cached course artifact for the exact document/model/prompt tuple."""
    path = cache_path or default_course_cache_path()
    key = course_artifact_key(source_paths, model_id=model_id, prompt_version=prompt_version)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return None
    artifacts = data.get("artifacts") if isinstance(data, dict) else None
    artifact = artifacts.get(key) if isinstance(artifacts, dict) else None
    if not isinstance(artifact, dict):
        return None
    return ensure_plan_v2_pace_mode(artifact)


def study_scope_from_course_option(option: Any) -> dict[str, Any]:
    """Build a StudyScope-shaped dict from a CourseOption-like object or mapping."""
    if isinstance(option, dict):
        folder_rel = str(option.get("folder_rel") or "").strip()
        title = str(option.get("title") or folder_rel).strip()
        raw_paths = option.get("source_paths") or []
    else:
        folder_rel = str(getattr(option, "folder_rel", "") or "").strip()
        title = str(getattr(option, "title", "") or folder_rel).strip()
        raw_paths = getattr(option, "source_paths", ()) or ()
    source_paths = [str(path).strip() for path in raw_paths if str(path).strip()]
    return {
        "folder_rel": folder_rel,
        "title": title,
        "source_paths": source_paths,
    }


def _course_options_from_index_stats(index_stats: dict | None) -> list[dict[str, Any]]:
    """Mirror ``mission_control._course_options_from_index_stats`` without UI imports."""
    if not isinstance(index_stats, dict):
        return []
    folders = [
        str(x).strip()
        for x in index_stats.get("folder_rel_options") or []
        if is_user_course_folder_rel(str(x).strip())
    ]
    files = [str(x).strip() for x in index_stats.get("files") or [] if str(x).strip()]
    if not folders:
        inferred = sorted({path.split("/", 1)[0].split("\\", 1)[0] for path in files if path})
        folders = [folder for folder in inferred if is_user_course_folder_rel(folder)]
    options: list[dict[str, Any]] = []
    for folder in folders:
        prefix_slash = f"{folder}/"
        prefix_backslash = f"{folder}\\"
        source_paths = tuple(
            path
            for path in files
            if path == folder or path.startswith(prefix_slash) or path.startswith(prefix_backslash)
        )
        options.append(
            study_scope_from_course_option(
                {
                    "folder_rel": folder,
                    "title": f"Курс: {folder}",
                    "source_paths": list(source_paths),
                }
            )
        )
    return options


def resolve_first_session_scope_for_home(
    *,
    index_stats: dict | None,
    active_scope: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Resolve scope for First Session cold open: active > sole candidate > first sorted > None."""
    if (
        isinstance(active_scope, dict)
        and active_scope.get("active")
        and str(active_scope.get("folder_rel") or "").strip()
    ):
        return active_scope
    options = _course_options_from_index_stats(index_stats)
    if not options:
        return None
    if len(options) == 1:
        return options[0]
    sorted_options = sorted(options, key=lambda scope: scope["folder_rel"])
    return sorted_options[0]


def first_session_artifact_is_populated(artifact: dict[str, Any] | None) -> bool:
    """True when artifact has non-empty baseline title and at least one non-empty seed question."""
    if not isinstance(artifact, dict):
        return False
    baseline = artifact.get("baseline_mission")
    if not isinstance(baseline, dict):
        return False
    if not str(baseline.get("title") or "").strip():
        return False
    seeds = artifact.get("seed_questions")
    if not isinstance(seeds, list) or not seeds:
        return False
    return any(isinstance(seed, dict) and str(seed.get("q") or "").strip() for seed in seeds)


def first_session_cache_root() -> Path:
    """Root directory for First Session Artifact JSON files (Move 1 / balance plan §11.1)."""
    return DATA_DIR / "cache" / "first_session" / _balance_data_mode_tag()


def first_session_artifact_path(course_id: str, *, cache_root: Path | None = None) -> Path:
    """Disk path for a course candidate artifact keyed by ``folder_rel``."""
    safe_id = str(course_id or "").strip().replace("\\", "/")
    if not safe_id:
        raise ValueError("course_id is required for first_session_artifact_path")
    root = cache_root or first_session_cache_root()
    return root / f"{safe_id}.json"


def _first_session_scope_match(artifact: dict[str, Any] | None, current_doc_hash: str) -> bool:
    if not isinstance(artifact, dict):
        return False
    if not current_doc_hash:
        return True
    stored = str(artifact.get("scope_hash") or "")
    if not stored:
        return False
    return stored == current_doc_hash


def save_first_session_artifact(
    course_id: str,
    payload: dict[str, Any],
    *,
    cache_root: Path | None = None,
) -> dict[str, Any]:
    """Atomically persist First Session Artifact (temp + ``os.replace``)."""
    path = first_session_artifact_path(course_id, cache_root=cache_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    try:
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
    return payload


def load_first_session_artifact_for_scope(
    scope: dict[str, Any],
    *,
    cache_root: Path | None = None,
) -> dict[str, Any] | None:
    """Load artifact for StudyScope when ``scope_hash`` matches current document set."""
    folder = str(scope.get("folder_rel") or "").strip()
    if not folder:
        return None
    path = first_session_artifact_path(folder, cache_root=cache_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    paths = scope.get("source_paths") if isinstance(scope.get("source_paths"), list) else []
    doc_hash = course_scope_hash(paths) if paths else ""
    if not _first_session_scope_match(data, doc_hash):
        return None
    return data


def invalidate_first_session_artifact(
    course_id: str,
    *,
    cache_root: Path | None = None,
) -> None:
    """Remove cached First Session Artifact for a course candidate."""
    path = first_session_artifact_path(course_id, cache_root=cache_root)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def save_course_artifact(
    source_paths: list[str] | tuple[str, ...],
    artifact: dict[str, Any],
    *,
    model_id: str | None = None,
    prompt_version: str = COURSE_PREPARE_PROMPT_VERSION,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """Persist a course artifact and return the enriched cached payload."""
    path = cache_path or default_course_cache_path()
    key = course_artifact_key(source_paths, model_id=model_id, prompt_version=prompt_version)
    normalized = normalize_source_paths(source_paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, json.JSONDecodeError):
        data = {}

    if not isinstance(data, dict):
        data = {}
    artifacts = data.setdefault("artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}
        data["artifacts"] = artifacts

    artifact_with_pace = ensure_plan_v2_pace_mode(dict(artifact))
    cached = {
        **artifact_with_pace,
        "cache_key": key,
        "scope_hash": course_scope_hash(normalized),
        "source_paths": normalized,
        "model_id": model_id or get_settings().llm_model,
        "prompt_version": prompt_version,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    for field in ("generation_id", "source_content_hashes", "graph_quality_summary"):
        if field in artifact_with_pace:
            cached[field] = artifact_with_pace[field]
    artifacts[key] = cached
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return cached
