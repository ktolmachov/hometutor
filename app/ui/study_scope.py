"""StudyScope — session state helpers for Course Workspace (Package AB).

Active course scope lives in ``st.session_state`` as the reactive mirror and is
persisted to ``app_kv`` (``data/user_state.db``) so it survives a Streamlit
restart — same mechanism as the Living Konspekt workbench cart
(``app/workbench_service.py`` / ``app/ui/living_konspekt_state.py``).

Persistence is gated by ``state``: ``None`` (real Streamlit session) writes
through to ``app_kv``; an injected mapping (unit tests) stays session-only.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, MutableMapping

if TYPE_CHECKING:
    pass

ACTIVE_SCOPE_KEY = "active_study_scope"
LAST_DEACTIVATED_SCOPE_KEY = "last_deactivated_study_scope"
_SCOPE_DERIVED_STATE_KEYS = ("last_synthesis", "last_learning_plan", "last_answer")
_SCOPE_QUIZ_KEY_PREFIX = "topic_scope_quiz_"

_ACTIVE_SCOPE_KV_KEY = "study_scope.active"
_LAST_DEACTIVATED_SCOPE_KV_KEY = "study_scope.last_deactivated"
_SCOPE_HYDRATED_KEY = "_study_scope_hydrated"


def _state(state: MutableMapping[str, Any] | None) -> MutableMapping[str, Any]:
    import streamlit as st

    return state if state is not None else st.session_state


def _scope_id(folder_rel: str) -> str:
    return hashlib.sha256(folder_rel.encode()).hexdigest()[:12]


def _clear_scope_derived_state(target: MutableMapping[str, Any] | None = None) -> None:
    """Reset all session state that may contain out-of-scope artifacts."""
    target = _state(target)
    for key in _SCOPE_DERIVED_STATE_KEYS:
        target[key] = None
    for key in list(target.keys()):
        if isinstance(key, str) and key.startswith(_SCOPE_QUIZ_KEY_PREFIX):
            target[key] = {}


# --- app_kv persistence (best-effort, mirrors workbench_service) ---


def _kv_get_json(key: str) -> Any:
    from app.user_state_core import get_kv

    raw = get_kv(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _kv_set_json(key: str, value: dict[str, Any]) -> None:
    from app.user_state_core import set_kv

    set_kv(key, json.dumps(value, ensure_ascii=False))


def _kv_clear(key: str) -> None:
    from app.user_state_core import set_kv

    set_kv(key, "")


def _persist_active_scope(scope: dict[str, Any]) -> None:
    try:
        _kv_set_json(_ACTIVE_SCOPE_KV_KEY, scope)
    except Exception:  # noqa: BLE001 - persistence is best-effort; must not break activate
        pass


def _persist_last_deactivated(scope: dict[str, Any]) -> None:
    normalized = _normalize_scope_payload(scope)
    if normalized is None:
        return
    try:
        _kv_set_json(_LAST_DEACTIVATED_SCOPE_KV_KEY, normalized)
    except Exception:  # noqa: BLE001 - persistence is best-effort; must not break deactivate
        pass


def _clear_active_scope_kv() -> None:
    try:
        _kv_clear(_ACTIVE_SCOPE_KV_KEY)
    except Exception:  # noqa: BLE001 - kv cleanup must not break deactivate
        pass


def _clear_last_deactivated_kv() -> None:
    try:
        _kv_clear(_LAST_DEACTIVATED_SCOPE_KV_KEY)
    except Exception:  # noqa: BLE001 - kv cleanup must not break restore
        pass


def _normalize_scope_payload(scope: dict[str, Any]) -> dict[str, Any] | None:
    folder_rel = str(scope.get("folder_rel") or "").strip()
    if not folder_rel:
        return None
    return {
        "id": str(scope.get("id") or _scope_id(folder_rel)),
        "title": str(scope.get("title") or folder_rel),
        "folder_rel": folder_rel,
        "source_paths": list(scope.get("source_paths") or []),
        "created_at": str(scope.get("created_at") or datetime.now(timezone.utc).isoformat()),
    }


def _load_active_scope_from_kv() -> dict[str, Any] | None:
    data = _kv_get_json(_ACTIVE_SCOPE_KV_KEY)
    if not isinstance(data, dict):
        return None
    return _normalize_scope_payload(data)


def _load_last_deactivated_from_kv() -> dict[str, Any] | None:
    data = _kv_get_json(_LAST_DEACTIVATED_SCOPE_KV_KEY)
    if not isinstance(data, dict):
        return None
    return _normalize_scope_payload(data)


def _scope_folder_exists(folder_rel: str) -> bool:
    """Return True if the course folder for ``folder_rel`` still exists on disk."""
    from app.path_safety import resolve_data_relative_path

    try:
        return resolve_data_relative_path(folder_rel).exists()
    except (ValueError, OSError):
        return False


def activate_scope(
    *,
    folder_rel: str,
    title: str | None = None,
    source_paths: list[str] | None = None,
    state: MutableMapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Set active study scope in session state and return the scope dict.

    When ``state`` is ``None`` (real Streamlit session) the scope is also
    persisted to ``app_kv`` so it survives a restart. Injecting a ``state``
    mapping (unit tests) skips persistence.
    """
    target = _state(state)
    scope: dict[str, Any] = {
        "id": _scope_id(folder_rel),
        "title": title or folder_rel,
        "folder_rel": folder_rel,
        "source_paths": list(source_paths or []),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "active": True,
    }
    target[ACTIVE_SCOPE_KEY] = scope
    _clear_scope_derived_state(target)
    if state is None:
        _persist_active_scope(scope)
    return scope


def _save_last_deactivated_scope(
    scope: dict[str, Any], target: MutableMapping[str, Any]
) -> None:
    normalized = _normalize_scope_payload(scope)
    if normalized is None:
        return
    target[LAST_DEACTIVATED_SCOPE_KEY] = normalized


def deactivate_scope(state: MutableMapping[str, Any] | None = None) -> None:
    """Clear active study scope → return to global mode."""
    target = _state(state)
    scope = target.get(ACTIVE_SCOPE_KEY)
    if isinstance(scope, dict):
        _save_last_deactivated_scope(scope, target)
        if state is None:
            _persist_last_deactivated(scope)
    target.pop(ACTIVE_SCOPE_KEY, None)
    _clear_scope_derived_state(target)
    if state is None:
        _clear_active_scope_kv()


def get_last_deactivated_scope(
    state: MutableMapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the most recently deactivated scope, if any."""
    target = _state(state)
    scope = target.get(LAST_DEACTIVATED_SCOPE_KEY)
    if not isinstance(scope, dict):
        return None
    return _normalize_scope_payload(scope)


def restore_scope(state: MutableMapping[str, Any] | None = None) -> dict[str, Any] | None:
    """Re-activate the most recently deactivated study scope."""
    target = _state(state)
    last = get_last_deactivated_scope(state)
    if last is None:
        return None
    restored = activate_scope(
        folder_rel=last["folder_rel"],
        title=last["title"],
        source_paths=list(last.get("source_paths") or []),
        state=state,
    )
    target.pop(LAST_DEACTIVATED_SCOPE_KEY, None)
    if state is None:
        _clear_last_deactivated_kv()
    return restored


def restore_scope_from_app_kv(
    state: MutableMapping[str, Any] | None = None,
) -> str | None:
    """Hydrate the active/last-deactivated scope from ``app_kv`` once per session.

    Called at UI startup. If ``st.session_state`` has no active scope but
    ``app_kv`` persists one, the scope is silently restored — provided its
    course folder still exists on disk. A missing folder degrades to no-scope
    and returns a one-line notice (caller renders it). Injecting ``state``
    (unit tests) skips ``app_kv`` access.
    """
    target = _state(state)
    if target.get(_SCOPE_HYDRATED_KEY):
        return None
    target[_SCOPE_HYDRATED_KEY] = True
    if state is not None:
        return None

    notice: str | None = None
    try:
        if not target.get(ACTIVE_SCOPE_KEY):
            active = _load_active_scope_from_kv()
            if active:
                folder_rel = str(active.get("folder_rel") or "")
                if folder_rel and _scope_folder_exists(folder_rel):
                    active["active"] = True
                    target[ACTIVE_SCOPE_KEY] = active
                else:
                    _clear_active_scope_kv()
                    title = str(active.get("title") or folder_rel or "курс")
                    notice = f"Курс «{title}» больше не найден и был отключен."
        if not target.get(LAST_DEACTIVATED_SCOPE_KEY):
            last = _load_last_deactivated_from_kv()
            if last:
                target[LAST_DEACTIVATED_SCOPE_KEY] = last
    except Exception:  # noqa: BLE001 - hydration must never crash UI startup
        return notice
    return notice


def get_active_scope(
    state: MutableMapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return active scope dict or None if in global mode."""
    target = _state(state)
    scope = target.get(ACTIVE_SCOPE_KEY)
    if not isinstance(scope, dict) or not scope.get("active"):
        return None
    return scope


def scope_folder_rel(
    state: MutableMapping[str, Any] | None = None,
) -> str | None:
    """Return folder_rel from active scope, or None."""
    scope = get_active_scope(state)
    return scope["folder_rel"] if scope else None


def apply_scope_folder_rel(
    current: str | None,
    state: MutableMapping[str, Any] | None = None,
) -> str | None:
    """Override current folder_rel with active scope's value if scope is active."""
    override = scope_folder_rel(state)
    return override if override else current


def folder_rel_from_paths(paths: list[str]) -> str | None:
    """Derive the most common top-level folder from a list of relative document paths."""
    from pathlib import PurePosixPath

    counts: dict[str, int] = {}
    for p in paths:
        parts = PurePosixPath(p).parts
        if len(parts) >= 2:
            counts[parts[0]] = counts.get(parts[0], 0) + 1
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])
