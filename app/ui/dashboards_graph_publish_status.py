"""Publish-status UI and staging preview helpers for the graph dashboard."""

from __future__ import annotations

from pathlib import Path

import streamlit as st


def get_graph_publish_status() -> dict | None:
    try:
        from app.graph_publish_status import get_graph_publish_status as _get_status

        return _get_status()
    except Exception:  # noqa: BLE001 - status is optional enrichment for both surfaces
        return None


def render_graph_publish_status(status: dict | None = None) -> dict | None:
    if status is None:
        status = get_graph_publish_status()
    try:
        from app.graph_publish_status import build_learner_publish_status_view
    except Exception:  # noqa: BLE001 - diagnostics must not block graph rendering
        st.caption("Статус карты временно недоступен.")
        return None

    view = build_learner_publish_status_view(status)
    primary = str(view.get("primary") or "")
    tone = str(view.get("tone") or "info")
    if tone == "success":
        st.success(primary)
    elif tone == "warning":
        st.warning(primary, icon="⚠️")
    else:
        st.info(primary)
    for caption in view.get("captions") or []:
        st.caption(str(caption))

    failed_title = view.get("failed_title")
    if failed_title:
        with st.expander(str(failed_title), expanded=False):
            metrics = [
                str(metric)
                for metric in (view.get("failed_metrics") or [])
                if str(metric).strip()
            ]
            if metrics:
                st.caption(" · ".join(metrics))
            for reason in list(view.get("failed_reasons") or [])[:6]:
                st.caption(f"- {reason}")
            debug_lines = [
                str(line)
                for line in (view.get("debug_lines") or [])
                if str(line).strip()
            ]
            if debug_lines:
                st.caption("Отладка: " + " · ".join(debug_lines[:4]))
    elif view.get("debug_lines"):
        with st.expander("Технические детали карты", expanded=False):
            for line in view["debug_lines"]:
                st.caption(str(line))
    return status


def load_staging_preview_graph(status: dict | None):
    """Load the latest failed staging graph for a read-only UI preview."""
    if not isinstance(status, dict):
        return None, None
    failed = status.get("latest_failed_staging")
    if not isinstance(failed, dict) or not failed.get("exists"):
        return None, None
    raw_bundle_dir = str(failed.get("bundle_dir") or "").strip()
    if not raw_bundle_dir:
        return None, None
    try:
        from app.knowledge_graph import SqliteBundleKnowledgeGraph

        graph = SqliteBundleKnowledgeGraph(Path(raw_bundle_dir))
        if graph.get_concepts():
            return graph, failed
    except Exception:  # noqa: BLE001 - staging preview must not break the published graph
        return None, None
    return None, None
