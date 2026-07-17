"""Beautiful D3.js knowledge-graph renderer — Wave 1 + Wave 2 + Wave 3 complete.

Wave 1 packages shipped (all additive, zero breaking changes):
  KG-01  weekly plan overlay   — removed from user-facing graph UI (C2)
  KG-02  build_graph_health()  — Graph diagnostics panel (🔬)
  KG-03  build_cluster_labels()— Named cluster hulls
  KG-04  SVG export + permalink copy (⬇ SVG / 🔗 buttons)

Wave 2 packages shipped:
  KG-05  Guided path animation — BFS маршрут + D3 step-by-step reveal (🗺 кнопка)
  KG-06  Forgetting decay overlay — Ebbinghaus retention → серый оверлей (🧠 кнопка)

Wave 3 packages shipped:
  KG-07  Mastery-over-time scrubber — temporal slider по quiz_results (⏱ кнопка)

Public API (unchanged):
    build_kg_payload(concepts, mastery_vector, learned_set, doc_index, due_reviews)
    render_d3_knowledge_graph(concepts, mastery_vector, learned_set, ...)
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from hmac import compare_digest
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence

from app.ui.knowledge_graph_d3_analysis import (
    build_cluster_labels,
    build_decay_vector,
    build_graph_health,
    build_mastery_history,
    compute_decay,
    node_worth,
    select_day_route,
    top_worth_factor,
)

# Canonical lesson-node detection lives in the data layer (B1): every surface —
# progress stats, D3/counters, graph audit, Mission Control card — shares one rule.
from app.knowledge_graph import is_lesson_node as _is_lesson_node

_D3_PATH = Path(__file__).resolve().parent / "assets" / "d3.v7.min.js"
_HTML_TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "knowledge_graph_d3_template.html"
_3D_TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "kg_3d_template.html"
_COMPONENT_PATH = Path(__file__).resolve().parent / "assets" / "kg_d3_component"
_3D_COMPONENT_PATH = Path(__file__).resolve().parent / "assets" / "kg_3d_component"

# G0 action bridge (embedded 3D hall → Python). UI-state only; no per-user table.
KG_3D_ACTION_KEY = "kg_3d_action"
KG_3D_SESSION_NONCE_KEY = "kg_3d_session_nonce"
KG_3D_DEDUP_KEY = "kg_3d_event_dedup"
KG_3D_QUERY_PARAM = "_kg3d"
KG_3D_MAX_RAW_LEN = 600
KG_3D_DEDUP_MAX = 64
_KG3D_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_KG3D_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$", re.IGNORECASE)
_KG3D_ACTIONS = frozenset({"start", "collect"})
_MISSING_TEMPLATE_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<style>
body{font-family:system-ui,sans-serif;background:#0a0a0f;color:#e8e8f0;margin:0;padding:24px;}
.err{border:1px solid rgba(239,68,68,.45);border-radius:10px;padding:16px;background:rgba(239,68,68,.10);}
.mut{color:#a1a1aa;font-size:13px;line-height:1.5;}
</style>
</head>
<body>
<div class="err">
<strong>Knowledge Graph не смог загрузить HTML-шаблон.</strong>
<p class="mut">Проверьте, что в сборку попал файл app/ui/assets/knowledge_graph_d3_template.html.</p>
</div>
</body>
</html>"""

_LEVEL_META = {
    "lesson":      {"label": "📘 Лекция",         "color": "#fbbf24"},
    "beginner":    {"label": "🌱 Beginner",      "color": "#38bdf8"},
    "intermediate":{"label": "🌿 Intermediate",   "color": "#a78bfa"},
    "advanced":    {"label": "🌳 Advanced",       "color": "#fb7185"},
    "unknown":     {"label": "❔ Без уровня",     "color": "#64748b"},
}


@lru_cache(maxsize=1)
def _load_d3_source() -> str:
    try:
        return _D3_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


@lru_cache(maxsize=1)
def _load_html_template() -> str:
    try:
        return _HTML_TEMPLATE_PATH.read_text(encoding="utf-8")
    except OSError:
        return _MISSING_TEMPLATE_HTML


@lru_cache(maxsize=1)
def _load_3d_template() -> str:
    """Self-contained 3D hall template (B1). No CDN; must be fully offline."""
    try:
        return _3D_TEMPLATE_PATH.read_text(encoding="utf-8")
    except OSError:
        return "<!doctype html><title>3D Knowledge Graph</title><body style='font-family:sans-serif;background:#0a0a0f;color:#ddd;padding:2rem'>3D template not found. Place kg_3d_template.html next to the 2D one.</body>"


def _norm_level(raw: Any) -> str:
    lvl = str(raw or "").strip().lower()
    return lvl if lvl in _LEVEL_META else "unknown"


def _evidence_doc_label(doc_id: Any, doc_index: Mapping[str, Any]) -> str | None:
    ref = str(doc_id or "").strip()
    if not ref:
        return None
    meta = doc_index.get(ref, {}) if isinstance(doc_index, Mapping) else {}
    if isinstance(meta, Mapping):
        label = str(meta.get("relative_path") or meta.get("file_name") or "").strip()
        if label:
            return label
    return ref


def _reach_count(start: str, adj: Mapping[str, List[str]]) -> int:
    seen: set[str] = set()
    q: deque[str] = deque(adj.get(start, []))
    while q:
        n = q.popleft()
        if n in seen:
            continue
        seen.add(n)
        q.extend(adj.get(n, []))
    return len(seen)


def _connected_components(node_ids: Sequence[str], edges: Sequence[Dict[str, str]]) -> Dict[str, int]:
    parent = {nid: nid for nid in node_ids}

    def find(x: str) -> str:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for e in edges:
        a, b = e["source"], e["target"]
        if a in parent and b in parent:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

    root_to_idx: Dict[str, int] = {}
    return {nid: root_to_idx.setdefault(find(nid), len(root_to_idx)) for nid in node_ids}


# ── Shared graph skeleton + counters (B1: single source of truth) ─────
#
# Mission Control and the Knowledge Graph screen must report identical counters
# for the same graph version. The frontier is RECOMPUTED from mastery_vector +
# prerequisite-readiness (never the stale raw ``frontier`` bundle flag).
# ``build_kg_payload`` (heavy D3 render) and ``compute_kg_counters`` (lightweight
# Mission Control path) share the same skeleton + frontier math so the two cannot
# drift apart again.


@dataclass
class _KGSkeleton:
    """Resolved graph skeleton shared by the heavy renderer and the counter helper."""

    valid: Dict[str, Any]
    ids: List[str]
    id_set: set
    edges: List[Dict[str, Any]]
    prereqs_map: Dict[str, List[str]]
    missing_map: Dict[str, List[str]]
    fwd: Dict[str, List[str]]
    unlocks: Dict[str, List[str]]
    reach: Dict[str, int]
    clusters: Dict[str, int]


def _build_kg_skeleton(
    concepts: Mapping[str, Any],
    typed_relations: Iterable[Mapping[str, Any]] | None = None,
    doc_index: Mapping[str, Any] | None = None,
) -> _KGSkeleton:
    """Resolve concepts into nodes, edges, prerequisites, reach and clusters.

    Pure extraction of the structure ``build_kg_payload`` builds up-front; shared with
    :func:`compute_kg_counters` so both paths operate on the identical graph view.
    """
    doc_index = doc_index or {}
    valid = {cid: data for cid, data in concepts.items() if isinstance(data, dict)}
    ids = list(valid.keys())
    id_set = set(ids)
    label_to_id = {
        str(data.get("label") or cid).strip(): cid
        for cid, data in valid.items()
        if str(data.get("label") or cid).strip()
    }

    def resolve_concept_id(value: Any) -> str | None:
        ref = str(value or "").strip()
        if ref in id_set:
            return ref
        return label_to_id.get(ref)

    edges: List[Dict[str, Any]] = []
    prereqs_map: Dict[str, List[str]] = {}
    missing_map: Dict[str, List[str]] = {}
    seen_edges: set[tuple[str, str]] = set()
    for relation in typed_relations or []:
        source = resolve_concept_id(relation.get("source_concept_id"))
        target = resolve_concept_id(relation.get("target_concept_id"))
        if not source or not target or source == target:
            continue
        key = (source, target)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append({
            "source": source,
            "target": target,
            "relation_type": str(relation.get("relation_type") or "related"),
            "confidence": relation.get("confidence"),
            "evidence_doc_id": relation.get("evidence_doc_id"),
            "evidence_chunk_id": relation.get("evidence_chunk_id"),
            "weak_evidence": relation.get("weak_evidence"),
            "inferred_relation": relation.get("inferred_relation"),
            "evidence_doc_label": _evidence_doc_label(relation.get("evidence_doc_id"), doc_index),
        })

    for cid, data in valid.items():
        raw_prereqs = [str(p).strip() for p in (data.get("prerequisites") or []) if str(p).strip()]
        prereqs = [resolved for p in raw_prereqs if (resolved := resolve_concept_id(p))]
        prereqs_map[cid] = prereqs
        missing_map[cid] = [p for p in raw_prereqs if resolve_concept_id(p) is None]
        for p in prereqs:
            key = (p, cid)
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({
                    "source": p,
                    "target": cid,
                    "relation_type": "prerequisite",
                })

    seen_related: set[tuple[str, str]] = set()
    for cid, data in valid.items():
        related = [str(r).strip() for r in (data.get("related_concepts") or []) if str(r).strip()]
        for r in related:
            related_id = resolve_concept_id(r)
            if related_id:
                canon = (min(cid, related_id), max(cid, related_id))
                if canon not in seen_related:
                    seen_related.add(canon)
                    key = (cid, related_id)
                    if key not in seen_edges and (related_id, cid) not in seen_edges:
                        seen_edges.add(key)
                        edges.append({
                            "source": cid,
                            "target": related_id,
                            "relation_type": "related",
                        })

    fwd: Dict[str, List[str]] = {cid: [] for cid in ids}
    unlocks: Dict[str, List[str]] = {cid: [] for cid in ids}
    for e in edges:
        fwd[e["source"]].append(e["target"])
        unlocks[e["source"]].append(e["target"])

    reach = {cid: _reach_count(cid, fwd) for cid in ids}
    clusters = _connected_components(ids, edges)

    return _KGSkeleton(
        valid=valid,
        ids=ids,
        id_set=id_set,
        edges=edges,
        prereqs_map=prereqs_map,
        missing_map=missing_map,
        fwd=fwd,
        unlocks=unlocks,
        reach=reach,
        clusters=clusters,
    )


def _mastery_pct(
    cid: str,
    data: Mapping[str, Any],
    mastery_vector: Mapping[str, float],
    learned: set[str],
) -> float:
    if cid in mastery_vector:
        return round(float(mastery_vector[cid]) * 100.0, 1)
    if cid in learned or bool(data.get("learned")):
        return 100.0
    return 0.0


def _frontier_state(
    cid: str,
    data: Mapping[str, Any],
    prereqs: List[str],
    mastery_vector: Mapping[str, float],
    learned: set[str],
    id_set: set[str],
    valid: Mapping[str, Any],
) -> tuple[float, bool, bool]:
    """Single source for the per-node (mastery, learned, frontier) decision.

    ``frontier`` is recomputed from mastery + prerequisite-readiness (matching the D3
    renderer), not read from the stale raw ``frontier`` flag stored in the bundle.
    """
    m = _mastery_pct(cid, data, mastery_vector, learned)
    is_learned = cid in learned or bool(data.get("learned")) or m >= 80.0
    if _is_lesson_node(cid, data):
        return m, is_learned, False
    prereqs_ready = all(
        (p in mastery_vector and mastery_vector[p] * 100 >= 80)
        or p in learned
        or bool(valid.get(p, {}).get("learned"))
        for p in prereqs if p in id_set
    )
    frontier = (not is_learned) and m < 80.0 and prereqs_ready
    return m, is_learned, frontier


def _kg_counters_from_skeleton(
    skel: _KGSkeleton,
    mastery_vector: Mapping[str, float],
    learned: set[str],
) -> Dict[str, Any]:
    """Unified Knowledge Graph counters from a built skeleton (B1).

    Consumed by both :func:`build_kg_payload` (graph screen ``stats``) and
    :func:`compute_kg_counters` (Mission Control card), so the two screens report
    identical numbers for the same graph.

    ``total_concepts`` excludes lesson nodes (detected via :func:`_is_lesson_node`:
    ``lesson:`` id prefix OR ``level == "lesson"``). ``learned`` and ``frontier`` are
    concept-only counters so labels like "доступно" never include curriculum-anchor
    lessons. ``avg_mastery`` still divides by ALL nodes (concepts + lessons)
    intentionally — lesson nodes carry aggregate mastery in the bundle and both screens
    historically used the full node set as the denominator. Keeping it preserves the
    existing mastery calibration.
    """
    total = len(skel.valid)
    total_concepts = 0
    total_lessons = 0
    learned_count = 0
    frontier_count = 0
    missing_count = 0
    mastery_sum = 0.0
    for cid, data in skel.valid.items():
        is_lesson = _is_lesson_node(cid, data)
        if is_lesson:
            total_lessons += 1
        else:
            total_concepts += 1
        m, is_learned, is_frontier = _frontier_state(
            cid, data, skel.prereqs_map.get(cid, []),
            mastery_vector, learned, skel.id_set, skel.valid,
        )
        mastery_sum += m
        if is_learned and not is_lesson:
            learned_count += 1
        if is_frontier and not is_lesson:
            frontier_count += 1
        if skel.missing_map.get(cid):
            missing_count += 1
    return {
        "total": total,
        "total_nodes": total,
        "total_concepts": total_concepts,
        "total_lessons": total_lessons,
        "edges": len(skel.edges),
        "learned": learned_count,
        "frontier": frontier_count,
        "missing": missing_count,
        "avg_mastery": round(mastery_sum / total, 1) if total else 0.0,
        "clusters": len(set(skel.clusters.values())) if skel.clusters else 0,
    }


def _enrich_stats_with_learner_velocity(stats: dict[str, Any]) -> None:
    try:
        from app import learner_model_service as _learner_model_service

        _plm = _learner_model_service.get_personalized_learner_profile()
        stats["velocity"] = round(float(_plm.learning_velocity) * 100, 1)
        stats["sessions"] = int(_plm.sessions_completed or 0)
        migration = _plm.state_migration if isinstance(_plm.state_migration, dict) else {}
        stats["interactions"] = int(migration.get("learning_interactions_total") or 0)
    except Exception:  # noqa: BLE001 — learner stats enrichment must not break graph rendering
        pass


def compute_kg_counters(
    concepts: Mapping[str, Any],
    mastery_vector: Mapping[str, float] | None = None,
    learned_set: Iterable[str] | None = None,
    typed_relations: Iterable[Mapping[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Unified Knowledge Graph counters — single source of truth for UI (B1).

    Lightweight: builds only the graph skeleton (no document sections / D3 nodes) and
    recomputes the frontier exactly like :func:`build_kg_payload`. Mission Control and
    the Knowledge Graph screen both derive their visible counters from this math.

    Returns ``total``/``total_nodes`` (all nodes), ``total_concepts`` (without lesson
    nodes), ``total_lessons``, concept-only ``frontier``/``learned``, ``avg_mastery``,
    ``clusters`` and ``edges``.
    """
    skel = _build_kg_skeleton(concepts, typed_relations)
    mv = mastery_vector or {}
    learned = {str(x).strip() for x in (learned_set or []) if str(x).strip()}
    stats = _kg_counters_from_skeleton(skel, mv, learned)
    _enrich_stats_with_learner_velocity(stats)
    return stats


def collect_kg_learned_set(concepts: Mapping[str, Any]) -> set[str]:
    """Learned concept ids for the current session — shared input for counters (B1).

    Combines in-session tutor-learned concepts
    (``st.session_state["tutor_learned_concepts"]``) with the persisted ``learned`` flags
    from the graph bundle. Mission Control and the Knowledge Graph tab must build the
    SAME set and pass it to :func:`compute_kg_counters` / :func:`build_kg_payload`, so a
    concept learned only in the current session moves frontier / learned / avg_mastery
    identically on both screens.
    """
    import streamlit as st

    learned: set[str] = set(st.session_state.get("tutor_learned_concepts") or [])
    for cid, data in concepts.items():
        if isinstance(data, dict) and data.get("learned"):
            learned.add(cid)
    return learned


# ── Document path resolution (Obsidian / VS Code deep-links) ─────────

def _document_paths(rel_path: str) -> tuple[str | None, str | None, str | None]:
    """Resolve (source_abs, vault_md_abs, obs_uri) for a document card.

    ``vault_md_abs`` / ``obs_uri`` are non-null only when a converted Markdown exists.
    Failures degrade gracefully so the graph still renders.
    """
    try:
        from app import obsidian_export as oe

        src = oe.resolve_source(rel_path)
        if src is None:
            return None, None, None
        md = oe.vault_target(src)
        if md.exists():
            return str(src), str(md), oe.obsidian_uri(md)
        return str(src), None, None
    except Exception:  # noqa: BLE001  # pragma: no cover - path lookup must not break graph rendering.
        return None, None, None


def _document_sections(
    path: str,
    query_text: str,
    *,
    index_cache: dict[str, list[Any]] | None = None,
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """Top-``top_k`` matching sections (heading + Obsidian/VS Code deep-links) for a related doc.

    Концепт часто разобран в нескольких местах конспекта (тема, антипаттерны, термины) —
    показываем до трёх. Empty list when the document has no konspekt yet, no sections were
    parsed or nothing overlaps the query — the caller falls back to the whole-document
    ``needs_konspekt``/``obs_uri`` hint.

    ``index_cache`` — per-render memoization by ``path``: many concept nodes can share
    the same related document, so :func:`build_kg_payload` threads one dict through its
    whole loop to avoid re-resolving/re-reading/re-hashing the same md-file per concept
    (module-level sha-cache in ``section_index`` still covers repeats *across* renders).
    """
    try:
        from app.obsidian_export import obsidian_uri, vscode_uri
        from app.section_index import build_section_index, top_sections_for

        if index_cache is not None:
            sections = index_cache.get(path)
            if sections is None:
                sections = build_section_index(path)
                index_cache[path] = sections
        else:
            sections = build_section_index(path)
        if not sections:
            return []
        return [
            {
                "heading_text": section.heading_text,
                "line_start": section.line_start,
                "obs_uri": obsidian_uri(section.konspekt_md_abs, heading_text=section.heading_text),
                "vscode_uri": vscode_uri(section.konspekt_md_abs, line=section.line_start),
            }
            for section in top_sections_for(sections, query_text, k=top_k)
        ]
    except Exception:  # noqa: BLE001  # pragma: no cover - section lookup must not break graph rendering.
        return []


# ── Main payload builder ─────────────────────────────────────────────

def build_kg_payload(
    concepts: Mapping[str, Any],
    mastery_vector: Mapping[str, float] | None = None,
    learned_set: Iterable[str] | None = None,
    doc_index: Mapping[str, Any] | None = None,
    due_reviews: List[Mapping[str, Any]] | None = None,
    sr_records: List[Dict[str, Any]] | None = None,
    quiz_rows: List[Dict[str, Any]] | None = None,
    typed_relations: Iterable[Mapping[str, Any]] | None = None,
    compiler_health: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Assemble all graph data for the D3 renderer."""
    mastery_vector = mastery_vector or {}
    learned = {str(x).strip() for x in (learned_set or []) if str(x).strip()}
    doc_index = doc_index or {}
    decay_vector = build_decay_vector(sr_records or [])
    section_index_cache: dict[str, list[Any]] = {}

    skel = _build_kg_skeleton(concepts, typed_relations, doc_index)
    valid = skel.valid
    ids = skel.ids
    id_set = skel.id_set
    edges = skel.edges
    prereqs_map = skel.prereqs_map
    missing_map = skel.missing_map
    unlocks = skel.unlocks
    reach = skel.reach
    clusters = skel.clusters
    max_reach = max(reach.values()) if reach else 0

    # Build label->id map and resolver exactly like in _build_kg_skeleton so due
    # from SR (which may store labels or aliases) attaches to canonical cid.
    label_to_id = {
        str(data.get("label") or cid).strip(): cid
        for cid, data in valid.items()
        if str(data.get("label") or cid).strip()
    }

    def _resolve_cid(ref: Any) -> str | None:
        s = str(ref or "").strip()
        if s in id_set:
            return s
        return label_to_id.get(s)

    # A1/A2: price on node. Scope to this graph only (ignore dues for concepts
    # not present in current bundle). Use the shared resolver.
    due_map: dict[str, int] = {}
    for r in (due_reviews or []):
        c = str(r.get("concept") or "").strip()
        if c:
            cid = _resolve_cid(c)
            if cid:
                due_map[cid] = due_map.get(cid, 0) + 1

    def _is_novel(cid: str, is_lesson_flag: bool) -> bool:
        if is_lesson_flag:
            return False
        return (cid not in mastery_vector) and (cid not in decay_vector)

    nodes: List[Dict[str, Any]] = []
    for cid, data in valid.items():
        prereqs = prereqs_map[cid]
        m, is_learned, frontier = _frontier_state(
            cid, data, prereqs, mastery_vector, learned, id_set, valid
        )

        related = list(data.get("related_documents") or data.get("documents") or [])
        courses = sorted({
            str(rp).replace("\\", "/").split("/", 1)[0]
            for rp in related
            if "/" in str(rp).replace("\\", "/")
        })
        related_cards = []
        for rp in related[:12]:
            meta = doc_index.get(str(rp), {}) if isinstance(doc_index, Mapping) else {}
            path = meta.get("relative_path") or meta.get("file_name") or str(rp)
            src_abs, md_abs, obs_uri = _document_paths(path)
            sections: List[Dict[str, Any]] = []
            if md_abs:
                query_text = " ".join(
                    part for part in [
                        str(data.get("label") or cid),
                        str(data.get("description") or ""),
                        " ".join(meta.get("key_concepts") or []) if isinstance(meta, Mapping) else "",
                    ]
                    if part
                )
                sections = _document_sections(path, query_text, index_cache=section_index_cache)
            related_cards.append({
                "path": path,
                "meta": " · ".join(p for p in [
                    str(meta.get("doc_type") or "").strip(),
                    str(meta.get("difficulty") or "").strip(),
                ] if p) or "document",
                "summary": str(meta.get("summary") or "")[:220],
                "src_abs": src_abs,
                "md_abs": md_abs,
                "obs_uri": obs_uri,
                "is_txt": bool(src_abs and src_abs.lower().endswith(".txt")),
                "sections": sections,
                "needs_konspekt": bool(src_abs and not md_abs),
            })

        is_lesson = _is_lesson_node(cid, data)
        novel = _is_novel(cid, is_lesson)

        nodes.append({
            "id": cid, "label": str(data.get("label") or cid),
            "level": _norm_level(data.get("level")),
            "desc": str(data.get("description") or "").strip(),
            "mastery": m, "learned": bool(is_learned), "frontier": bool(frontier),
            "prereqs": prereqs, "unlocks": sorted(set(unlocks[cid])),
            "missing": missing_map[cid],
            "reach": reach[cid],
            "centrality": round(reach[cid] / max_reach, 4) if max_reach else 0.0,
            "cluster": clusters.get(cid, 0),
            "courses": courses,
            "related": related_cards,
            # KG-06: forgetting decay — null when no SRS record exists yet
            "decay": decay_vector.get(cid),
            # A1: price signals (due already fetched upstream; novel = untouched non-lesson)
            "due": due_map.get(cid, 0),
            "novel": bool(novel),
            "is_lesson": bool(is_lesson),
        })

    # A2: attach worth + dominant reason (post-process; pure, cheap)
    for nd in nodes:
        nd["worth"] = node_worth(nd)
        nd["worth_reason"] = top_worth_factor(nd)

    day_route = select_day_route(nodes, k=6)

    stats = _kg_counters_from_skeleton(skel, mastery_vector, learned)

    _enrich_stats_with_learner_velocity(stats)

    return {
        "nodes": nodes,
        "edges": edges,
        "levels": _LEVEL_META,
        "stats": stats,
        # C2: no user-facing weekly graph planner. Keep the key as a stable
        # export contract, but do not expose a competing source of "today".
        "weekly_plan": [],
        "health": build_graph_health(nodes, edges),
        "cluster_labels": build_cluster_labels(nodes),
        # Wave 2 enrichments
        "decay_vector": decay_vector,          # KG-06: {concept_id: retention 0..1}
        "day_route": day_route,                # A2: precomputed top actionable stops (for 3D + consistency)
        # Wave 3 enrichments
        "mastery_history": build_mastery_history(quiz_rows or [], ids),  # KG-07
        "compiler_health": dict(compiler_health) if isinstance(compiler_health, Mapping) else None,
    }


def _json_for_script(value: Any) -> str:
    """Serialize JSON safe to embed inside a ``<script>`` block.

    Escapes ``<`` / ``>`` / ``&`` so a label containing ``</script>`` or HTML
    cannot break out of the script context when the offline HTML is opened.
    """
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _day_route_ids(payload: Mapping[str, Any]) -> list[str]:
    day_route = payload.get("day_route") or []
    if not isinstance(day_route, list):
        return []
    route_ids: list[str] = []
    for item in day_route:
        if isinstance(item, str) and item.strip():
            route_ids.append(item.strip())
        elif isinstance(item, Mapping):
            rid = str(item.get("id") or "").strip()
            if rid:
                route_ids.append(rid)
    return route_ids


def build_kg_html(payload: Mapping[str, Any]) -> str:
    d3_src = _load_d3_source()
    if d3_src:
        d3_tag = f"<script>{d3_src}</script>"
    else:
        # Local-first / offline contract for exported self-contained HTML.
        # No CDN fallback (would break the "скачать и открыть без интернета" promise).
        d3_tag = '<script>/* d3.v7.min.js missing from assets — self-contained export requires the vendored file */</script>'
    return (
        _load_html_template()
        .replace("__D3_TAG__", d3_tag)
        .replace("__NODES__",         _json_for_script(payload["nodes"]))
        .replace("__EDGES__",         _json_for_script(payload["edges"]))
        .replace("__LEVELS__",        _json_for_script(payload["levels"]))
        .replace("__STATS__",         _json_for_script(payload["stats"]))
        .replace("__HEALTH__",        _json_for_script(payload["health"]))
        .replace("__CLUSTER_LABELS__",_json_for_script(payload["cluster_labels"]))
        .replace("__DECAY_VECTOR__",    _json_for_script(payload.get("decay_vector", {})))
        .replace("__MASTERY_HISTORY__", _json_for_script(payload.get("mastery_history", [])))
        .replace("__COMPILER_HEALTH__", _json_for_script(payload.get("compiler_health")))
        .replace("__DAY_ROUTE__",       _json_for_script(_day_route_ids(payload)))
    )


def ensure_kg_3d_session_nonce(state: MutableMapping[str, Any]) -> str:
    """128-bit random nonce for the current Streamlit session (action envelope)."""
    existing = str(state.get(KG_3D_SESSION_NONCE_KEY) or "").strip()
    if existing:
        return existing
    nonce = secrets.token_hex(16)
    state[KG_3D_SESSION_NONCE_KEY] = nonce
    return nonce


def _valid_event_id(event_id: str) -> bool:
    if _KG3D_UUID_RE.match(event_id):
        return True
    return bool(_KG3D_ULID_RE.match(event_id))


def decode_kg_3d_query_raw(raw: str) -> dict[str, Any] | None:
    """Decode base64url(minified JSON) action envelope; length-capped.

    Returns None for empty/malformed/oversized payloads. Does not validate
    domain fields (nonce, concept membership) — see :func:`validate_kg_3d_envelope`.
    """
    text = str(raw or "").strip()
    if not text or len(text) > KG_3D_MAX_RAW_LEN:
        return None
    try:
        pad = "=" * (-len(text) % 4)
        data = base64.urlsafe_b64decode(text + pad)
        env = json.loads(data.decode("utf-8"))
    except (ValueError, binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return env if isinstance(env, dict) else None


def validate_kg_3d_envelope(
    env: Mapping[str, Any] | None,
    *,
    session_nonce: str,
    node_ids: Iterable[str],
) -> dict[str, Any] | None:
    """Validate G0 envelope fields; constant-time nonce compare."""
    if not isinstance(env, Mapping):
        return None
    if int(env.get("version") or 0) != 1:
        return None
    if str(env.get("source") or "") != "kg3d":
        return None
    action = str(env.get("action") or "").strip()
    if action not in _KG3D_ACTIONS:
        return None
    concept_id = str(env.get("concept_id") or "").strip()
    event_id = str(env.get("event_id") or "").strip()
    nonce = str(env.get("session_nonce") or "").strip()
    if not concept_id or not event_id or not nonce:
        return None
    if not _valid_event_id(event_id):
        return None
    # Constant-time: pad/truncate comparison length only after length match.
    expected = str(session_nonce or "")
    if len(nonce) != len(expected) or not compare_digest(nonce, expected):
        return None
    allowed = {str(n).strip() for n in node_ids if str(n).strip()}
    if concept_id not in allowed:
        return None
    return {
        "version": 1,
        "source": "kg3d",
        "event_id": event_id,
        "session_nonce": nonce,
        "concept_id": concept_id,
        "action": action,
    }


def _kg_3d_dedup_map(state: MutableMapping[str, Any]) -> OrderedDict[str, str]:
    raw = state.get(KG_3D_DEDUP_KEY)
    if isinstance(raw, OrderedDict):
        return raw
    if isinstance(raw, dict):
        od: OrderedDict[str, str] = OrderedDict()
        for k, v in raw.items():
            key = str(k).strip()
            status = str(v or "").strip()
            if key and status in {"processing", "succeeded", "failed"}:
                od[key] = status
        state[KG_3D_DEDUP_KEY] = od
        return od
    od = OrderedDict()
    state[KG_3D_DEDUP_KEY] = od
    return od


def reserve_kg_3d_event_id(state: MutableMapping[str, Any], event_id: str) -> bool:
    """Reserve ``event_id`` before side effect. False if already seen in window."""
    eid = str(event_id or "").strip()
    if not eid:
        return False
    dedup = _kg_3d_dedup_map(state)
    if eid in dedup:
        return False
    dedup[eid] = "processing"
    while len(dedup) > KG_3D_DEDUP_MAX:
        dedup.popitem(last=False)
    return True


def mark_kg_3d_event(
    state: MutableMapping[str, Any], event_id: str, status: str
) -> None:
    """Mark reserved event as succeeded|failed (or processing)."""
    eid = str(event_id or "").strip()
    if not eid:
        return
    if status not in {"processing", "succeeded", "failed"}:
        return
    dedup = _kg_3d_dedup_map(state)
    dedup[eid] = status
    while len(dedup) > KG_3D_DEDUP_MAX:
        dedup.popitem(last=False)


def consume_kg_3d_query_param(
    *,
    raw: str | None,
    session_nonce: str,
    node_ids: Iterable[str],
    state: MutableMapping[str, Any],
) -> dict[str, Any] | None:
    """Validate → reserve event_id. Caller removes query param always.

    Order (plan G0): validate → remove query param (caller) → reserve → execute → ack.
    Returns a validated envelope ready for execute, or None if rejected/duplicate.
    """
    env = validate_kg_3d_envelope(
        decode_kg_3d_query_raw(str(raw or "")),
        session_nonce=session_nonce,
        node_ids=node_ids,
    )
    if env is None:
        return None
    if not reserve_kg_3d_event_id(state, env["event_id"]):
        return None
    return env


def encode_kg_3d_query_raw(envelope: Mapping[str, Any]) -> str:
    """Test/helper: encode envelope as base64url(minified JSON)."""
    raw = json.dumps(dict(envelope), ensure_ascii=False, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def build_kg_3d_html(
    payload: Mapping[str, Any],
    *,
    host_mode: str = "export",
    session_nonce: str = "",
    collected_concept_ids: Sequence[str] | None = None,
    workbench_count: int | None = None,
    exported_at: str | None = None,
) -> str:
    """Self-contained offline 3D Knowledge Graph hall (no CDN).

    Same payload as the 2D map: nodes (worth/due/novel), edges, stats, and
    precomputed ``day_route`` (A2 stops). Export defaults to **route scene**
    (first frame = day path, not full graph); worth is rank/reason, not height.

    Render-contract extensions (not domain schema):
    - ``host_mode``: ``export`` (inert actions) | ``embedded`` (action bridge)
    - ``session_nonce``: embedded-only envelope binding
    - ``collected_concept_ids`` / ``workbench_count``: embedded inventory view-model
    - mastery_history / decay_vector / snapshot_date: G2 memory overlay inputs
    """
    mode = "embedded" if str(host_mode or "").strip().lower() == "embedded" else "export"
    t = _load_3d_template()
    route_ids = _day_route_ids(payload)
    snap = str(exported_at or "").strip() or date.today().isoformat()
    collected = [
        str(c).strip()
        for c in (collected_concept_ids or [])
        if str(c).strip()
    ]
    # Export never bakes live basket state (honest offline contract).
    if mode == "export":
        collected = []
        wb_count: int | None = None
        nonce = ""
    else:
        wb_count = int(workbench_count) if workbench_count is not None else None
        nonce = str(session_nonce or "").strip()
    return (
        t.replace("__NODES__", _json_for_script(payload.get("nodes", [])))
        .replace("__EDGES__", _json_for_script(payload.get("edges", [])))
        .replace("__STATS__", _json_for_script(payload.get("stats", {})))
        .replace("__HEALTH__", _json_for_script(payload.get("health")))
        .replace("__DAY_ROUTE__", _json_for_script(route_ids))
        .replace("__MASTERY_HISTORY__", _json_for_script(payload.get("mastery_history", [])))
        .replace("__DECAY_VECTOR__", _json_for_script(payload.get("decay_vector", {})))
        .replace("__SNAPSHOT_DATE__", _json_for_script(snap))
        .replace("__HOST_MODE__", _json_for_script(mode))
        .replace("__SESSION_NONCE__", _json_for_script(nonce))
        .replace("__COLLECTED_IDS__", _json_for_script(collected))
        .replace(
            "__WORKBENCH_COUNT__",
            _json_for_script(wb_count if wb_count is not None else None),
        )
    )


@lru_cache(maxsize=1)
def _kg_d3_component():
    import streamlit.components.v1 as components

    return components.declare_component("kg_d3", path=str(_COMPONENT_PATH))


@lru_cache(maxsize=1)
def _kg_3d_component():
    import streamlit.components.v1 as components

    return components.declare_component("kg_3d", path=str(_3D_COMPONENT_PATH))


def render_kg_3d_hall(
    payload: Mapping[str, Any],
    *,
    session_nonce: str,
    collected_concept_ids: Sequence[str] | None = None,
    workbench_count: int | None = None,
    height: int = 720,
    key: str = "kg_3d_component",
) -> str | None:
    """Render embedded 3D hall via dedicated Streamlit component.

    Returns selected concept id (string) from ``setComponentValue`` if any.
    Actions are delivered exclusively via ``_kg3d`` query-param (not component value).
    """
    html = build_kg_3d_html(
        payload,
        host_mode="embedded",
        session_nonce=session_nonce,
        collected_concept_ids=collected_concept_ids,
        workbench_count=workbench_count,
    )
    selected = _kg_3d_component()(
        html=html,
        height=height,
        default=None,
        key=key,
    )
    if isinstance(selected, str) and selected.strip():
        return selected.strip()
    return None


def render_d3_knowledge_graph(
    concepts: Mapping[str, Any],
    mastery_vector: Mapping[str, float] | None = None,
    learned_set: Iterable[str] | None = None,
    doc_index: Mapping[str, Any] | None = None,
    typed_relations: Iterable[Mapping[str, Any]] | None = None,
    source_paths: list[str] | None = None,
    due_reviews: List[Dict[str, Any]] | None = None,
    *,
    height: int = 720,
) -> Dict[str, Any]:
    """Render via a local Streamlit component; return payload for companion widgets."""
    sr_records: List[Dict[str, Any]] = []
    quiz_rows: List[Dict[str, Any]] = []
    if due_reviews is None:
        try:
            from app.spaced_repetition import get_due_reviews, get_all_sr_concepts
            from app.user_state import _with_db
            # Fallback for callers without kg (tests etc.). Prefer caller to pass
            # scoped list via filter_due_reviews_for_kg(..., scan_limit=5000)
            due_reviews = get_due_reviews(limit=200)
        except Exception:  # noqa: BLE001 - missing review state leaves the optional overlay empty.
            due_reviews = []
    due_reviews = due_reviews or []
    try:
        from app.spaced_repetition import get_all_sr_concepts
        from app.user_state import _with_db
        sr_records = get_all_sr_concepts()
    except Exception:  # noqa: BLE001
        pass
    try:
        def _load_quiz(conn: Any) -> List[Dict[str, Any]]:
            rows = conn.execute(
                "SELECT concept, score, timestamp FROM quiz_results ORDER BY timestamp ASC LIMIT 4000"
            ).fetchall()
            return [dict(r) for r in rows]
        quiz_rows = _with_db(_load_quiz)
    except Exception:  # noqa: BLE001 - missing quiz history leaves the optional overlay empty.
        pass

    compiler_health = None
    try:
        from app.course_cache import resolve_compiler_health_for_kg

        paths = [str(p).strip() for p in (source_paths or []) if str(p).strip()]
        if paths:
            compiler_health = resolve_compiler_health_for_kg(source_paths=paths)
    except Exception:  # noqa: BLE001 - missing sidecar must not break graph render
        compiler_health = None

    payload = build_kg_payload(
        concepts,
        mastery_vector,
        learned_set,
        doc_index,
        due_reviews,
        sr_records,
        quiz_rows,
        typed_relations,
        compiler_health=compiler_health,
    )
    if payload["nodes"]:
        selected = _kg_d3_component()(
            html=build_kg_html(payload),
            height=height,
            default=None,
            key="kg_d3_component",
        )
        if isinstance(selected, str) and selected.strip():
            payload["selected_concept"] = selected.strip()
    return payload
