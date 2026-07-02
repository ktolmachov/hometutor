"""Pure helpers for level-based UI navigation visibility."""
from __future__ import annotations

from app.ui.constants import ALL_VIEWS
from app.ui.feature_registry import features_for_surface
from app.ui_preferences import feature_visible


def hidden_nav_views_for_level(level: str, overrides: dict[str, bool]) -> set[str]:
    hidden: set[str] = set()
    for spec in features_for_surface("nav"):
        if spec.view_name and not feature_visible(
            spec,
            level=level,
            overrides=overrides,
        ):
            hidden.add(spec.view_name)
    return hidden


def visible_nav_views_for_level(
    level: str,
    overrides: dict[str, bool],
    *,
    current_view: str | None = None,
) -> list[str]:
    hidden = hidden_nav_views_for_level(level, overrides)
    visible = [view for view in ALL_VIEWS if view not in hidden]
    current = str(current_view or "").strip()
    if current in ALL_VIEWS and current not in visible:
        visible.append(current)
    return visible
