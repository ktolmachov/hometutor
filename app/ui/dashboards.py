"""Dashboard tabs: learning progress, knowledge graph, personalization settings."""

from __future__ import annotations

# Re-expose tab renderers for UI fragments/router compatibility
from app.ui.dashboards_progress import (
    _render_learning_progress_tab,
    _render_course_progress_panel,
    _render_personalization_settings,
)

from app.ui.dashboards_graph import (
    _render_knowledge_graph_tab,
)
