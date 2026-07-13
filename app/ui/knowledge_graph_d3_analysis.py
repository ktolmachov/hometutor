"""Analysis helpers for the D3 knowledge graph payload."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List


def build_graph_health(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Graph quality report: cycles, orphans, missing prerequisites, dead ends.

    Returns dict with keys: score (0–100), cycles, orphans, missing, dead_ends.
    """
    node_ids = [n["id"] for n in nodes]
    # directed adj: prereq → concept
    adj: Dict[str, List[str]] = {nid: [] for nid in node_ids}
    for e in edges:
        if e["source"] in adj and e["target"] in adj:
            adj[e["source"]].append(e["target"])

    # iterative DFS cycle detection (avoids Python recursion limit)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {nid: WHITE for nid in node_ids}
    cycles: List[List[str]] = []

    for start in node_ids:
        if color[start] != WHITE:
            continue
        stack = [(start, iter(adj.get(start, [])))]
        path: List[str] = [start]
        color[start] = GRAY
        while stack:
            _, children = stack[-1]
            try:
                child = next(children)
                if color[child] == GRAY:
                    idx = path.index(child)
                    cycle = path[idx:]
                    # deduplicate: only keep if not already seen
                    key = frozenset(cycle)
                    if not any(frozenset(c) == key for c in cycles):
                        cycles.append(cycle[:])
                elif color[child] == WHITE:
                    color[child] = GRAY
                    path.append(child)
                    stack.append((child, iter(adj.get(child, []))))
            except StopIteration:
                color[stack.pop()[0]] = BLACK
                if path:
                    path.pop()

    # undirected degree for orphan detection
    degree: Dict[str, int] = {nid: 0 for nid in node_ids}
    for e in edges:
        degree[e["source"]] = degree.get(e["source"], 0) + 1
        degree[e["target"]] = degree.get(e["target"], 0) + 1

    orphans = [
        n["id"] for n in nodes
        if degree.get(n["id"], 0) == 0 and not n.get("learned")
    ]
    missing = [
        {"concept": n["id"], "missing": n["missing"]}
        for n in nodes if n.get("missing")
    ]
    dead_ends = [
        n["id"] for n in nodes
        if n.get("level") == "advanced"
        and n.get("reach", 0) == 0
        and not n.get("related")
        and not n.get("learned")
    ]

    score = max(0, 100 - len(cycles) * 15 - len(orphans) * 5 - len(missing) * 3 - len(dead_ends) * 2)

    return {
        "score": score,
        "cycles": [list(c) for c in cycles[:6]],
        "orphans": orphans,
        "missing": missing[:12],
        "dead_ends": dead_ends,
    }


def build_cluster_labels(nodes: List[Dict[str, Any]]) -> Dict[str, str]:
    """For each cluster pick the highest-reach concept as label."""
    best: Dict[int, tuple[int, str]] = {}
    for n in nodes:
        cid = n.get("cluster", 0)
        reach = n.get("reach", 0)
        if cid not in best or reach > best[cid][0]:
            best[cid] = (reach, n["id"])
    return {str(cid): name for cid, (_, name) in best.items()}


# ── KG-06: Ebbinghaus forgetting decay ───────────────────────────────

def compute_decay(
    last_review_iso: str | None,
    easiness: float,
    interval_days: int,
) -> float:
    """Ebbinghaus-SM2 retention: R = e^(-elapsed / stability).

    stability = easiness * interval_days  (rough SM-2 approximation)
    Returns a value in [0, 1] — 1.0 means fully retained, 0.0 = fully forgotten.
    Returns 1.0 when ``last_review_iso`` is absent (never reviewed ≠ forgotten).
    """
    if not last_review_iso:
        return 1.0
    try:
        last = datetime.fromisoformat(last_review_iso.replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(tz=timezone.utc) - last).total_seconds() / 86400.0
        stability = max(0.1, float(easiness) * max(1, int(interval_days)))
        return round(min(1.0, max(0.0, math.exp(-elapsed / stability))), 4)
    except Exception:  # noqa: BLE001 - invalid SR metadata falls back to full retention.
        return 1.0


def build_decay_vector(sr_records: List[Dict[str, Any]]) -> Dict[str, float]:
    """Map concept_id → retention (0..1) from raw spaced-repetition rows."""
    result: Dict[str, float] = {}
    for row in sr_records:
        cid = str(row.get("concept") or "").strip()
        if not cid:
            continue
        result[cid] = compute_decay(
            row.get("last_review"),
            float(row.get("easiness") or 2.5),
            int(row.get("interval_days") or 1),
        )
    return result


# ── KG-07: mastery-over-time history ─────────────────────────────────

_EMA_ALPHA = 0.35  # EMA smoothing for quiz score → mastery


def build_mastery_history(
    quiz_rows: List[Dict[str, Any]],
    known_concept_ids: Iterable[str] | None = None,
) -> List[Dict[str, Any]]:
    """Build chronological mastery snapshots from raw quiz_results rows.

    Args:
        quiz_rows: list of {concept, score, timestamp} dicts, any order.
        known_concept_ids: optional filter — only include concepts in the graph.

    Returns:
        List of snapshots sorted by date ascending:
            [{"date": "2024-01-15", "mastery": {"Basics": 72.5, ...}}, ...]
        Empty list when quiz_rows is empty.

    Algorithm:
        - Sort by timestamp ASC.
        - EMA per concept (alpha=0.35): mastery = alpha*score + (1-alpha)*mastery.
        - Snapshot at each new calendar date (date-boundary snapshot).
        - Final snapshot always appended if the last day is not yet included.
    """
    if not quiz_rows:
        return []

    filter_ids: set[str] | None = None
    if known_concept_ids is not None:
        filter_ids = {str(c).strip() for c in known_concept_ids if str(c).strip()}

    # Sort ascending by timestamp (lexicographic ISO works fine)
    rows = sorted(quiz_rows, key=lambda r: str(r.get("timestamp") or ""))

    ema: Dict[str, float] = {}        # concept → current mastery 0..1
    snapshots: List[Dict[str, Any]] = []
    last_date: str | None = None

    def _take_snapshot(date: str) -> None:
        if not ema:
            return
        subset = {
            c: round(v * 100.0, 1)
            for c, v in ema.items()
            if filter_ids is None or c in filter_ids
        }
        if subset:
            snapshots.append({"date": date, "mastery": subset})

    for row in rows:
        ts = str(row.get("timestamp") or "").strip()
        if not ts:
            continue
        date = ts[:10]  # YYYY-MM-DD

        concept = str(row.get("concept") or "").strip()
        if not concept:
            continue
        if filter_ids is not None and concept not in filter_ids:
            continue

        try:
            score = max(0.0, min(1.0, float(row.get("score") or 0.0)))
        except (TypeError, ValueError):
            score = 0.0

        # Snapshot before processing a new day
        if last_date is not None and date != last_date:
            _take_snapshot(last_date)

        ema[concept] = _EMA_ALPHA * score + (1.0 - _EMA_ALPHA) * ema.get(concept, score)
        last_date = date

    # Final snapshot for the last day
    if last_date and (not snapshots or snapshots[-1]["date"] != last_date):
        _take_snapshot(last_date)

    return snapshots


# ── A2: node worth for value-based routing (wave-kg-node-worth) ────────

# Weights (documented, tunable only with tests). Personal urgency first.
DUE_WEIGHT = 5.0          # each due card (capped)
NOVEL_WEIGHT = 4.0        # brand new concept for this learner
DECAY_WEIGHT = 3.5        # penalty for low retention (1 - decay)
FRONTIER_WEIGHT = 2.0     # prereqs ready, not yet learned
REACH_WEIGHT = 1.0        # structural (centrality already normalized 0..1)


def node_worth(n: Dict[str, Any]) -> float:
    """Compute scalar worth of a study stop.

    Pure function. Higher = stop here sooner on "маршрут дня".
    Respects A1 signals (due, novel) + decay + frontier + reach.
    IMPORTANT: due (scheduled review) contributes to worth EVEN for learned nodes,
    because due means "time to repeat" (maintenance). Learned + due is valid repeat stop.
    """
    if not isinstance(n, dict):
        return 0.0
    if n.get("is_lesson"):
        # lessons are anchors; worth mainly on concepts
        return 0.5 * (float(n.get("centrality") or 0))

    due = float(n.get("due") or 0)
    novel = 1.0 if n.get("novel") else 0.0
    decay = n.get("decay")
    decay_p = (1.0 - float(decay)) if isinstance(decay, (int, float)) else 0.0
    frontier = 1.0 if n.get("frontier") else 0.0
    reach_n = float(n.get("centrality") or 0.0)

    w = (
        DUE_WEIGHT * min(due, 5.0)
        + NOVEL_WEIGHT * novel
        + DECAY_WEIGHT * decay_p
        + FRONTIER_WEIGHT * frontier
        + REACH_WEIGHT * reach_n
    )
    return round(max(0.0, w), 3)


def top_worth_factor(n: Dict[str, Any]) -> str:
    """Human label for the single largest contributor to worth (for route step)."""
    if not isinstance(n, dict):
        return ""
    parts = []
    due = float(n.get("due") or 0)
    if due > 0:
        parts.append((DUE_WEIGHT * min(due, 5.0), "🃏 к повторению"))
    if n.get("novel") and not n.get("learned"):
        parts.append((NOVEL_WEIGHT, "✨ новое для тебя"))
    dec = n.get("decay")
    if isinstance(dec, (int, float)) and dec < 0.65:
        parts.append((DECAY_WEIGHT * (1.0 - dec), "🧠 низкий retention"))
    if n.get("frontier") and not n.get("learned"):
        parts.append((FRONTIER_WEIGHT, "✦ prereqs готовы"))
    if not parts:
        return "структурная важность"
    parts.sort(reverse=True)
    return parts[0][1]


def select_day_route(
    nodes: list[Dict[str, Any]],
    k: int = 6,
) -> list[str]:
    """Select top actionable nodes by worth and try to chain them in prereq order.

    Actionable = has due > 0 or is frontier (and not lesson).
    Used by both 2D auto-route and 3D flight for consistency.
    """
    actionable = [
        n for n in nodes
        if not n.get("is_lesson")
        and ((n.get("due") or 0) > 0 or n.get("frontier"))
    ]
    if not actionable:
        return []

    # sort by worth desc (worth already attached)
    actionable = sorted(actionable, key=lambda n: n.get("worth") or 0, reverse=True)

    if len(actionable) <= k:
        return [n["id"] for n in actionable]

    selected: list[str] = []
    used: set[str] = set()
    top = actionable[: max(k, 10)]  # a bit more for chaining opportunities
    id_to_node = {n["id"]: n for n in top}

    if top:
        selected.append(top[0]["id"])
        used.add(top[0]["id"])

    while len(selected) < k and len(used) < len(top):
        last_id = selected[-1]
        last = id_to_node.get(last_id, {})
        unlocks = last.get("unlocks") or []

        best = None
        best_w = -1.0
        for u in unlocks:
            if u in id_to_node and u not in used:
                w = id_to_node[u].get("worth") or 0
                if w > best_w:
                    best = u
                    best_w = w

        if best:
            selected.append(best)
            used.add(best)
            continue

        # fallback to next highest worth not used
        for cand in top:
            if cand["id"] not in used:
                selected.append(cand["id"])
                used.add(cand["id"])
                break

    return selected[:k]
