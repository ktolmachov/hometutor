"""Beautiful D3.js knowledge-graph renderer — Wave 1 + Wave 2 + Wave 3 complete.

Wave 1 packages shipped (all additive, zero breaking changes):
  KG-01  build_weekly_plan()   — "Plan My Week" overlay (📅 mode)
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

import json
from collections import deque
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from app.ui.knowledge_graph_d3_analysis import (
    build_cluster_labels,
    build_decay_vector,
    build_graph_health,
    build_mastery_history,
    build_weekly_plan,
)

_D3_PATH = Path(__file__).resolve().parent / "assets" / "d3.v7.min.js"
_HTML_TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "knowledge_graph_d3_template.html"
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
    max_reach = max(reach.values()) if reach else 0
    clusters = _connected_components(ids, edges)

    def mastery_pct(cid: str, data: Mapping[str, Any]) -> float:
        if cid in mastery_vector:
            return round(float(mastery_vector[cid]) * 100.0, 1)
        if cid in learned or bool(data.get("learned")):
            return 100.0
        return 0.0

    nodes: List[Dict[str, Any]] = []
    for cid, data in valid.items():
        m = mastery_pct(cid, data)
        is_learned = cid in learned or bool(data.get("learned")) or m >= 80.0
        prereqs = prereqs_map[cid]
        prereqs_ready = all(
            (p in mastery_vector and mastery_vector[p] * 100 >= 80)
            or p in learned
            or bool(valid.get(p, {}).get("learned"))
            for p in prereqs if p in id_set
        )
        frontier = (not is_learned) and m < 80.0 and prereqs_ready

        related = list(data.get("related_documents") or data.get("documents") or [])
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
            "related": related_cards,
            # KG-06: forgetting decay — null when no SRS record exists yet
            "decay": decay_vector.get(cid),
        })

    stats = {
        "total": len(nodes), "edges": len(edges),
        "learned": sum(1 for n in nodes if n["learned"]),
        "frontier": sum(1 for n in nodes if n["frontier"]),
        "missing": sum(1 for n in nodes if n["missing"]),
        "avg_mastery": round(sum(n["mastery"] for n in nodes) / len(nodes), 1) if nodes else 0.0,
        "clusters": len(set(clusters.values())) if clusters else 0,
    }

    return {
        "nodes": nodes,
        "edges": edges,
        "levels": _LEVEL_META,
        "stats": stats,
        # Wave 1 enrichments
        "weekly_plan": build_weekly_plan(nodes, due_reviews),
        "health": build_graph_health(nodes, edges),
        "cluster_labels": build_cluster_labels(nodes),
        # Wave 2 enrichments
        "decay_vector": decay_vector,          # KG-06: {concept_id: retention 0..1}
        # Wave 3 enrichments
        "mastery_history": build_mastery_history(quiz_rows or [], ids),  # KG-07
        "compiler_health": dict(compiler_health) if isinstance(compiler_health, Mapping) else None,
    }


def build_kg_html(payload: Mapping[str, Any]) -> str:
    d3_src = _load_d3_source()
    d3_tag = f"<script>{d3_src}</script>" if d3_src else '<script src="https://cdn.jsdelivr.net/npm/d3@7"></script>'
    return (
        _load_html_template()
        .replace("__D3_TAG__", d3_tag)
        .replace("__NODES__",         json.dumps(payload["nodes"],         ensure_ascii=False))
        .replace("__EDGES__",         json.dumps(payload["edges"],         ensure_ascii=False))
        .replace("__LEVELS__",        json.dumps(payload["levels"],        ensure_ascii=False))
        .replace("__STATS__",         json.dumps(payload["stats"],         ensure_ascii=False))
        .replace("__WEEKLY_PLAN__",   json.dumps(payload["weekly_plan"],   ensure_ascii=False))
        .replace("__HEALTH__",        json.dumps(payload["health"],        ensure_ascii=False))
        .replace("__CLUSTER_LABELS__",json.dumps(payload["cluster_labels"],ensure_ascii=False))
        .replace("__DECAY_VECTOR__",    json.dumps(payload.get("decay_vector", {}),    ensure_ascii=False))
        .replace("__MASTERY_HISTORY__", json.dumps(payload.get("mastery_history", []), ensure_ascii=False))
        .replace("__COMPILER_HEALTH__", json.dumps(payload.get("compiler_health"), ensure_ascii=False))
    )


def render_d3_knowledge_graph(
    concepts: Mapping[str, Any],
    mastery_vector: Mapping[str, float] | None = None,
    learned_set: Iterable[str] | None = None,
    doc_index: Mapping[str, Any] | None = None,
    typed_relations: Iterable[Mapping[str, Any]] | None = None,
    source_paths: list[str] | None = None,
    *,
    height: int = 720,
) -> Dict[str, Any]:
    """Render via ``st.components.v1.html``; return payload for companion widgets."""
    import streamlit.components.v1 as components

    due_reviews: List[Dict[str, Any]] = []
    sr_records: List[Dict[str, Any]] = []
    quiz_rows: List[Dict[str, Any]] = []
    try:
        from app.spaced_repetition import get_due_reviews, get_all_sr_concepts
        from app.user_state import _with_db
        due_reviews = get_due_reviews(limit=20)
        sr_records = get_all_sr_concepts()
    except Exception:  # noqa: BLE001 - missing review state leaves the optional overlay empty.
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
        components.html(build_kg_html(payload), height=height, scrolling=False)
    return payload
