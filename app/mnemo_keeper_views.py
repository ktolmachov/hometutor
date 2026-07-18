"""Мнемополис Keeper — view-model assembly for the 3D hall (W3b/W3c).

Pure read-only presentation layer: turns a KG payload + Keeper narrative into
hall-ready dicts (guide, threats). Extracted from :mod:`app.mnemo_keeper` so the
infra module stays under the architecture size budget. Hard rules are inherited:
never writes domain state; LLM only via provider-layer when explicitly allowed.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, MutableMapping

from app.mnemo_keeper import (
    KEEPER_SILENT_COPY,
    build_threats_from_decay,
    request_keeper,
)
from app.prompts import mnemo_keeper as prompts


# ── W3b: guide view-model for 3D hall (render-contract only) ─────────────


def stops_from_kg_payload(payload: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """Build compact stop rows from KG payload day_route + nodes."""
    payload = payload or {}
    nodes = payload.get("nodes") or []
    by_id: dict[str, Mapping[str, Any]] = {}
    for n in nodes:
        if not isinstance(n, Mapping):
            continue
        cid = str(n.get("id") or "").strip()
        if cid:
            by_id[cid] = n
    route = payload.get("day_route") or []
    stops: list[dict[str, str]] = []
    for raw_id in route:
        cid = str(raw_id or "").strip()
        if not cid:
            continue
        n = by_id.get(cid) or {}
        stops.append(
            {
                "id": cid,
                "label": str(n.get("label") or cid),
                "worth_reason": str(n.get("worth_reason") or ""),
            }
        )
    return stops


def guide_lines_by_stop(
    text: str,
    stops: list[dict[str, str]],
) -> dict[str, str]:
    """Map guide prose lines to concept ids (best-effort parse of «N. Name: text»)."""
    by_stop: dict[str, str] = {}
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    # Prefer positional match to day_route order.
    for i, stop in enumerate(stops):
        cid = str(stop.get("id") or "").strip()
        if not cid:
            continue
        if i < len(lines):
            line = lines[i]
            # Strip leading "N." / "N:"
            cleaned = line
            if ". " in line[:4]:
                cleaned = line.split(". ", 1)[-1]
            label = str(stop.get("label") or "")
            if label and cleaned.lower().startswith(label.lower()):
                rest = cleaned[len(label) :].lstrip(" :-—")
                by_stop[cid] = rest or cleaned
            else:
                by_stop[cid] = cleaned
        else:
            reason = str(stop.get("worth_reason") or "").strip()
            by_stop[cid] = reason or "в маршруте дня"
    return by_stop


def build_guide_view_model(
    payload: Mapping[str, Any] | None,
    *,
    session_state: MutableMapping[str, Any] | None = None,
    allow_llm: bool = False,
    snapshot_date: str = "",
    llm_complete: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """W3b: hall-ready guide dict ``{text, source, reason, by_stop, silent}``.

    First paint should call with ``allow_llm=False`` (static worth_reason narrative).
    Host may call again with ``allow_llm=True`` after explicit user action (LLM).
    """
    payload = payload or {}
    stops = stops_from_kg_payload(payload)
    route = [str(s.get("id") or "") for s in stops]
    snap = str(snapshot_date or "").strip()
    if not snap:
        hist = payload.get("mastery_history") or []
        if hist and isinstance(hist[-1], Mapping):
            snap = str(hist[-1].get("date") or "").strip()
    result = request_keeper(
        prompts.SCENARIO_GUIDE,
        snapshot_date=snap,
        day_route=route,
        stops=stops,
        allow_llm=allow_llm,
        session_state=session_state,
        llm_complete=llm_complete,
    )
    by_stop = guide_lines_by_stop(result.text, stops)
    # Guarantee every route stop has a line (honest degrade).
    for s in stops:
        cid = str(s.get("id") or "")
        if cid and cid not in by_stop:
            by_stop[cid] = str(s.get("worth_reason") or "в маршруте дня")
    return {
        "text": result.text,
        "source": result.source,
        "reason": result.reason,
        "by_stop": by_stop,
        "silent": result.text.strip() == KEEPER_SILENT_COPY,
        "used_llm": result.used_llm,
        "budget": result.budget_snapshot,
    }


# ── W3c: threats view-model (deterministic list + optional Keeper prose) ─


def threats_from_kg_payload(
    payload: Mapping[str, Any] | None,
    *,
    forget_min: float = 0.28,
    limit: int = 8,
) -> list[dict[str, object]]:
    """Build threat rows from payload decay_vector + node labels/due."""
    payload = payload or {}
    nodes = payload.get("nodes") or []
    labels: dict[str, str] = {}
    due_map: dict[str, Any] = {}
    for n in nodes:
        if not isinstance(n, Mapping):
            continue
        cid = str(n.get("id") or "").strip()
        if not cid:
            continue
        labels[cid] = str(n.get("label") or cid)
        if n.get("due") is not None:
            due_map[cid] = n.get("due")
    decay = payload.get("decay_vector")
    if not isinstance(decay, Mapping):
        decay = {}
    return build_threats_from_decay(
        decay_vector=decay,
        labels=labels,
        due_map=due_map,
        forget_min=forget_min,
        limit=limit,
    )


def build_threats_view_model(
    payload: Mapping[str, Any] | None,
    *,
    session_state: MutableMapping[str, Any] | None = None,
    allow_llm: bool = False,
    snapshot_date: str = "",
    forget_min: float = 0.28,
    llm_complete: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """W3c: hall-ready threats dict.

    ``items`` is always deterministic (decay/due). ``text`` is prose (static or LLM).
    CTA «Повторить» (W2b) remains the action to dispel fog — not generated here.
    """
    payload = payload or {}
    items = threats_from_kg_payload(payload, forget_min=forget_min)
    snap = str(snapshot_date or "").strip()
    if not snap:
        hist = payload.get("mastery_history") or []
        if hist and isinstance(hist[-1], Mapping):
            snap = str(hist[-1].get("date") or "").strip()
    result = request_keeper(
        prompts.SCENARIO_THREATS,
        snapshot_date=snap,
        threats=items,
        allow_llm=allow_llm,
        session_state=session_state,
        llm_complete=llm_complete,
    )
    # Compact rows for canvas/panel (JSON-safe).
    safe_items: list[dict[str, object]] = []
    for t in items:
        safe_items.append(
            {
                "id": str(t.get("id") or ""),
                "label": str(t.get("label") or t.get("id") or ""),
                "forget_pct": int(t.get("forget_pct") or 0),
                "due": t.get("due"),
                "retention": t.get("retention"),
            }
        )
    return {
        "text": result.text,
        "source": result.source,
        "reason": result.reason,
        "items": safe_items,
        "count": len(safe_items),
        "silent": result.text.strip() == KEEPER_SILENT_COPY,
        "used_llm": result.used_llm,
        "budget": result.budget_snapshot,
        # Hint for UI: review action dispels fog (W2b), not a new action.
        "review_action": "review",
    }


# ── W3d: quest view-model (one-line morning goal; degrade = «N из M») ────


def _route_done_count(payload: Mapping[str, Any] | None, route_ids: list[str]) -> int:
    """Count day-route stops already touched (learned or mastery ≥ 0.8)."""
    payload = payload or {}
    by_id: dict[str, Mapping[str, Any]] = {}
    for n in payload.get("nodes") or []:
        if not isinstance(n, Mapping):
            continue
        cid = str(n.get("id") or "").strip()
        if cid:
            by_id[cid] = n
    done = 0
    for rid in route_ids:
        n = by_id.get(rid) or {}
        try:
            mastery = float(n.get("mastery") or 0.0)
        except (TypeError, ValueError):
            mastery = 0.0
        if mastery > 1.0:
            mastery = mastery / 100.0
        if bool(n.get("learned")) or mastery >= 0.8:
            done += 1
    return done


def build_quest_view_model(
    payload: Mapping[str, Any] | None,
    *,
    session_state: MutableMapping[str, Any] | None = None,
    allow_llm: bool = False,
    snapshot_date: str = "",
    llm_complete: Callable[[str, str], str] | None = None,
) -> dict[str, Any]:
    """W3d / Keeper D: hall-ready quest line ``{text, source, stop_count, done_count, focus}``.

    First paint: ``allow_llm=False`` → degrade «d из n» (+ focus label).
    Optional LLM: one respectful morning-goal sentence (budget/cache via Keeper).
    """
    payload = payload or {}
    stops = stops_from_kg_payload(payload)
    route = [str(s.get("id") or "") for s in stops if str(s.get("id") or "").strip()]
    focus = str((stops[0] or {}).get("label") or (route[0] if route else "")).strip()
    done_count = _route_done_count(payload, route)
    snap = str(snapshot_date or "").strip()
    if not snap:
        hist = payload.get("mastery_history") or []
        if hist and isinstance(hist[-1], Mapping):
            snap = str(hist[-1].get("date") or "").strip()
    result = request_keeper(
        prompts.SCENARIO_QUEST,
        snapshot_date=snap,
        day_route=route,
        stops=stops,
        focus=focus,
        done_count=done_count,
        allow_llm=allow_llm,
        session_state=session_state,
        llm_complete=llm_complete,
    )
    text = str(result.text or "").strip()
    if len(text) > 200:
        text = text[:199].rstrip() + "…"
    return {
        "text": text,
        "source": result.source,
        "reason": result.reason,
        "stop_count": len(route),
        "done_count": done_count,
        "focus": focus,
        "silent": text == KEEPER_SILENT_COPY or not text,
        "used_llm": result.used_llm,
        "budget": result.budget_snapshot,
    }


def assemble_keeper_hall_vms(
    payload: Mapping[str, Any] | None,
    *,
    session_state: MutableMapping[str, Any] | None = None,
    allow_guide_llm: bool = False,
    allow_threats_llm: bool = False,
    allow_quest_llm: bool = False,
    snapshot_date: str = "",
    llm_complete: Callable[[str, str], str] | None = None,
) -> dict[str, dict[str, Any]]:
    """W3b/c/d: build guide + threats + quest for the 3D hall in one place."""
    return {
        "guide": build_guide_view_model(
            payload,
            session_state=session_state,
            allow_llm=allow_guide_llm,
            snapshot_date=snapshot_date,
            llm_complete=llm_complete,
        ),
        "threats": build_threats_view_model(
            payload,
            session_state=session_state,
            allow_llm=allow_threats_llm,
            snapshot_date=snapshot_date,
            llm_complete=llm_complete,
        ),
        "quest": build_quest_view_model(
            payload,
            session_state=session_state,
            allow_llm=allow_quest_llm,
            snapshot_date=snapshot_date,
            llm_complete=llm_complete,
        ),
    }
