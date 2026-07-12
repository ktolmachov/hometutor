"""Pure helpers for level-based UI navigation visibility."""
from __future__ import annotations

from app.ui.constants import ALL_VIEWS
from app.ui.feature_registry import (
    context_ok_for_feature,
    features_for_surface,
)
from app.ui_preferences import feature_visible


def hidden_nav_views_for_level(level: str, overrides: dict[str, bool]) -> set[str]:
    hidden: set[str] = set()
    for spec in features_for_surface("nav"):
        if spec.view_name and not feature_visible(
            spec,
            level=level,
            overrides=overrides,
            context_ok=context_ok_for_feature(spec),
        ):
            hidden.add(spec.view_name)
    return hidden


def _is_requirement_hidden(spec) -> bool:
    """True when the spec has unmet requirements (agent_enabled, active_course, etc.)."""
    return bool(spec.requires) and not context_ok_for_feature(spec)


def visible_nav_views_for_level(
    level: str,
    overrides: dict[str, bool],
    *,
    current_view: str | None = None,
) -> list[str]:
    hidden = hidden_nav_views_for_level(level, overrides)
    visible = [view for view in ALL_VIEWS if view not in hidden]
    current = str(current_view or "").strip()
    # Allow stale current_view to survive tier changes (deeplink recovery),
    # but NOT requirement changes (e.g. AGENT_ENABLED toggled off) —
    # requirement-hidden views remain excluded even from the deeplink bridge.
    if current in ALL_VIEWS and current not in visible:
        spec = _nav_spec_for_view(current)
        if spec is not None and not _is_requirement_hidden(spec):
            visible.append(current)
    return visible


def _nav_spec_for_view(view_name: str) -> object | None:
    for spec in features_for_surface("nav"):
        if spec.view_name == view_name:
            return spec
    return None
