"""W5b/W5b.1: read-only scene-DSL schema, validator, presentation apply.

Vision §6.3 F: commands may only describe presentation
(``filter/focus/scene_mode/overlay/route_override``). Domain ``day_route`` is
never mutated. Unknown keys and write-like ops are rejected.

W5b = schema/validator. W5b.1 = map validated envelopes → presentation state
for the hall (no domain write, no JS eval).
"""

from __future__ import annotations

from typing import Any, Mapping

SCENE_DSL_VERSION = 1

ALLOWED_SCENE_MODES = frozenset({"route", "local", "all"})
ALLOWED_OVERLAYS = frozenset({"memory", "fog", "calm", "replay", "none"})
ALLOWED_COMMANDS = frozenset(
    {
        "filter",
        "focus",
        "set_scene_mode",
        "set_overlay",
        "route_override",
        "clear",
    }
)
_FORBIDDEN_KEYS = frozenset(
    {
        "write",
        "eval",
        "script",
        "js",
        "mastery",
        "user_state",
        "workbench",
        "gamification",
        "quiz",
        "sql",
        "exec",
    }
)
_ALLOWED_TOP = frozenset(
    {
        "version",
        "command",
        "node_id",
        "node_ids",
        "scene_mode",
        "overlay",
        "filter",
        "route_override",
        "query",
    }
)


class SceneDslError(ValueError):
    """Invalid scene-DSL envelope."""


def _check_keys(raw: Mapping[str, Any]) -> None:
    for key in raw:
        k = str(key or "").strip().lower()
        if k in _FORBIDDEN_KEYS:
            raise SceneDslError(f"forbidden_key:{k}")
        if k and k not in _ALLOWED_TOP:
            raise SceneDslError(f"unknown_key:{k}")


def _parse_id_list(
    raw_ids: Any,
    *,
    allowed_nodes: set[str],
    err_prefix: str,
) -> list[str]:
    if raw_ids is None:
        return []
    if not isinstance(raw_ids, (list, tuple)):
        raise SceneDslError(f"{err_prefix}_not_list")
    out: list[str] = []
    for item in raw_ids:
        cid = str(item or "").strip()
        if not cid:
            continue
        if allowed_nodes and cid not in allowed_nodes:
            raise SceneDslError(f"unknown_{err_prefix}:{cid}")
        out.append(cid)
    return out


def validate_scene_dsl(
    raw: Mapping[str, Any] | None,
    *,
    node_ids: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """Validate a scene-DSL envelope; return a sanitized dict or raise."""
    if not isinstance(raw, Mapping):
        raise SceneDslError("envelope_not_object")
    _check_keys(raw)
    try:
        version = int(raw.get("version"))
    except (TypeError, ValueError) as exc:
        raise SceneDslError("bad_version") from exc
    if version != SCENE_DSL_VERSION:
        raise SceneDslError("unsupported_version")

    command = str(raw.get("command") or "").strip().lower()
    if command not in ALLOWED_COMMANDS:
        raise SceneDslError("unknown_command")

    allowed_nodes = {str(n).strip() for n in (node_ids or set()) if str(n).strip()}
    node_id = str(raw.get("node_id") or "").strip()
    if node_id and allowed_nodes and node_id not in allowed_nodes:
        raise SceneDslError("unknown_node_id")

    node_ids_out = _parse_id_list(
        raw.get("node_ids"), allowed_nodes=allowed_nodes, err_prefix="node_id"
    )
    scene_mode = str(raw.get("scene_mode") or "").strip().lower()
    if scene_mode and scene_mode not in ALLOWED_SCENE_MODES:
        raise SceneDslError("bad_scene_mode")
    overlay = str(raw.get("overlay") or "").strip().lower()
    if overlay and overlay not in ALLOWED_OVERLAYS:
        raise SceneDslError("bad_overlay")
    filt = str(raw.get("filter") or "").strip()
    if len(filt) > 80:
        raise SceneDslError("filter_too_long")
    route_override = _parse_id_list(
        raw.get("route_override"),
        allowed_nodes=allowed_nodes,
        err_prefix="route_node",
    )
    if command == "route_override" and raw.get("route_override") is not None and not route_override:
        raise SceneDslError("empty_route_override")
    query = str(raw.get("query") or "").strip()
    if len(query) > 200:
        raise SceneDslError("query_too_long")

    out: dict[str, Any] = {"version": SCENE_DSL_VERSION, "command": command}
    if node_id:
        out["node_id"] = node_id
    if node_ids_out:
        out["node_ids"] = node_ids_out
    if scene_mode:
        out["scene_mode"] = scene_mode
    if overlay:
        out["overlay"] = overlay
    if filt:
        out["filter"] = filt
    if route_override:
        out["route_override"] = route_override
        out["route_override_presentation_only"] = True
    if query:
        out["query"] = query
    return out


def try_validate_scene_dsl(
    raw: Mapping[str, Any] | None,
    *,
    node_ids: set[str] | frozenset[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Non-raising helper: ``(ok_dict, None)`` or ``(None, reason)``."""
    try:
        return validate_scene_dsl(raw, node_ids=node_ids), None
    except SceneDslError as exc:
        return None, str(exc)


def presentation_from_dsl(validated: Mapping[str, Any] | None) -> dict[str, Any]:
    """Map a *validated* DSL envelope to hall presentation state (W5b.1).

    Never mutates domain day_route. ``route_override`` is highlight-only.
    """
    if not isinstance(validated, Mapping):
        return empty_presentation()
    command = str(validated.get("command") or "").strip().lower()
    state = empty_presentation()
    if command == "clear":
        return state
    if command == "set_scene_mode":
        mode = str(validated.get("scene_mode") or "").strip().lower()
        if mode in ALLOWED_SCENE_MODES:
            state["scene_mode"] = mode
    if command == "set_overlay":
        overlay = str(validated.get("overlay") or "").strip().lower()
        if overlay in ALLOWED_OVERLAYS:
            state["overlay"] = overlay
    if command == "filter":
        state["filter"] = str(validated.get("filter") or "").strip()
    if command == "focus":
        state["focus_id"] = str(validated.get("node_id") or "").strip()
        extra = validated.get("node_ids") or []
        if isinstance(extra, (list, tuple)) and extra and not state["focus_id"]:
            state["focus_id"] = str(extra[0] or "").strip()
    if command == "route_override":
        route = validated.get("route_override") or []
        if isinstance(route, (list, tuple)):
            state["route_override"] = [str(x).strip() for x in route if str(x).strip()]
        state["route_override_presentation_only"] = True
    # Composite fields allowed on any command when present after validate.
    if validated.get("scene_mode") and not state.get("scene_mode"):
        mode = str(validated.get("scene_mode") or "").strip().lower()
        if mode in ALLOWED_SCENE_MODES:
            state["scene_mode"] = mode
    if validated.get("overlay") and not state.get("overlay"):
        overlay = str(validated.get("overlay") or "").strip().lower()
        if overlay in ALLOWED_OVERLAYS:
            state["overlay"] = overlay
    if validated.get("filter") and not state.get("filter"):
        state["filter"] = str(validated.get("filter") or "").strip()
    state["domain_day_route_unchanged"] = True
    return state


def empty_presentation() -> dict[str, Any]:
    """Neutral presentation (domain route untouched)."""
    return {
        "scene_mode": None,
        "overlay": None,
        "filter": "",
        "focus_id": "",
        "route_override": [],
        "route_override_presentation_only": True,
        "domain_day_route_unchanged": True,
    }


# Named presets for hall UI (no free-text NL required).
SCENE_PRESETS: dict[str, dict[str, Any]] = {
    "clear": {"version": SCENE_DSL_VERSION, "command": "clear"},
    "route": {
        "version": SCENE_DSL_VERSION,
        "command": "set_scene_mode",
        "scene_mode": "route",
    },
    "local": {
        "version": SCENE_DSL_VERSION,
        "command": "set_scene_mode",
        "scene_mode": "local",
    },
    "all": {
        "version": SCENE_DSL_VERSION,
        "command": "set_scene_mode",
        "scene_mode": "all",
    },
    "calm": {
        "version": SCENE_DSL_VERSION,
        "command": "set_overlay",
        "overlay": "calm",
    },
    "weak": {
        "version": SCENE_DSL_VERSION,
        "command": "filter",
        "filter": "weak",
    },
}


def preset_presentation(name: str) -> dict[str, Any]:
    """Validate a named preset and return presentation state."""
    raw = SCENE_PRESETS.get(str(name or "").strip().lower())
    if raw is None:
        return empty_presentation()
    ok, _err = try_validate_scene_dsl(raw, node_ids=None)
    if ok is None:
        return empty_presentation()
    return presentation_from_dsl(ok)
