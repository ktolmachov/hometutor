"""StudyScope — session state helpers for Course Workspace (Package AB)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

ACTIVE_SCOPE_KEY = "active_study_scope"
_SCOPE_DERIVED_STATE_KEYS = ("last_synthesis", "last_learning_plan", "last_answer")
_SCOPE_QUIZ_KEY_PREFIX = "topic_scope_quiz_"


def _scope_id(folder_rel: str) -> str:
    return hashlib.sha256(folder_rel.encode()).hexdigest()[:12]


def _clear_scope_derived_state() -> None:
    """Reset all session state that may contain out-of-scope artifacts."""
    import streamlit as st

    for key in _SCOPE_DERIVED_STATE_KEYS:
        st.session_state[key] = None
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(_SCOPE_QUIZ_KEY_PREFIX):
            st.session_state[key] = {}


def activate_scope(
    *,
    folder_rel: str,
    title: str | None = None,
    source_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Set active study scope in session state and return the scope dict."""
    import streamlit as st

    scope: dict[str, Any] = {
        "id": _scope_id(folder_rel),
        "title": title or folder_rel,
        "folder_rel": folder_rel,
        "source_paths": list(source_paths or []),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "active": True,
    }
    st.session_state[ACTIVE_SCOPE_KEY] = scope
    _clear_scope_derived_state()
    return scope


def deactivate_scope() -> None:
    """Clear active study scope → return to global mode."""
    import streamlit as st

    st.session_state.pop(ACTIVE_SCOPE_KEY, None)
    _clear_scope_derived_state()


def get_active_scope() -> dict[str, Any] | None:
    """Return active scope dict or None if in global mode."""
    import streamlit as st

    scope = st.session_state.get(ACTIVE_SCOPE_KEY)
    if not isinstance(scope, dict) or not scope.get("active"):
        return None
    return scope


def scope_folder_rel() -> str | None:
    """Return folder_rel from active scope, or None."""
    scope = get_active_scope()
    return scope["folder_rel"] if scope else None


def apply_scope_folder_rel(current: str | None) -> str | None:
    """Override current folder_rel with active scope's value if scope is active."""
    override = scope_folder_rel()
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
